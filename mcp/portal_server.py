#!/usr/bin/env python3
"""portal/server.py — GREY RESEARCHER web portal (owner directive 2026-10-22).

Google-style search box -> background research run -> live SSE progress bar
-> results page (professional summaries from the optional audit, else the
deterministic brief). Deploys on the owner's server; on the desktop it binds
127.0.0.1:8791 only.

Endpoints:
    GET  /                      search page
    POST /api/research          {"query": "...", "max_pages": n} -> run_id
    GET  /api/progress/<id>     SSE: staged events (search_done/scraped/
                                judged/audit/guide/done/error)
    GET  /api/run/<id>          full result JSON once the run finishes
    GET  /assets/...            static assets (grey kit css/js)

Runs are in-process and nothing persists between them; the model audit is
the same never-resident lane. NO resident LLM anywhere.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

REPO = Path(__file__).resolve().parent
_PORTAL_DIR = REPO / "portal"
PORT = int(os.environ.get("GREYSEARCH_PORTAL_PORT") or 8791)
HOST = os.environ.get("GREYSEARCH_PORTAL_HOST") or "127.0.0.1"

_REFINE_RETRY_MAX = 1
_REFINE_RETRYABLE = ("unparsable/insufficient", "insufficient:true")
_REFINE_RETRY_PAUSE_S = 5.0

app = Flask("grey-researcher-portal", static_folder=None)

_RUNS: dict = {}
_RUNS_LOCK = threading.Lock()
_LAST_RUN_ID = ""
_REG_DIR = REPO / "runs" / "portal"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _registry_write(run_id: str, run: dict) -> None:
    """Durable run registry (runs/portal/<id>.json): the run->guide mapping
    survives portal restarts; latest/run/curation resolve from disk then.
    Every row here was submitted through this portal, so each carries
    origin: "webui" — or "qa" when the submission asks for the acceptance-
    gate marking — which the run ledger's origin filter keys on."""
    try:
        _REG_DIR.mkdir(parents=True, exist_ok=True)
        result = run.get("result") or {}
        guide = ((result.get("master_guide") or {}) or {}).get("path")
        meta = {"run_id": run_id, "query": run.get("query") or "",
                "status": run.get("status"), "guide_path": guide,
                "origin": run.get("origin") or "webui",
                "written": time.time()}
        if guide:
            (_REG_DIR / (run_id + ".json")).write_text(json.dumps(meta))
    except Exception:
        pass


def _registry_read(run_id: str) -> dict:
    try:
        if re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
            return json.loads((_REG_DIR / (str(run_id) + ".json")).read_text())
    except Exception:
        pass
    return {}

def _emit(run_id: str, stage: str, data: dict | None = None) -> None:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return
        run["events"].append({"stage": stage, "data": data or {},
                              "t": round(time.time(), 2)})
        run["queue"].put({"stage": stage, "data": data or {}})
    _events_persist(run_id, stage, data or {})


# ---- the run event journal (runs/events/<run_id>.jsonl) -------------------
# One JSON object per line, mirroring the visualcompanion events contract:
# server stage events and user interaction events share one file so a
# reload can replay uncommitted picks and a restart keeps the run's story.
# Appends are a single joined write under a lock and never load-bearing —
# a journal failure must not touch the UI.

_EVENTS_DIR = REPO / "runs" / "events"
_EVENTS_LOCK = threading.Lock()
_LINE_CAP = int(os.environ.get("GREYSEARCH_EVENTS_LINE_CAP") or 4096)
_MAX_EVENTS_BYTES = int(
    os.environ.get("GREYSEARCH_EVENTS_MAX_BYTES") or 2_000_000)


