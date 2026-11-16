#!/usr/bin/env python3
"""Job journal, state machine and reconciliation for knowledge-ingestor.

Every ingest is journaled to dbs/<db>/jobs/<jobid>.json before work starts and
each item's outcome is written there before the cursor advances, so any process
can pick a job up from where it stopped. Ingestion is fully model-free: the
embedding encoder is optional at every step, and records whose vectors are
missing are a resumable state (pending embed) rather than a failure.
"""
import json, os, re, shutil, threading, time
import kbcore

MAX_ATTEMPTS = 3
BACKOFF = (3.0, 10.0, 30.0)
POLITE_URL_SLEEP = 3.0
JOBS_KEPT = 20
EVENT_CAP = 5000
CLAIM_TTL = 6 * 3600

_LIVE = {}           # db path -> running worker thread (this process)
_LIVE_LOCK = threading.Lock()
_ENC_CACHE = {"enc": None, "failed": False, "why": ""}
_ENC_LOCK = threading.Lock()

TRANSIENT = ("timeout", "timed out", "temporarily", "connection reset", "reset by peer",
             "refused", "unreachable", "ssl", "429", " 500", " 502", " 503", " 504",
             "aborted", "too many requests")


def enc_factory():
    with _ENC_LOCK:
        if _ENC_CACHE["enc"] is None and not _ENC_CACHE["failed"]:
            try:
                _ENC_CACHE["enc"] = kbcore.Encoder()
            except Exception as e:
                _ENC_CACHE["failed"] = True
                _ENC_CACHE["why"] = f"{type(e).__name__}: {e}"
        return _ENC_CACHE["enc"]


def model_state():
    """Cache-only availability probe: never loads the model."""
    if os.environ.get("KB_DISABLE_MODEL"):
        return False
    with _ENC_LOCK:
        if _ENC_CACHE["enc"] is not None:
            return True
        if _ENC_CACHE["failed"]:
            return False
    return "unloaded"


def _now():
    return time.strftime("%F %T")


def _jdir(db_path):
    return os.path.join(db_path, "jobs")


def journal_of(path, jid):
    return os.path.join(_jdir(path), f"{jid}.json")


def _atomic_json(fp, data):
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, fp)


def log(path, jid, ev):
    ev = {"ts": _now(), **ev}
    fp = os.path.join(_jdir(path), f"{jid}.events.jsonl")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    try:
        if os.path.exists(fp) and sum(1 for _ in open(fp)) > EVENT_CAP:
            lines = open(fp).readlines()[-2000:]
            open(fp, "w").writelines(lines)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        pass


def create_job(db_path, items, note=""):
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    its = []
    for it in items:
        kind, target = it[0], str(it[1])[:500]
        meta = it[2] if len(it) > 2 and isinstance(it[2], dict) else {}
        its.append({"kind": kind, "target": target, "status": "pending",
                    "attempts": 0, "why": "", "meta": meta})
    j = {"jobid": jid, "db": os.path.basename(db_path), "created": _now(),
         "state": "queued", "cursor": 0, "note": note, "stats": {"added": 0, "parked": 0, "dups": 0},
         "items": its}
    os.makedirs(_jdir(db_path), exist_ok=True)
    _atomic_json(journal_of(db_path, jid), j)
    _prune(db_path)
    log(db_path, jid, {"ev": "created", "items": len(items), "note": note[:80]})
    return j


def _prune(db_path):
    jdir = _jdir(db_path)
    try:
        entries = [f for f in os.listdir(jdir) if f.endswith(".json")]
    except OSError:
        return
    closed, stale = [], []
    for f in entries:
        fp = os.path.join(jdir, f)
        try:
            st = json.load(open(fp))
        except Exception:
            stale.append((f, 0)); continue
        (closed if st.get("state") in ("done", "parked", "error", "refused") else stale).append(
            (f, os.path.getmtime(fp)))
    dead = sorted(closed, key=lambda x: -x[1])[JOBS_KEPT:] + stale[5:]
    for f, _ in dead:
        for suffix in (".json", ".events.jsonl"):
            try: os.unlink(os.path.join(jdir, f[:-5] + suffix))
            except OSError: pass