def _events_file(run_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
        return None
    return Path(_EVENTS_DIR) / (str(run_id) + ".jsonl")


def _valid_user_event(o: dict):
    """Whitelist rebuild of one client-supplied event: only the known
    types with their known shape survive, ts is always server-stamped (a
    client-provided ts is dropped), and unknown/stray keys are refused.
    Returns the clean event, or None when the event is refused."""
    t = o.get("type")
    on = o.get("on")
    if not isinstance(on, bool):
        return None
    if t == "para":
        pid, u = str(o.get("pid") or ""), str(o.get("u") or "")
        if not re.fullmatch(r"pg\d+#p\d+", pid) or len(u) > 500:
            return None
        return {"type": "para", "on": on, "pid": pid, "u": u}
    if t == "para-all":
        pid, u = str(o.get("pid") or ""), str(o.get("u") or "")
        if not re.fullmatch(r"pg\d+", pid) or len(u) > 500:
            return None
        return {"type": "para-all", "on": on, "pid": pid, "u": u}
    if t == "kw":
        v = str(o.get("value") or "")
        if not v or len(v) > 80:
            return None
        return {"type": "kw", "on": on, "value": v}
    if t == "img":
        k = str(o.get("key") or "")
        if not re.fullmatch(r"[fu]:.{1,518}", k):
            return None
        return {"type": "img", "on": on, "key": k}
    if t == "uurl":
        u = str(o.get("u") or "")
        if not re.match(r"^https?://", u, re.I) or len(u) > 500:
            return None
        return {"type": "uurl", "on": on, "u": u}
    return None


def _strip_stage_payload(stage: str, data: dict) -> dict:
    """The journal carries the run's story, not its bulk: a scraped event's
    live preview record compresses to ids plus counts — the full text lives
    in the run's curation sidecar."""
    d = dict(data or {})
    if isinstance(d.get("page"), dict):
        p = d["page"]
        paras = p.get("paragraphs") or []
        d["page"] = {
            "id": str(p.get("id") or "")[:40],
            "url": str(p.get("url") or "")[:300],
            "title": str(p.get("title") or "")[:120],
            "decision": str(p.get("decision") or ""),
            "paragraphs_total": (p.get("paragraphs_total") if
                                 p.get("paragraphs_total") else len(paras)),
            "paragraphs_truncated": bool(p.get("paragraphs_truncated")),
            "chars": p.get("chars") or 0,
        }
    return d


def _events_write(run_id: str, events: list, validate: bool = False):
    """Append events to the run's journal. One joined write under the lock
    so concurrent emitters never interleave lines. Returns {"kept",
    "refused"} — refused is the count of events that failed validation or
    the per-line cap. A run id that fails the shape check returns None; an
    unwritten run_id does NOT refuse writes (the file is created on
    demand)."""
    f = _events_file(run_id)
    if not f:
        return None
    lines, refused = [], 0
    for o in (events or [])[:128]:
        if not isinstance(o, dict):
            refused += 1
            continue
        ev = dict(o)
        ev.pop("ts", None)
        if validate:
            ev2 = _valid_user_event(ev)
            if ev2 is None:
                refused += 1
                continue
            ev = ev2
        ev["ts"] = round(time.time(), 2)
        try:
            line = json.dumps(ev, ensure_ascii=False, default=str,
                              separators=(",", ":"))
        except Exception:
            refused += 1
            continue
        if len(line.encode("utf-8", "replace")) > _LINE_CAP:
            refused += 1
            continue
        lines.append(line)
    if not lines:
        return {"kept": 0, "refused": refused}
    blob = "\n".join(lines) + "\n"
    with _EVENTS_LOCK:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            size = f.stat().st_size if f.is_file() else 0
            if size >= _MAX_EVENTS_BYTES:
                return {"kept": 0, "refused": refused + len(lines)}
            if size + len(blob.encode("utf-8", "replace")) > _MAX_EVENTS_BYTES:
                tail = f.read_bytes()[-512:] if f.is_file() else b""
                if b'"type":"capped"' in tail:
                    return {"kept": 0, "refused": refused + len(lines)}
                refused += len(lines)
                lines = []
                blob = (json.dumps(
                            {"type": "capped",
                             "note": "event journal hit its ceiling for "
                                     "this run",
                             "ts": round(time.time(), 2)},
                            ensure_ascii=False,
                            separators=(",", ":")) + "\n")
            with f.open("a", encoding="utf-8") as fh:
                fh.write(blob)
        except Exception:
            return {"kept": 0, "refused": refused + len(lines)}
    return {"kept": len(lines), "refused": refused}


def _events_read(run_id: str):
    """The journal for one run: malformed lines are skipped, never fatal
    (the visualcompanion read_events rule). Returns None for a run id that
    fails the shape check."""
    f = _events_file(run_id)
    if not f:
        return None
    try:
        raw = f.read_text(encoding="utf-8", errors="replace")
        size = f.stat().st_size
    except OSError:
        raw, size = "", 0
    events = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return {"exists": bool(events), "run_id": str(run_id), "events": events,
            "capped": size >= _MAX_EVENTS_BYTES}


def _events_persist(run_id: str, stage: str, data: dict | None = None) -> None:
    try:
        _events_write(run_id, [{"type": "stage", "stage": str(stage)[:64],
                                **_strip_stage_payload(stage, data)}])
    except Exception:
        pass

LENGTH_PAGES = {"brief": 3, "standard": 4, "deep": 6, "report": 8}

def _runner(run_id: str, query: str, length: str, max_pages: int,
            engines=None) -> None:
    def _watchdog(run_id=run_id):
        time.sleep(900)
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
            if run and run["status"] == "running":
                run["status"] = "error"
        _emit(run_id, "error",
              {"error": "This run took too long and was stopped. Try again — "
                        "or a narrower topic; the search lanes pace themselves."})
        _emit(run_id, "__end__", {})

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        _emit(run_id, "start", {"query": query})
        try:
            import browser_session as _bs
            if not _bs.cdp_alive():
                _bs.ensure_daemon(wait_s=45)
        except Exception:
            pass
        import research_integration as ri
        import greysearch_mcp as gm
        with _RUNS_LOCK:
            _RUNS[run_id]["length"] = length
        pages = max_pages or LENGTH_PAGES.get(length, 4)
        _budget = {"brief": 240.0, "standard": 300.0, "deep": 420.0,
                   "report": 540.0}.get(length, 300.0)
        result = ri.research_deep(
            query, max_pages=pages, max_total_seconds=_budget,
            progress_cb=lambda st, d: _emit(run_id, st, d),
            engines=engines)
        _emit(run_id, "audit", {})
        write_path = Path(gm._resolve_guide_path(None, query, slug_tag=length))
        _img_sel: list = []
        try:
            from searxng_integrated import _split_selection as _ss
            _img_sel = (_ss(engines or []) or {}).get("images", [])
        except Exception:
            _img_sel = []
        _emit(run_id, "images", {"count": "?"})
        try:
            import photos
            accepted = result.get("pages_fetched") or []
            cands = photos.guide_images(
                query, accepted, per_page=1,
                dest_dir=write_path.parent / (write_path.stem + "_imgcand"),
                engines=_img_sel)
            slim = [{"file": c.get("file"), "url": c.get("url"),
                     "title": c.get("title", "")[:90],
                     "creator": c.get("creator", "")[:60],
                     "license": c.get("license", ""), "provenance":
                     c.get("provenance")} for c in cands]
            result["image_candidates"] = slim
            _emit(run_id, "images", {"count": len(slim)})
        except Exception as _pe:
            result["image_candidates"] = []
            _emit(run_id, "images", {"count": 0, "note": str(_pe)[:120]})
        _rr_img = result.get("run_report")
        if isinstance(_rr_img, dict):
            _rr_img["image_candidates"] = list(
                result.get("image_candidates") or [])
        result = gm._attach_guide(result, query, write_path)
        with _RUNS_LOCK:
            _RUNS[run_id]["result"] = result
            _RUNS[run_id]["status"] = "done"
        _registry_write(run_id, _RUNS.get(run_id) or {})
        _emit(run_id, "guide", {"path": str(write_path)})
    except Exception as e:
        _emit(run_id, "error", {"error": str(e)[:300]})
        with _RUNS_LOCK:
            _RUNS[run_id]["status"] = "error"
    finally:
        _emit(run_id, "__end__", {})

@app.get("/")
def index():
    return send_from_directory(_PORTAL_DIR, "index.html")

@app.post("/api/research")
def api_research():
    body = request.get_json(force=True, silent=True) or {}
    q = (body.get("query") or "").strip()
    if not q:
        return jsonify({"error": "query required"}), 400
    length = (body.get("length") or "standard").strip().lower()
    if length not in ("brief", "standard", "deep", "report"):
        length = "standard"
    max_pages = int(body.get("max_pages")
                    or LENGTH_PAGES.get(length, 4))
    engines_raw = body.get("engines")
    if engines_raw and not isinstance(engines_raw, list):
        engines_raw = [engines_raw]
    engines = sorted({str(x).strip().lower()
                      for x in (engines_raw or []) if str(x).strip()})[:8]
    unknown_dropped = 0
    try:
        from searxng_integrated import engine_catalog
        _known = {str(e.get("name") or "").strip().lower()
                  for e in engine_catalog()}
        if _known:
            unknown_dropped = len([e for e in engines if e not in _known])
            engines = [e for e in engines if e in _known][:8]
    except Exception:
        pass
    run_id = uuid.uuid4().hex[:12]
    body_origin = (body.get("origin") or "").strip().lower()
    origin = "qa" if body_origin == "qa" else "webui"
    with _RUNS_LOCK:
        _RUNS[run_id] = {"status": "running", "events": [],
                         "queue": queue.Queue(), "result": None,
                         "query": q,
                         "length": length,
                         "engines": engines,
                         "origin": origin}
    threading.Thread(target=_runner,
                     args=(run_id, q, length, max_pages,
                           engines),
                     daemon=True).start()
    global _LAST_RUN_ID
    with _RUNS_LOCK:
        _LAST_RUN_ID = run_id
    return jsonify({"run_id": run_id, "engines": engines,
                    "unknown_engines_dropped": unknown_dropped})

@app.get("/api/progress/<run_id>")
def api_progress(run_id: str):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run:
        return jsonify({"error": "unknown run"}), 404

    def gen():
        import json as _j
        for ev in list(run["events"]):
            yield f"data: {_j.dumps(ev)}\n\n"
            if ev["stage"] == "__end__":
                return
        while True:
            try:
                ev = run["queue"].get(timeout=120)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield f"data: {_j.dumps(ev)}\n\n"
            if ev["stage"] == "__end__":
                return

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})

def _build_title(result: dict) -> str:
    """Page title from the research question."""
    q = result.get("question") or ""
    return (q[:90] or "Research Guide")

_STALE_AUTOBUILD_WARNING_PREFIXES = (
    "site guardrails FAILED",
    "site builder rc=",
    "site build failed (isolated)",
)

def _supersede_stale_site_state(run: dict, build: dict) -> None:
    """Point the run record's result["site"] at the LAST build and drop the
    superseded auto-build's stale site warnings. Existing keys (path, pages,
    built, guardrails) keep their meaning; the consumer-visible change is
    record freshness, never shape."""
    result = run.get("result")
    if not isinstance(result, dict):
        return
    site = build.get("site")
    pages = 0
    if site:
        try:
            pages = len(list(Path(site).glob("*.html")))
        except Exception:
            pages = 0
    result["site"] = {"path": site, "pages": pages,
                      "built": bool(build.get("ok")),
                      "guardrails": build.get("guardrails") or {},
                      "theme": build.get("theme"),
                      "built_via": "confirm-grid"}
    result["warnings"] = [
        w for w in (result.get("warnings") or [])
        if not str(w).startswith(_STALE_AUTOBUILD_WARNING_PREFIXES)]

def _clip_cap(x: str, n: int = 90) -> str:
    return (str(x) or "")[:n]