def try_claim(db_path, jid):
    """Single writer per journal. A claim from a dead pid may be taken over."""
    fp = journal_of(db_path, jid) + ".claim"
    me = {"pid": os.getpid(), "ts": time.time()}
    try:
        fd = os.open(fp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, json.dumps(me).encode()); os.close(fd)
        return True
    except FileExistsError:
        try:
            old = json.load(open(fp))
        except Exception:
            old = {}
        alive = False
        if isinstance(old.get("pid"), int):
            try: os.kill(old["pid"], 0); alive = True
            except OSError: alive = False
        if alive and time.time() - float(old.get("ts") or 0) < CLAIM_TTL:
            return False
        tmp = fp + ".takeover"
        with open(tmp, "w") as f: f.write(json.dumps(me))
        os.replace(tmp, fp)
        return True


def unclaim(db_path, jid):
    try: os.unlink(journal_of(db_path, jid) + ".claim")
    except OSError: pass


def _classify(msg, code):
    s = f"{code or ''} {msg}".lower()
    if "404" in s or "410" in s or "no such record" in s:
        return "permanent"
    return "transient" if any(m in s for m in TRANSIENT) else "permanent"


def _host(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


def extract_url(db_path, url, meta=None):
    """Dispatch behavior tree for one URL. Returns (outcome, records, why)
    with outcome in ok / permanent / transient."""
    meta = meta or {}
    base = {"t": (meta.get("t") or "") or (url.split("/")[-1] or url)[:110],
            "u": url, "d": meta.get("d", "web"), "s": _host(url) or meta.get("s", ""),
            "f": meta.get("f", "mcp")}
    ok, data, ctype, code = kbcore.fetch(url)
    if not ok:
        why = f"fetch failed ({code or ''}) {str(data, 'utf-8', 'replace')[:100] if data else ''}".strip()
        return (_classify(why, code), [], why)
    lane, handled, why = kbcore.content_route(ctype, data)
    if lane == "unknown":
        return ("permanent", [], f"unsupported content type ({ctype or 'unknown'})")
    if lane == "pdf":
        tmp = os.path.join(db_path, "jobs")
        os.makedirs(tmp, exist_ok=True)
        fp = os.path.join(tmp, f"tmp-{os.urandom(4).hex()}.pdf")
        open(fp, "wb").write(data)
        try:
            text, branch = kbcore.pdf_text_logged(fp)
        finally:
            os.unlink(fp)
        if len(text) < 200:
            return ("permanent", [], f"pdf lane returned too little text ({len(text)}b)")
        base["src"] = "mcp-pdf"
        return ("ok", kbcore.records_from(text, base), f"lane=pdf {branch}")
    if lane == "html":
        text = kbcore.html_text(data.decode("utf-8", "ignore"))
        if len(text) < 300:
            return ("permanent", [], f"html lane returned too little text ({len(text)}b)")
        base["src"] = "mcp-web"
        return ("ok", kbcore.records_from(text, base), "lane=html")
    text = data.decode("utf-8", "ignore").strip()
    if len(text) < 300:
        return ("permanent", [], f"text lane returned too little text ({len(text)}b)")
    base["src"] = "mcp-web"
    return ("ok", kbcore.records_from(text, base), "lane=text")


def extract_pdf(db_path, fp, meta=None):
    """Extraction behavior tree for one PDF file. Returns (outcome, records,
    why, branch)."""
    meta = meta or {}
    title = (meta.get("t") or "") or re.sub(r"^\d{8,}_", "", os.path.basename(fp))[:-4]
    text, branch = kbcore.pdf_text_logged(fp)
    if len(text) >= 200:
        base = {"t": title[:110], "u": f"upload:{os.path.relpath(fp, db_path)}",
                "d": meta.get("d", "document"), "s": meta.get("s", "local-pdf"),
                "f": meta.get("f", "webui"), "src": "webpdf"}
        return ("ok", kbcore.records_from(text, base), "", branch)
    return ("permanent", [], f"no extractable text ({branch}, {len(text)}b)", branch)


def _prj(db_path, j):
    """Projection for the live status card (existing portal fields)."""
    try:
        kbcore.status_set(db_path, {"state": j["state"],
                                    "added": j["stats"].get("added", 0),
                                    "skipped": [i for i in j["items"] if i["status"] == "parked"],
                                    "phase": j.get("phase", ""),
                                    "dups": j["stats"].get("dups", 0),
                                    "jobid": j["jobid"],
                                    "error": "" if j["state"] != "error" else j.get("why", ""),
                                    "pending_embed": j.get("pending_embed", 0)})
    except Exception:
        pass


def run_job(db_path, j):
    """Walk the journal to completion. Model-free: without an encoder the job
    lands every record (lexically searchable at once) and ends in state
    embedding_paused with a resumable pending count."""
    jid = j["jobid"]
    with _LIVE_LOCK:
        if _LIVE.get(db_path):
            return "refused"
        _LIVE[db_path] = threading.current_thread()
    unclaim(db_path, jid)
    try:
        items = j["items"]
        j["state"], j["phase"] = "extracting", ""
        _atomic_json(journal_of(db_path, jid), j); _prj(db_path, j)
        enc = enc_factory()
        work = [idx for idx, it in enumerate(items) if it["status"] not in ("done", "parked", "dup")]
        while work:
            idx = work.pop(0)
            item = items[idx]
            if item["status"] in ("done", "parked", "dup"):
                continue
            if item["attempts"]:
                time.sleep(BACKOFF[min(item["attempts"] - 1, len(BACKOFF) - 1)])
            j["phase"] = f"{'pdf' if item['kind'] == 'pdf' else 'url'} {idx + 1}/{len(items)}: {os.path.basename(item['target'])[:60]}"
            j["state"] = "extracting"
            _prj(db_path, j)
            try:
                if item["kind"] == "pdf":
                    out, recs, why, branch = extract_pdf(db_path, item["target"], item.get("meta"))
                    item["branch"] = branch
                else:
                    if not item["target"].startswith("http"):
                        out, recs, why, branch = "permanent", [], "not http", "none"
                    else:
                        out, recs, why = extract_url(db_path, item["target"], item.get("meta"))
                        branch = why.split()[0] if why else ""
                        item["branch"] = branch
            except Exception as e:
                out, recs, why, branch = "transient", [], f"{type(e).__name__}: {e}", "exception"
            item["attempts"] += 1
            item["n"] = len(recs)
            log(db_path, jid, {"ev": "extract", "idx": idx, "kind": item["kind"],
                               "outcome": out, "branch": branch, "n": len(recs),
                               "attempt": item["attempts"], "why": why[:200]})
            if out == "ok":
                added = kbcore.add_records(db_path, recs, enc, src="journal")
                j["stats"]["added"] += len(added)
                j["stats"]["dups"] += max(0, len(recs) - len(added))
                item["status"], item["why"] = "done", why
            elif out == "permanent":
                item["status"], item["why"] = "parked", why
                j["stats"]["parked"] += 1
            else:
                if item["attempts"] >= MAX_ATTEMPTS:
                    item["status"], item["why"] = "parked", f"transient exhausted: {why}"
                    j["stats"]["parked"] += 1
                else:
                    item["status"], item["why"] = "retry", why
                    work.append(idx)
            if item["status"] != "retry":
                j["cursor"] = idx + 1
            _atomic_json(journal_of(db_path, jid), j)
            if item["kind"] == "url" and out == "ok":
                time.sleep(POLITE_URL_SLEEP)
        if all(it["status"] in ("done", "parked", "dup") for it in items):
            j["cursor"] = len(items)
        audit0 = kbcore.audit_db(db_path)
        j["pending_embed"] = audit0["pending_embed"]
        if audit0["pending_embed"] and enc is None:
            j["state"] = "embedding_paused"
            j["why"] = "records committed; embedding resumes when the model is available"
            _atomic_json(journal_of(db_path, jid), j); _prj(db_path, j)
            log(db_path, jid, {"ev": "paused", "pending_embed": j["pending_embed"],
                               "reason": _ENC_CACHE["why"] or "model unavailable"})
            return "embedding_paused"
        j["state"] = "embedding"
        _prj(db_path, j)
        try:
            kbcore.embed_catchup(db_path, enc)
        except Exception as e:
            j["state"], j["why"] = "embedding_paused", f"embed failed: {type(e).__name__}: {e}"
            _atomic_json(journal_of(db_path, jid), j); _prj(db_path, j)
            log(db_path, jid, {"ev": "embed-failed", "why": j["why"]})
            return "embedding_paused"
        j["state"] = "validating"
        _prj(db_path, j)
        audit = kbcore.audit_db(db_path)
        if audit["verdict"] == "needs_rebuild":
            kbcore.rebuild(db_path, enc)
            audit = kbcore.audit_db(db_path)
        log(db_path, jid, {"ev": "validate", **audit})
        j["state"] = "done"
        _atomic_json(journal_of(db_path, jid), j); _prj(db_path, j)
        log(db_path, jid, {"ev": "done", **j["stats"]})
        return "done"
    finally:
        with _LIVE_LOCK:
            _LIVE[db_path] = None
            _LIVE.pop(db_path, None)
        _chain_next(db_path)


def _chain_next(db_path):
    """Slot-free rule: the oldest still-queued journal without a claim starts."""
    jdir = _jdir(db_path)
    try:
        entries = sorted(os.listdir(jdir))
    except OSError:
        return
    for f in entries:
        if not f.endswith(".json"):
            continue
        jid = f[:-5]
        try:
            jj = json.load(open(os.path.join(jdir, f)))
        except Exception:
            continue
        if jj.get("state") != "queued":
            continue
        if not try_claim(db_path, jid):
            return
        log(db_path, jid, {"ev": "chain-start"})
        threading.Thread(target=run_job, args=(db_path, jj), daemon=True).start()
        return


def start_threaded(db_path, j):
    t = threading.Thread(target=run_job, args=(db_path, j), daemon=True)
    t.start()
    return t


def reconcile(db_path, autostart=True):
    """Startup truth pass: repair stale card state, mark orphaned journals
    interrupted, reschedule pending embeds, and (optionally) resume work.
    Loads no model ever."""
    audit = kbcore.audit_db(db_path)
    if audit["verdict"] == "needs_rebuild":
        kbcore.status_set(db_path, {"state": "needs_rebuild",
                                    "error": "storage desync: rebuild required",
                                    "pending_embed": audit["pending_embed"]})
    elif audit["verdict"] == "pending_embed":
        if not _any_running(db_path):
            kbcore.status_set(db_path, {"state": "embedding_paused",
                                        "error": "", "pending_embed": audit["pending_embed"]})
    elif audit["verdict"] == "ok":
        if _jdir(db_path) and not _any_running(db_path):
            st = kbcore.status_get(db_path)
            if st.get("state") in ("running", "error"):
                kbcore.status_set(db_path, {"state": "idle", "error": "",
                                            "pending_embed": audit["pending_embed"]})
    resumed = []
    jdir = _jdir(db_path)
    if not os.path.isdir(jdir) or autostart is False:
        return resumed
    for f in sorted(os.listdir(jdir)):
        if not f.endswith(".json"):
            continue
        jid = f[:-5]
        try:
            j = json.load(open(os.path.join(jdir, f)))
        except Exception:
            continue
        if j.get("state") in ("queued", "extracting", "embedding", "embedding_paused", "interrupted"):
            if _any_running(db_path) or not try_claim(db_path, jid):
                continue
            _atomic_json(journal_of(db_path, jid), j)
            log(db_path, jid, {"ev": "reconcile-resume", "from": j.get("state")})
            def work(j=j):
                try:
                    run_job(db_path, j)
                except Exception as e:
                    kbcore.status_set(db_path, {"state": "error", "error": f"{type(e).__name__}: {e}"})
                finally:
                    unclaim(db_path, j["jobid"])
            threading.Thread(target=work, daemon=True).start()
            resumed.append(jid)
    return resumed


def _any_running(db_path):
    with _LIVE_LOCK:
        return _LIVE.get(db_path) is not None


def reconcile_all(dbs_root, autostart=True):
    out = {}
    if not os.path.isdir(dbs_root):
        return out
    for name in sorted(os.listdir(dbs_root)):
        p = os.path.join(dbs_root, name)
        if os.path.isfile(os.path.join(p, "pack.jsonl")):
            r = reconcile(p, autostart=autostart)
            if r:
                out[name] = r
    return out


def jobs_view(db_path):
    """Journal listing for tools and UI panels."""
    jdir = _jdir(db_path)
    if not os.path.isdir(jdir):
        return []
    out = []
    for f in sorted(os.listdir(jdir), reverse=True):
        if not f.endswith(".json"):
            continue
        try:
            j = json.load(open(os.path.join(jdir, f)))
        except Exception:
            continue
        out.append({"jobid": j.get("jobid"), "state": j.get("state"),
                    "created": j.get("created"), "items": len(j.get("items", [])),
                    "cursor": j.get("cursor", 0),
                    "stats": j.get("stats", {}), "pending_embed": j.get("pending_embed", 0),
                    "items_detail": [{"kind": i["kind"], "target": i["target"][:80],
                                      "status": i["status"], "why": i.get("why", ""),
                                      "branch": i.get("branch", ""), "n": i.get("n", 0)}
                                     for i in j.get("items", [])][:40]})
    return out


if __name__ == "__main__":
    print(json.dumps(reconcile_all(kbcore.DBS, autostart=False), indent=2))