def _table_md(t: dict) -> str:
    try:
        cols = t.get("columns") or []
        rows = t.get("rows") or []
        if not cols or len(rows) < 2:
            return ""
        out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
        for r in rows:
            cells = r[:len(cols)] + [""] * (len(cols) - len(r))
            out.append("| " + " | ".join(str(c) for c in cells) + " |")
        return "\n".join(out)
    except Exception:
        return ""

def _research_appendix(result: dict) -> str:
    """The FULL research text (owner: a research report, not an essay) —
    every kept source, its distilled prose, sources listed."""
    pages = [p for p in (result.get("pages_fetched") or [])
             if p and (p.get("text") or (p.get("clean") or {}).get("body_text"))]
    if not pages:
        return ""
    out = ["", "## Research detail (from the kept sources)", ""]
    for i, p in enumerate(pages[:8]):
        clean = p.get("clean") or {}
        title = clean.get("title") or p.get("title") or p.get("url")
        url = p.get("url") or ""
        body = clean.get("body_text") or p.get("text") or ""
        paras = [x.strip() for x in re.split(r"\n\s*\n", body)
                 if len(x.strip()) > 100][:5]
        out.append(f"**{i + 1}. {title}**  ")
        if url:
            out.append(f"<{url}>")
        out.append("")
        out += [x + "\n" for x in paras]
    return "\n".join(out)

def _compose_refined_guide(result: dict, refined_text: str,
                           refine_prompt: str) -> str:
    """Final guide body = brief + refined (model-written) sections +
    research limitations. Everything stays source-grounded; the refined
    text is the model's parse of gathered data, not invention."""
    head = f"**Focus:** {refine_prompt[:200]}\n"
    brief = (result.get("master_guide") or {}).get("preview", "")
    sources = result.get("sources") or []
    sources = list(dict.fromkeys(sources))
    tail = "\n\n## Sources\n\n" + "\n".join(f"- <{u}>" for u in sources)
    return head + "\n" + refined_text + "\n" + \
        (_research_appendix(result) or "") + tail

def _run_tables_markdown(result: dict) -> str:
    """Pull REAL tables found on accepted pages (site_render chartifies
    these into themed teaching charts automatically)."""
    parts = []
    n = 0
    for p in (result.get("pages_fetched") or []):
        tables = (p.get("tables") or [])
        for t in tables[:1]:
            headers = t.get("headers") or []
            rows = t.get("rows") or []
            if len(headers) >= 2 and 2 <= len(rows) <= 12:
                parts.append("| " + " | ".join(str(h)[:40] for h in headers)
                             + " |")
                parts.append("|" + "---|" * len(headers))
                for r in rows:
                    parts.append("| " + " | ".join(str(c)[:40] for c in r[:len(headers)]) + " |")
                parts.append("")
                n += 1
        if n >= 3:
            break
    return "\n".join(parts).strip()

def _insert_chosen_images(md_text: str, chosen: list, gpath: Path) -> str:
    """Insert the CHOSEN confirm-grid candidates into the guide markdown.

    Pass-4 defect (observed live 2026-10-23): the insert used the candidate's
    ORIGINAL REMOTE url, so the site build re-downloaded each pick, and that
    second download silently failed for one — the user-approved image vanished
    from the export while its "*Image: ..." credit line shipped alone. Now
    each candidate's ALREADY-DOWNLOADED local copy (its "file", in the run's
    _imgcand dir) is copied beside the master guide and referenced by that
    relative path, which site_render.download_images resolves as a local
    source — a chosen pick can never depend on a second remote download.
    Candidates without a local copy fall back to the remote url (old
    behaviour, best-effort). Creator/license meta is kept verbatim so the
    credit stays accurate."""
    import photos as _ph
    used = set()
    for i, c in enumerate((chosen or [])[:3]):
        key = c.get("url") or c.get("file") or str(i)
        if key in used:
            continue
        used.add(key)
        meta = {"url": c.get("url") or "", "title": c.get("title") or "",
                "creator": c.get("creator") or "unknown",
                "license": c.get("license") or ""}
        lf = c.get("file")
        if lf:
            src = Path(lf)
            if src.is_file():
                dest = gpath.parent / f"chosen-{i}-{src.name}"
                if not dest.is_file() \
                        or dest.read_bytes() != src.read_bytes():
                    dest.write_bytes(src.read_bytes())
                meta["url"] = dest.name
        if meta["url"]:
            md_text = _ph.insert_photo(md_text, meta, meta["title"])
    return md_text

@app.get("/api/latest")
def api_latest():
    """Reattach after a page reload: the newest run's id + status (the SSE
    endpoint replays its events, so the bar resumes). A portal restart
    clears the in-memory map — fall back to the newest run in the disk
    registry so finished research stays reachable. Lane wave 2026-11-03:
    acceptance-gate runs (origin "qa") never attach the plain page — they
    are the research tooling's own runs, not the reader's. A page that
    loads with ?origin=all (the gates, in qamode) gets every run."""
    want_all = ((request.args.get("origin") or "").strip().lower() == "all")
    with _RUNS_LOCK:
        run = {}
        latest_id = None
        for rid, r in _RUNS.items():
            if not want_all and r.get("origin") == "qa":
                continue
            run = r
            latest_id = rid
    if run:
        return jsonify({"run_id": latest_id, "status": run.get("status"),
                        "origin": run.get("origin") or "webui",
                        "exists": bool(run)})
    best = {}
    if _REG_DIR.is_dir():
        for p in _REG_DIR.glob("*.json"):
            try:
                m = json.loads(p.read_text())
            except Exception:
                continue
            if m.get("status") != "done":
                continue
            org = str(m.get("origin") or "").strip() or "webui"
            if org == "qa" and not want_all:
                continue
            if m.get("written", 0) > best.get("written", 0):
                best = m
    if best:
        return jsonify({"run_id": best.get("run_id"), "status": "done",
                        "origin": str(best.get("origin") or "webui"),
                        "exists": True})
    return jsonify({"run_id": _LAST_RUN_ID, "status": None,
                    "exists": bool(run)})

@app.post("/api/build/<run_id>")
def api_build(run_id: str):
    """Confirm step: chosen images + theme -> final guardrailed site."""
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run or run["status"] != "done":
        return jsonify({"error": "run not finished"}), 400
    body = request.get_json(force=True, silent=True) or {}
    theme = (body.get("theme") or "master").strip()
    chosen = [c for c in (body.get("images") or []) if c]

    result = run["result"] or {}
    gpath = Path((result.get("master_guide") or {}).get("path") or "")
    if not gpath.is_file():
        return jsonify({"error": "guide not found"}), 404

    refine = run.get("latest_refine") or {}
    if refine.get("text"):
        md_text = _compose_refined_guide(
            result, refine["text"], refine.get("prompt") or "")
    else:
        md_text = gpath.read_text()

    try:
        md_text = _insert_chosen_images(md_text, chosen, gpath)

    except Exception as _ie:
        md_text += f"\n<!-- image insertion note: {str(_ie)[:120]} -->\n"

    try:
        tables_md = _run_tables_markdown(result)
        if tables_md:
            md_text += "\n\n" + tables_md
    except Exception:
        pass

    tmp_md = gpath.with_name(gpath.stem + f"-{theme}.md")
    run["build_request"] = {"theme": theme, "n_chosen": len(chosen),
                            "chosen_urls": [c.get("url", "")[:80] for c in chosen],
                            "refined": bool(refine.get("text"))}
    tmp_md.write_text(md_text)
    import subprocess, sys as _sys
    site_out = tmp_md.with_name(tmp_md.stem + "_site")
    _boot = ("import sys; sys.path.insert(0, %r); "
             "import greysearch_site_builder as m; "
             "sys.exit(m.render())" % str(REPO))
    pr = subprocess.run(
        [_sys.executable, "-c", _boot,
         str(tmp_md), "-o", str(site_out), "--theme", theme,
         "--title", _build_title(result),
         "--max-images", "40"],
        capture_output=True, text=True, timeout=180,
        cwd=str(REPO))
    ok = (site_out / "index.html").is_file()
    zip_path = None
    pdf_path = None
    if ok:
        import shutil
        shutil.make_archive(str(site_out), "zip", site_out)
        zip_path = str(site_out) + ".zip"
        pdf_note = ""
        try:
            import pdf_export
            pdf_path = pdf_export.render_pdf(
                str(site_out / "index.html"),
                str(site_out.with_suffix(".pdf")))
            if not pdf_path:
                pdf_note = "render returned None (see portal log)"
        except Exception as _pe:
            pdf_note = f"pdf error: {str(_pe)[:160]}"
    guard = {}
    try:
        guard = json.loads((site_out / "guardrails.json").read_text())
    except Exception:
        pass
    run["build"] = {"site": str(site_out) if ok else None, "ok": ok,
                    "zip": zip_path, "pdf": pdf_path, "pdf_note": pdf_note, "theme": theme,
                    "guardrails": guard,
                    "tail": (pr.stderr or "")[-400:]}
    _supersede_stale_site_state(run, run["build"])
    _emit(run_id, "built", {"site": str(site_out) if ok else None,
                            "zip": zip_path, "pdf": pdf_path, "ok": ok})
    return jsonify(run["build"])

@app.post("/api/refine/<run_id>")
def api_refine(run_id: str):
    """Narrow-scope stage: the user's prompt + the run's gathered data ->
    output text. Repeatable; every call returns fresh text for live view.
    Model down -> honest fallback message, research text stays shown."""
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run or run["status"] != "done":
        return jsonify({"error": "run not finished"}), 400
    body = request.get_json(force=True, silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    result = run["result"] or {}
    question = result.get("question") or ""
    import dossier as _d
    text = _d.build_dossier(result, question + " " + prompt,
                            budget_chars=9000)
    out = {"ok": False, "text": ""}
    try:
        import llm_audit as _la
        _R = None
        for _attempt in range(_REFINE_RETRY_MAX + 1):
            _R = None
            if _la.audit_allowed() and _la.endpoint_ok():
                _R = _la.refine(
                        prompt, text,
                        (run.get("length") or "standard"))
                if not _R:
                    _R = _la.audit(prompt, text)
            if _R and (_R.get("sections") or _R.get("brief") or _R.get("facts")):
                break
            _why = (_la.last_reason() if _la else "") or ""
            if (_attempt < _REFINE_RETRY_MAX
                    and any(k in _why for k in _REFINE_RETRYABLE)):
                time.sleep(_REFINE_RETRY_PAUSE_S)
                continue
            break
        if _R and (_R.get("sections") or _R.get("brief") or _R.get("facts")):
            parts = []
            if _R.get("brief"):
                parts.append(f"_{_R['brief']}_")
            for sct in (_R.get("sections") or []):
                h = (sct.get("heading") or "").strip() if isinstance(sct, dict) else ""
                body = (sct.get("text") or "").strip() if isinstance(sct, dict) else ""
                if h and body:
                    parts.append(f"## {h}\n\n{body}")
                if isinstance(sct, dict) and sct.get("table"):
                    t = sct["table"]
                    parts.append(_table_md(t))
            for t in (_R.get("tables") or []):
                parts.append(f"**{_clip_cap(t.get('caption') or 'Data')}**" if t.get("caption") else "")
                parts.append(_table_md(t))
            if _R.get("facts"):
                parts.append("**Key facts**")
                parts += [f"- {f}" for f in _R["facts"]]
            txt = "\n\n".join(parts).strip()
            if txt:
                suggestions = []
                try:
                    import photos as _ph
                    paras = [x for x in txt.split("\n") if len(x) > 120
                             and not x.startswith(("#", "-", "*", "_"))]
                    for i, para in enumerate(paras[:6]):
                        q2 = _ph.keywords(para, 3)
                        cpool = ([_ph.find_photo(q2)] if _ph.find_photo(q2) else []) \
                            + _ph.searx_image_hits(q2, 3)
                        cpool = [c for c in cpool if c.get("url")
                                 and _ph._topical_hit(c, f"{question} {para}")]
                        if cpool:
                            dl = _ph.download_with_provenance(
                                cpool[0],
                                Path((result.get("master_guide") or {})
                                     .get("path", "guides/x.md")).parent
                                / (Path((result.get("master_guide") or {})
                                        .get("path", "guides/x.md")).stem
                                   + "_imgcand"),
                                f"para{i}")
                            if dl:
                                suggestions.append({
                                    "file": dl.get("file"),
                                    "url": dl.get("url"),
                                    "title": (dl.get("title") or "")[:90],
                                    "creator": (dl.get("creator") or "")[:60],
                                    "license": dl.get("license") or "",
                                    "provenance": dl.get("provenance"),
                                    "para": i,
                                    "para_head": para[:50]})
                        time.sleep(0.5)
                except Exception:
                    pass
                out = {"ok": True, "text": txt, "model": _R.get("model"),
                       "image_suggestions": suggestions}
                run.setdefault("refine", []).append({"prompt": prompt, "text": txt})
                run["latest_refine"] = {"prompt": prompt, "text": txt}
                run["image_suggestions"] = suggestions
            else:
                out = {"ok": False, "text": "The model returned an empty "
                       "write-up for that instruction. Try rewording it."}
        else:
            _why = (_la.last_reason() if _la else "") or ""
            if "dossier empty" in _why:
                out = {"ok": False,
                       "text": "This run gathered no usable sources, so "
                               "there is nothing to narrow or rewrite. "
                               "Search again with a fuller query.",
                       "reason": _why}
            else:
                out = {"ok": False,
                       "text": "The model is not reachable right now. The "
                               "research results below still stand, and "
                               "you can export them as they are.",
                       "reason": _why}
    except Exception as e:
        out = {"ok": False, "text": "", "error": str(e)[:200]}
    _emit(run_id, "refine", {"ok": bool(out.get("ok"))})
    return jsonify(out)

@app.get("/api/run/<run_id>")
def api_run(run_id: str):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if run:
        return jsonify({"status": run["status"], "result": run["result"],
                        "build": run.get("build"),
                        "refine": (run.get("latest_refine") or {})})
    """Restart-proof hydrate: a finished run whose in-memory entry is gone
    re-serves from the disk registry + the run report on disk. The live
    text view (pages_fetched) is session-only by design; the curated
    research lives in the curation sidecar, which this path keeps serving."""
    reg = _registry_read(run_id)
    if reg.get("status") != "done":
        return jsonify({"error": "unknown run"}), 404
    gpath = Path(reg.get("guide_path") or "")
    if not gpath.is_file():
        return jsonify({"error": "unknown run"}), 404
    report = {}
    try:
        report = json.loads(gpath.with_suffix(
            gpath.suffix + ".run-report.json").read_text())
    except Exception:
        report = {}
    try:
        preview = gpath.read_text()[:4000]
    except Exception:
        preview = ""
    hydrated = {
        "master_guide": {"path": str(gpath), "preview": preview},
        "sources": [s.get("url") if isinstance(s, dict) else str(s)
                    for s in (report.get("accepted_sources") or [])][:12],
        "image_candidates": report.get("image_candidates") or [],
        "pages_fetched": [],
    }
    return jsonify({"status": "done", "result": hydrated,
                    "build": None, "refine": {}})

_FETCH_URLS_CAP = 8
_FETCH_URLS_WALL_S = 180.0
_WAVE_LOCKS: dict = {}
_WAVE_LOCKS_GUARD = threading.Lock()

@app.post("/api/fetch-urls/<run_id>")
def api_fetch_urls(run_id: str):
    """Second wave (owner decision 2026-11-03, "save everything before the
    output steps"): any TURNED-AWAY candidate from a finished run can be
    opened on the run's own slot browser and appended to the run's curation
    record. Body {"urls": [...]}, at most 8 per call, http(s) only; skips
    urls the record already holds; 180s honest wall-clock; every miss is
    reported with its reason. Only the curation sidecar changes — the run
    report stays the historical record of what the run itself did; saved
    sets compose selections against the sidecar at compose time, so a ticked
    new page joins any set on the next save. The 4 MB record guard here is
    a REJECTION (412), not a silent shrink — the owner's just-requested
    pages are never the first thing dropped; the message names the limit."""
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        guide_path = (((run.get("result") or {})
                       .get("master_guide") or {}).get("path")
                      if run else None)
        run_busy = bool(run and run.get("status") == "running")
    if not guide_path:
        reg = _registry_read(run_id)
        if reg.get("status") == "done":
            guide_path = reg.get("guide_path")
    guide_path = Path(guide_path) if guide_path else None
    if not (guide_path and guide_path.is_file()):
        return jsonify({"error": "unknown run"}), 404
    if run_busy:
        return jsonify({"error": "this run is still in progress; wait for "
                                 "it to finish before fetching more pages"}
                       ), 409
    cpath = guide_path.with_suffix(guide_path.suffix + ".curation.json")
    if not cpath.is_file():
        return jsonify({"error": "no curation record for this run yet"}), 404
    body = request.get_json(force=True, silent=True) or {}
    urls: list = []
    for _u in (body.get("urls") or []):
        u = str(_u or "").strip()
        if u.lower().startswith(("http://", "https://")) and u not in urls:
            urls.append(u)
    if not urls:
        return jsonify({"error": "no http(s) urls in the request"}), 400
    if len(urls) > _FETCH_URLS_CAP:
        return jsonify({"error": f"fetch at most "
                                 f"{_FETCH_URLS_CAP} urls per call"}), 400
    with _WAVE_LOCKS_GUARD:
        lock = _WAVE_LOCKS.setdefault(run_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return jsonify({"error": "a fetch is already running for this run"}), 409
    try:
        try:
            payload = json.loads(cpath.read_text())
        except Exception:
            return jsonify({"error": "curation record unreadable"}), 500
        pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
        have = set()
        for _p in pages:
            if isinstance(_p, dict):
                have.add(_p.get("url") or "")
                have.add(_p.get("final_url") or "")
        have.discard("")
        todo = [u for u in urls if u not in have]
        if todo:
            try:
                import browser_session as _bs
                if not _bs.cdp_alive():
                    _bs.ensure_daemon(wait_s=45)
            except Exception:
                pass
        import research_integration as _ri
        import greysearch_mcp as _gm
        import page_clean as _pc
        fetched: list = []
        failed: list = []
        if todo:
            bridge = _ri.get_bridge()
            deadline = time.time() + _FETCH_URLS_WALL_S
            next_id = len(pages)
            for u in todo:
                if time.time() > deadline:
                    failed.append({"url": u, "error": "fetch budget reached"})
                    continue
                try:
                    sr = bridge.research_scrape(u)
                    if not sr.get("ok"):
                        failed.append({"url": u,
                                       "error": str(sr.get("error")
                                                    or "page could not be "
                                                      "fetched")[:180]})
                        continue
                    sr = dict(sr)
                    sr.setdefault("url", u)
                    cleaned = _pc.clean_page(sr)
                    if _pc.is_thin(cleaned):
                        failed.append({"url": u,
                                       "error": f"page is nearly empty "
                                                f"({cleaned.get('main_chars', 0)} chars)"})
                        continue
                    sr["clean"] = cleaned
                    rec = _gm._curation_page(
                        {**sr, "tier": "second-wave",
                         "relevance": {"decision": "manual",
                                       "reason": "fetched on your command "
                                                 "for this record"}},
                        f"pg{next_id}")
                    next_id += 1
                    pages.append(rec)
                    fetched.append(rec.get("url") or u)
                except Exception as fe:
                    failed.append({"url": u, "error": str(fe)[:180]})
        if not fetched:
            return jsonify({"ok": True, "fetched": 0, "failed": failed,
                            "counts": _gm._curation_counts(
                                pages, payload.get("unscraped_candidates")),
                            "note": "nothing new to fetch" if not todo
                            else "the selected pages could not be fetched"})
        payload["pages"] = pages
        fetched_set = set(fetched)
        payload["unscraped_candidates"] = [
            c for c in (payload.get("unscraped_candidates") or [])
            if isinstance(c, dict) and c.get("url") not in fetched_set]
        payload["second_wave"] = {
            "fetched": len(fetched),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if len(json.dumps(payload, default=str).encode()) > _gm._MAX_RECORD_BYTES:
            return jsonify({"error": "this curation record is full (4 MB "
                                     "record limit) — export it as-is before "
                                     "fetching more"}), 412
        payload["counts"] = _gm._curation_counts(
            payload["pages"], payload["unscraped_candidates"])
        tmp = cpath.with_name(cpath.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, default=str),
                       encoding="utf-8")
        os.replace(tmp, cpath)
        return jsonify({"ok": True, "fetched": len(fetched),
                        "failed": failed, "counts": payload["counts"]})
    finally:
        lock.release()

FAVICON = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4n"
           "GNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")

@app.get("/favicon.ico")
def favicon():
    import base64
    return Response(base64.b64decode(FAVICON), mimetype="image/png")

@app.get("/kit/theme.css")
def kit_css():
    """Font-stripped grey kit css — same treatment built sites receive."""
    import re as _re
    src = (REPO / "assets" / "kit-source" / "theme.css").read_text()
    return Response(_re.sub(r"@font-face\s*\{[^{}]*\}\s*", "", src),
                    mimetype="text/css")

@app.get("/imgcand/<path:fname>")
def imgcand(fname: str):
    """Serve an image candidate file from a run's _imgcand dir."""
    return send_from_directory(REPO / "guides", fname)

@app.get("/site/<path:fname>")
def site_file(fname: str):
    """Serve a built site (downloadable) — read-only, guides tree."""
    return send_from_directory(REPO / "guides", fname)

@app.get("/assets/<path:fname>")
def assets(fname: str):
    return send_from_directory(REPO / "assets", fname)

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)

CLEANUP_MAX_AGE_S = float(os.environ.get("GREYSEARCH_SITE_TTL_S")
                          or 900.0)

_THEMES = ("master", "neutral", "polaroid", "cockpit", "cockpit-paper",
           "console", "compact", "casebook", "agent-paper", "agent-pulse",
           "agent-history", "terminal", "swiss", "bespoke", "torque",
           "umami", "aurora")

def _disposable(path) -> bool:
    """Only build byproducts are ever disposable, and only by exact name
    shape. A master guide .md is never disposable here. 2026-11-03: a run's
    _imgcand dir is NOT disposable either — its image candidates are the
    publish grid's data and the confirm step's local copies (the owner's
    "save everything before output" rule: a grid that 404s after the 900s
    sweep is a broken record, so picks stay durable)."""
    name = os.path.basename(str(path))
    if name.endswith(".md") or name.endswith(".md.run-report.json"):
        for th in _THEMES:
            if name.endswith(f"-{th}.md"):
                return True
        return False
    return "_site" in name

def _janitor_sweep() -> list:
    gone = []
    now = time.time()
    guides_dir = REPO / "guides"
    if not guides_dir.is_dir():
        return gone
    for path in list(guides_dir.glob("**/*")):
        try:
            if not _disposable(path):
                continue
            if now - path.stat().st_mtime <= CLEANUP_MAX_AGE_S:
                continue
            if path.is_dir():
                import shutil as _sh
                _sh.rmtree(path, ignore_errors=True)
            else:
                path.unlink()
            gone.append(path.name)
        except Exception:
            continue
    return gone

def _janitor():
    while True:
        try:
            _janitor_sweep()
        except Exception:
            pass
        time.sleep(60)

_start_janitor = threading.Thread(
    target=_janitor, daemon=True, name="gr-janitor").start()

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
