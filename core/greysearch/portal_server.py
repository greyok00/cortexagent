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


_ROW_LOCK = threading.Lock()
_ROW_MILESTONES = frozenset({
    "start", "search_done", "judged", "images", "guide", "built",
    "error", "__end__"})


def _row_write(run_id: str, run: dict) -> None:
    """Durable run lifecycle row (runs/portal/<id>.json): written at
    submission and on every status/milestone change, never only on
    success — a run that failed or was orphaned by a restart stays
    visible in /api/latest and /api/run instead of evaporating with
    _RUNS. Legacy keys keep their meaning (run_id, query, status,
    guide_path, origin, written; the run->guide mapping still survives
    portal restarts and every row still carries origin "webui"/"qa");
    the additive keys (stage, length, max_pages, engines, error,
    started_at, updated_at, epoch, resumed, resume, search,
    images_count, curation_path) are the lifecycle contract. Atomic
    write (tmp + os.replace) so a half row can never stand in for a
    finished one; a write failure prints to the portal log and the next
    milestone rewrites the row — the run itself never breaks."""
    try:
        _REG_DIR.mkdir(parents=True, exist_ok=True)
        result = run.get("result") or {}
        guide = ((result.get("master_guide") or {}) or {}).get("path")
        meta = {"run_id": run_id, "query": run.get("query") or "",
                "status": run.get("status"), "stage": run.get("stage") or "",
                "guide_path": guide,
                "curation_path": run.get("curation_path") or "",
                "origin": run.get("origin") or "webui",
                "length": run.get("length") or "",
                "max_pages": run.get("max_pages"),
                "engines": run.get("engines") or [],
                "error": run.get("error") or "",
                "started_at": run.get("started_at") or time.time(),
                "updated_at": time.time(),
                "epoch": int(run.get("epoch") or 1),
                "resumed": int(run.get("resumed") or 0),
                "resume": run.get("resume") or {"can": False, "reason": "",
                                                "from_stage": ""},
                "search": run.get("search") or {},
                "images_count": run.get("images_count"),
                "written": time.time()}
        path = _REG_DIR / (run_id + ".json")
        tmp = path.with_name(path.name + ".tmp")
        with _ROW_LOCK:
            tmp.write_text(json.dumps(meta, ensure_ascii=False))
            os.replace(tmp, path)
    except Exception as _rw:
        print("greysearch: run row write failed for %s: %s"
              % (run_id, str(_rw)[:160]), flush=True)


def _row_update(run_id: str, status: str | None = None,
                stage: str | None = None, error: str | None = None,
                **extra) -> None:
    """The lifecycle chokepoint: updates the in-memory run when present,
    then rewrites the durable row, so _RUNS and disk never disagree.
    Unknown kwargs land on the row verbatim (images_count, search,
    curation_path, resume...). A run missing from _RUNS changes nothing —
    its disk row already says whatever the sweep maintains."""
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run is None:
            return
        if status is not None:
            run["status"] = status
        if stage is not None:
            run["stage"] = stage
        if error is not None:
            run["error"] = error
        run.update(extra)
        snap = dict(run)
    _row_write(run_id, snap)


def _registry_read(run_id: str) -> dict:
    try:
        if re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
            return json.loads((_REG_DIR / (str(run_id) + ".json")).read_text())
    except Exception:
        pass
    return {}

def _emit(run_id: str, stage: str, data: dict | None = None) -> None:
    # The journal write comes FIRST and unconditionally: a run orphaned by
    # a restart keeps its stage story even after _RUNS lost it. The in-
    # memory append and SSE queue below only run while the live run exists.
    _events_persist(run_id, stage, data or {})
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run:
            run["events"].append({"stage": stage, "data": data or {},
                                  "t": round(time.time(), 2)})
            run["queue"].put({"stage": stage, "data": data or {}})
    if stage not in _ROW_MILESTONES:
        return
    # Row writes ride milestones only, so per-page events add no disk I/O:
    # "judged" counts only when the batch loop reports its final page
    # (judged_so_far == of), "images" only when the marker event's count
    # is a real number, not the "?" placeholder.
    if stage == "error":
        _row_update(run_id, status="error",
                    error=str((data or {}).get("error") or "")[:300])
    elif stage == "__end__":
        _row_update(run_id)
    elif stage in ("guide", "built"):
        _row_update(run_id, stage=stage)
    elif stage == "judged":
        _d = data or {}
        if _d.get("of") is not None and \
                _d.get("judged_so_far") == _d.get("of"):
            _row_update(run_id, stage=stage, status="running")
    elif stage == "images":
        if isinstance((data or {}).get("count"), int):
            _row_update(run_id, stage=stage, status="running",
                        images_count=(data or {}).get("count"))
    elif stage == "search_done":
        # W-3: the durable search record (replayed pool + lane plan) rides
        # the row, not the journal — the resume re-enters from it.
        _row_update(run_id, stage=stage, status="running",
                    search={"plan": list((data or {}).get("plan") or []),
                            "pool": list((data or {}).get("results") or [])})
    else:
        _row_update(run_id, stage=stage, status="running")


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
    if stage == "search_done":
        # W-3: the durable search record (plan + pool) lives in the registry
        # row, never in the journal — the journal keeps the run's story, not
        # its bulk. The row write happens on the milestone below.
        d.pop("results", None)
        d.pop("plan", None)
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


# ---- the judged-page substrate (runs/pages/<run_id>.jsonl) ----------------
# One JSON object per line: {"pgid": "pg<n>", "page": <verbatim judged
# record>}. This is the resume memory for the read phase (W-3): the runner
# casts every judged page here right after its verdict, so a failed or
# interrupted run replays its read pages verbatim instead of re-fetching
# them (the plan: an over-cap page is refused honestly and named).
_PAGES_DIR = REPO / "runs" / "pages"
_PAGES_LOCK = threading.Lock()
_PAGES_LINE_CAP = int(
    os.environ.get("GREYSEARCH_PAGES_LINE_CAP") or 1_500_000)
_PAGES_RUN_CAP = int(os.environ.get("GREYSEARCH_PAGES_RUN_CAP") or 8_000_000)
_PAGES_PGIDS: dict = {}
_REFUSED_PAGES: dict = {}


def _pages_file(run_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
        return None
    return Path(_PAGES_DIR) / (str(run_id) + ".jsonl")


def _pages_known(run_id: str) -> set:
    with _PAGES_LOCK:
        s = _PAGES_PGIDS.get(run_id)
        if s is None:
            s = set()
            f = _pages_file(run_id)
            if f and f.is_file():
                for ln in f.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        rec = json.loads(ln)
                    except Exception:
                        continue
                    if isinstance(rec, dict) and rec.get("pgid"):
                        s.add(str(rec["pgid"]))
            _PAGES_PGIDS[run_id] = s
        return s


def _pages_append(run_id: str, pgid: str, page: dict) -> dict:
    """One judged page record, appended idempotently by pgid. An over-cap
    page is refused honestly and named — it is never silently shrunk; the
    resume simply re-reads it. Returns {"kept": bool, "reason": str}."""
    f = _pages_file(run_id)
    if not f:
        return {"kept": False, "reason": "bad run id"}
    try:
        line = json.dumps({"pgid": str(pgid), "page": page},
                          ensure_ascii=False, default=str,
                          separators=(",", ":"))
    except Exception:
        return {"kept": False, "reason": "page record not serializable"}
    if len(line.encode("utf-8", "replace")) > _PAGES_LINE_CAP:
        return {"kept": False,
                "reason": "page too large to journal (1.5 MB line cap) — "
                          "the resume re-reads it"}
    if str(pgid) in _pages_known(run_id):
        return {"kept": True, "reason": "already recorded"}
    with _PAGES_LOCK:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            size = f.stat().st_size if f.is_file() else 0
            if size >= _PAGES_RUN_CAP:
                return {"kept": False,
                        "reason": "run page records hit the 8 MB ceiling — "
                                  "the resume re-reads it"}
            with f.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _PAGES_PGIDS.setdefault(str(run_id), set()).add(str(pgid))
            return {"kept": True, "reason": "recorded"}
        except Exception as _pa:
            return {"kept": False, "reason": str(_pa)[:120]}


def _pages_read(run_id: str) -> list:
    """The run's judged records in pg order. Malformed lines are skipped,
    never fatal (the visualcompanion read_events rule): a torn line costs
    one record, not the run."""
    f = _pages_file(run_id)
    if not f or not f.is_file():
        return []
    try:
        raw = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    recs = []
    for ln in (raw or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("page"), dict):
            recs.append(rec)
    return recs


def _pages_cast(run_id: str, pages_out: list, pg_start: int) -> None:
    """Runner-side persistence for page_cb: cast every judged page to the
    substrate in one sweep, pg ids continuing from pg_start. Refused pgids
    are tracked (the resume reason names them). Never raises — a cast
    failure must not touch the run itself."""
    try:
        refused = _REFUSED_PAGES.setdefault(run_id, [])
        for _i, _pg in enumerate(pages_out or []):
            if not isinstance(_pg, dict):
                continue
            _a = _pages_append(run_id, f"pg{int(pg_start) + _i}", _pg)
            if not _a.get("kept"):
                refused.append(f"pg{int(pg_start) + _i}")
    except Exception:
        pass

LENGTH_PAGES = {"brief": 3, "standard": 4, "deep": 6, "report": 8}

_RUN_WATCHDOG_S = float(os.environ.get("GREYSEARCH_RUN_WATCHDOG_S") or 900.0)


def _runner(run_id: str, query: str, length: str, max_pages: int,
            engines=None, resume=None) -> None:
    """One run attempt, fresh or resumed. On a resume the durable payload
    rides in `resume` ({"attempt", "search", "pages"): the same code
    serves both paths — the research phase replays the recorded search
    and judged pages instead of redoing them (W-3)."""
    with _RUNS_LOCK:
        _ep = _RUNS.get(run_id) or {}
        epoch = int(_ep.get("epoch") or 1)

    def _stale() -> bool:
        """A resumed run's newer runner thread owns the lifecycle; this
        thread's writes stop at the journal (it may still append its
        story) and never touch status or the registry row."""
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if run is None:
            return int(_registry_read(run_id).get("epoch") or 1) > epoch
        return int(run.get("epoch") or 1) > epoch

    def _watchdog(run_id=run_id):
        time.sleep(_RUN_WATCHDOG_S)
        late = False
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
            if run and run["status"] == "running":
                run["status"] = "error"
                late = True
        if not late or _stale():
            # the run finished inside the budget, or a newer runner owns
            # the lifecycle now: a late deadline stays silent, or the
            # journal keeps a phantom failure recorded minutes after the
            # real __end__
            return
        _emit(run_id, "error",
              {"error": "This run took too long and was stopped. Try again — "
                        "or a narrower topic; the search lanes pace themselves."})
        _emit(run_id, "__end__", {})

    threading.Thread(target=_watchdog, daemon=True).start()
    abandoned = False
    _lane = ""
    try:
        _emit(run_id, "start", {"query": query, **(
            {"resumed_attempt": int((resume or {}).get("attempt") or 0)}
            if resume else {})})
        import browser_session as _bs
        try:
            import greysearch_mcp as gm
            # one lane per run: a free map slot, or a brand-new lane when
            # every lane is busy — search volume never queues on a slot
            # cap. The binding rides on this thread (and, via the scrape
            # job arguments, on the scrape-pool threads), never on the
            # process-wide env: runner threads share one process.
            _lane, _lane_note = gm._bind_slot("")
            _bs.set_thread_slot(_lane)
        except Exception:
            _lane = ""
            _bs.set_thread_slot("")
        if not _bs.cdp_alive():
            _bs.ensure_daemon(wait_s=45)
        import research_integration as ri
        import greysearch_mcp as gm

        _rs = resume or {}
        _rs_search = _rs.get("search") or {}

        def _pages_out(pages_out, pg_start: int) -> None:
            _pages_cast(run_id, pages_out, pg_start)

        def _research_phase(result_sink: dict) -> None:
            """Search + read: research_deep with the resume payload when
            the row carries one, else the fresh path — the same code
            serves both (W-3: the resume replays the durable search record
            and the judged pages instead of redoing them)."""
            with _RUNS_LOCK:
                _RUNS[run_id]["length"] = length
            pages = max_pages or LENGTH_PAGES.get(length, 4)
            _budget = {"brief": 240.0, "standard": 300.0, "deep": 420.0,
                       "report": 540.0}.get(length, 300.0)
            result_sink["result"] = ri.research_deep(
                query, max_pages=pages, max_total_seconds=_budget,
                progress_cb=lambda st, d: _emit(run_id, st, d),
                engines=engines, slot=_lane,
                resume_pool=_rs_search.get("pool"),
                resume_lanes=_rs_search.get("plan"),
                resume_pages=_rs.get("pages"),
                page_cb=_pages_out)
            _emit(run_id, "audit", {})

        def _output_phase(result: dict) -> None:
            """Images + guide + the done row: the same finish any run takes.
            The guide re-attaches only when its sibling set (md +
            .run-report.json + .curation.json) is incomplete — a restart
            that landed between the guide write and its done row re-reads
            the finished artifacts instead of rewriting them."""
            write_path = Path(gm._resolve_guide_path(None, query,
                                                     slug_tag=length))
            siblings_done = (
                write_path.is_file()
                and write_path
                .with_suffix(write_path.suffix + ".run-report.json")
                .is_file()
                and write_path
                .with_suffix(write_path.suffix + ".curation.json")
                .is_file())
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
                    dest_dir=write_path.parent /
                    (write_path.stem + "_imgcand"),
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
            if siblings_done:
                # artifacts complete on disk; nothing rewrites or re-judges
                preview = ""
                try:
                    preview = write_path.read_text()[:4000]
                except Exception:
                    pass
                result["master_guide"] = {"path": str(write_path),
                                          "written": True,
                                          "preview": preview}
            else:
                result = gm._attach_guide(result, query, write_path)
            if not ((result or {}).get("master_guide") or {}).get("written"):
                # the publisher failure is a failed run, not a finished one:
                # "done" with no guide on disk lied to /api/latest and the UI
                _why = "; ".join(
                    str(w) for w in (result.get("warnings") or []))
                raise RuntimeError("the publisher wrote no master guide"
                                   + (f" — {_why[:240]}"
                                      if _why.strip() else ""))
            with _RUNS_LOCK:
                _RUNS[run_id]["result"] = result
            _cpath = write_path.with_suffix(
                write_path.suffix + ".curation.json")
            _row_update(run_id, status="done",
                        images_count=len(result.get("image_candidates") or []),
                        curation_path=str(_cpath) if _cpath.is_file()
                        else "")
            _emit(run_id, "guide", {"path": str(write_path)})

        _sink: dict = {}
        _research_phase(_sink)
        result = _sink.get("result")
        if _stale():
            abandoned = True
            _emit(run_id, "abandoned",
                  {"note": "a newer runner took over this run; this "
                           "attempt stopped without touching its status"})
        else:
            _output_phase(result)
    except Exception as e:
        if _stale():
            abandoned = True
            _emit(run_id, "abandoned", {})
        else:
            _emit(run_id, "error", {"error": str(e)[:300]})
    finally:
        if abandoned:
            pass
        elif _stale():
            _emit(run_id, "abandoned", {})
        else:
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
                         "origin": origin,
                         "stage": "",
                         "error": "",
                         "max_pages": max_pages,
                         "started_at": time.time(),
                         "epoch": 1,
                         "resumed": 0}
    _row_write(run_id, _RUNS[run_id])
    threading.Thread(target=_runner,
                     args=(run_id, q, length, max_pages,
                           engines),
                     daemon=True).start()
    global _LAST_RUN_ID
    with _RUNS_LOCK:
        _LAST_RUN_ID = run_id
    return jsonify({"run_id": run_id, "engines": engines,
                    "unknown_engines_dropped": unknown_dropped})

def _journal_stage_lines(run_id: str, tail: int) -> list:
    """The run's story from disk, as {"stage", "data"} SSE-shaped events in
    journal order, capped to the last `tail` stage lines. A journal line is
    {"type":"stage","stage":...,**payload,"ts":...}; the payload (everything
    but type/stage/ts) becomes the event's data object. Journal lines carry
    the run's story, never its bulk (the strip rule above)."""
    info = _events_read(run_id)
    if not info or not info.get("exists"):
        return []
    lines = [e for e in (info.get("events") or [])
             if isinstance(e, dict) and e.get("type") == "stage"
             and e.get("stage")]
    lines = lines[-max(1, tail):]
    out = []
    for ln in lines:
        data = {k: v for k, v in ln.items()
                if k not in ("type", "stage", "ts")}
        out.append({"stage": str(ln.get("stage")), "data": data})
    return out


@app.get("/api/progress/<run_id>")
def api_progress(run_id: str):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if not run:
        # Restart-orphaned run: its stage story survives in the journal,
        # so the progress bar replays instead of answering 404. The
        # replayed stream is read-only history — a run that stopped
        # mid-flight ends after the tail (the sweep holds its true
        # status in the registry row).
        replay = _journal_stage_lines(
            run_id, int(os.environ.get("GREYSEARCH_PROGRESS_REPLAY_LINES")
                        or 400))
        if not replay:
            return jsonify({"error": "unknown run"}), 404

        def gen():
            import json as _j
            for ev in replay:
                yield f"data: {_j.dumps(ev)}\n\n"
                if ev["stage"] == "__end__":
                    return
            yield f"data: {_j.dumps({'stage': '__end__', 'data': {'replayed': True}})}\n\n"

        return Response(gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

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
    for i, p in enumerate(pages[:APPENDIX_MAX_PAGES]):
        clean = p.get("clean") or {}
        title = clean.get("title") or p.get("title") or p.get("url")
        url = p.get("url") or ""
        body = clean.get("body_text") or p.get("text") or ""
        paras = [x.strip() for x in re.split(r"\n\s*\n", body)
                 if len(x.strip()) > APPENDIX_MIN_PARA_CHARS]
        paras = paras[:APPENDIX_MAX_PARAS]
        out.append(f"**{i + 1}. {title}**  ")
        if url:
            out.append(f"<{url}>")
        out.append("")
        out += [x + "\n" for x in paras]
    return "\n".join(out)

def _compose_refined_guide(result: dict, refined_text: str,
                           refine_prompt: str) -> str:
    """Final guide body = brief + refined (model-written, opt-in) sections +
    research appendix + sources. Everything stays source-grounded; the
    refined text is the model's parse of gathered data, not invention. The
    original deterministic guide file is NOT modified — it stays on disk
    unchanged as this page's source of truth, and this disclaimer sits at
    the head of the composed page saying so."""
    _gname = Path((result.get("master_guide") or {}).get("path") or
                  "the saved guide").name
    head = (f"**Focus:** {refine_prompt[:200]} · *Optional model rewrite — "
            f"the original deterministic guide (`{_gname}`) is the source of "
            "truth and is unchanged on disk.*\n")
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
    for i, c in enumerate((chosen or [])[:MAX_CHOSEN_IMAGES]):
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
                        "stage": run.get("stage") or "",
                        "error": run.get("error") or "",
                        "origin": run.get("origin") or "webui",
                        "exists": bool(run)})
    best = {}
    if _REG_DIR.is_dir():
        for p in _REG_DIR.glob("*.json"):
            try:
                m = json.loads(p.read_text())
            except Exception:
                continue
            org = str(m.get("origin") or "").strip() or "webui"
            if org == "qa" and not want_all:
                continue
            # every status tells the truth about this run (done, error,
            # interrupted, running): the newest non-qa row is the latest
            # run, whatever happened to it
            if m.get("written", 0) > best.get("written", 0):
                best = m
    if best:
        return jsonify({"run_id": best.get("run_id"),
                        "status": best.get("status") or "done",
                        "stage": best.get("stage") or "",
                        "error": best.get("error") or "",
                        "origin": str(best.get("origin") or "webui"),
                        "exists": True})
    return jsonify({"run_id": _LAST_RUN_ID, "status": None,
                    "exists": bool(run)})

BUILD_TIMEOUT_S = float(os.environ.get("GREYSEARCH_BUILD_TIMEOUT_S") or 180.0)
BUILD_SUB_TIMEOUT_S = 150

# W-5 named gating constants — these caps decide how much user-visible site
# content exists (images per build, chosen-photo inserts, research-appendix
# depth); they edit published output, so each carries a name.
BUILD_MAX_IMAGES = 40      # --max-images passed to the site builder
MAX_CHOSEN_IMAGES = 3      # curated "chosen" photos inserted into the guide
APPENDIX_MAX_PAGES = 8     # accepted sources shown in the research appendix
APPENDIX_MAX_PARAS = 5     # prose paragraphs kept per appendix source
APPENDIX_MIN_PARA_CHARS = 100  # a paragraph shorter than this is chrome.0


@app.post("/api/build/<run_id>")
def api_build(run_id: str):
    """Confirm step: chosen images + theme -> final guardrailed site.
    Restart-proof like /api/run: a finished run whose in-memory entry is
    gone after a portal restart hydrates from the disk registry (the same
    run the station can still reopen and whose record/guide serve fine),
    so the publish drawer keeps building it instead of answering 400.
    Refine state is live-session by design; a hydrated run builds from
    its master guide on disk."""
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
    if run and run["status"] != "done":
        return jsonify({"error": "run not finished"}), 400
    if run is None:
        reg = _registry_read(run_id)
        if reg.get("status") != "done" or not reg.get("guide_path"):
            return jsonify({"error": "run not finished"}), 400
        run = {"result": {"question": reg.get("query") or "",
                          "master_guide": {"path": reg["guide_path"]}},
               "latest_refine": {}}
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
    tmp_md_tmp = tmp_md.with_name(tmp_md.name + ".tmp")
    tmp_md_tmp.write_text(md_text, encoding="utf-8")
    os.replace(tmp_md_tmp, tmp_md)
    import subprocess, sys as _sys
    import shutil as _shutil
    site_out = tmp_md.with_name(tmp_md.stem + "_site")
    _old_zip = tmp_md.with_name(tmp_md.stem + "_site.zip")
    _old_pdf = site_out.with_suffix(".pdf")
    # a failed rebuild must never stand in for success: the previous
    # build's success signals (site dir, zip, pdf) are gone before the
    # new builder starts
    for _stale in (_old_zip, _old_pdf, site_out):
        try:
            if _stale.is_dir():
                _shutil.rmtree(_stale)
            elif _stale.is_file():
                _stale.unlink()
        except Exception:
            pass
    _boot = ("import sys; sys.path.insert(0, %r); "
             "import greysearch_site_builder as m; "
             "sys.exit(m.render())" % str(REPO))
    try:
        pr = subprocess.run(
            [_sys.executable, "-c", _boot,
             str(tmp_md), "-o", str(site_out), "--theme", theme,
             "--title", _build_title(result),
             "--max-images", str(BUILD_MAX_IMAGES)],
            capture_output=True, text=True, timeout=BUILD_SUB_TIMEOUT_S,
            cwd=str(REPO))
    except subprocess.TimeoutExpired:
        _why = ("the site build ran past its "
                f"{int(BUILD_SUB_TIMEOUT_S)}-second budget and was "
                "stopped (builder wedged); nothing was published — "
                "your guide is unchanged")
        run["build"] = {"site": None, "ok": False, "zip": None,
                        "pdf": None, "pdf_note": "", "theme": theme,
                        "guardrails": {}, "tail": "build timeout"}
        _emit(run_id, "built", {"ok": False, "site": None})
        return jsonify({"error": _why, "ok": False}), 502
    ok = (site_out / "index.html").is_file()
    zip_path = None
    pdf_path = None
    notes = []
    if ok:
        try:
            _shutil.make_archive(str(site_out), "zip", site_out)
            zip_path = str(site_out) + ".zip"
        except Exception as _ze:
            notes.append(f"zip failed: {str(_ze)[:120]}")
        if zip_path:
            try:
                import pdf_export
                pdf_path = pdf_export.render_pdf(
                    str(site_out / "index.html"),
                    str(site_out.with_suffix(".pdf")))
                if not pdf_path:
                    notes.append("render returned None (see portal log)")
            except Exception as _pe:
                notes.append(f"pdf error: {str(_pe)[:160]}")
    guard = {}
    try:
        guard = json.loads((site_out / "guardrails.json").read_text())
    except Exception:
        pass
    run["build"] = {"site": str(site_out) if ok else None, "ok": ok,
                    "zip": zip_path, "pdf": pdf_path,
                    "pdf_note": "; ".join(notes), "theme": theme,
                    "guardrails": guard,
                    "tail": (pr.stderr or "")[-400:],
                    # W-4 provenance: which text the built site came from and
                    # which file stays the source of truth
                    "refined_source": ("model-rewrite (optional)"
                                       if refine.get("text")
                                       else "deterministic"),
                    "base_guide": str(gpath)}
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
    out = {"ok": False, "text": ""}
    if not run.get("length"):
        reg = _registry_read(run_id)
        run.setdefault("length", reg.get("length") or "standard")
        run.setdefault("engines", reg.get("engines") or [])
    try:
        import dossier as _d
        text = _d.build_dossier(result, question + " " + prompt,
                                budget_chars=9000)
    except Exception as _de:
        out = {"ok": False,
               "text": "The research record for this run could not be "
                       "composed for a rewrite; your results and guide "
                       "are unchanged.",
               "error": str(_de)[:200]}
        _emit(run_id, "refine", {"ok": False})
        return jsonify(out)
    try:
        import llm_audit as _la
        # W-4 honesty: a closed model lane is a POLICY state, not an outage.
        # The rewrite is an optional enhancer — the deterministic research,
        # the guide, and every export complete without it.
        if not _la.model_allowed():
            out = {"ok": False,
                   "text": "Refine is the optional model rewrite stage, and "
                           "the model lane is OFF on this server by policy. "
                           "The deterministic research below, the guide, and "
                           "all exports are complete without it.",
                   "reason": "model lane off by policy"}
            _emit(run_id, "refine", {"ok": False})
            return jsonify(out)
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
                       "policy": "optional-enhancer",
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
                        "refine": (run.get("latest_refine") or {}),
                        "stage": run.get("stage") or "",
                        "error": run.get("error") or "",
                        "resume": run.get("resume") or {"can": False,
                                                        "reason": "",
                                                        "from_stage": ""}})
    # Restart-proof hydrate: a run whose in-memory entry is gone re-serves
    # from the disk registry. A failed or interrupted run hydrates as an
    # empty shell so /api/run tells the same truth the row does (a done
    # run as always serves from the disk registry + the run report on
    # disk; the live text view (pages_fetched) is session-only by design
    # and the curated research lives in the curation sidecar).
    reg = _registry_read(run_id)
    reg_status = str(reg.get("status") or "")
    _no_resume = {"can": False, "reason": "", "from_stage": ""}
    if reg_status in ("error", "interrupted"):
        return jsonify({"status": reg_status, "result": {"question":
                                                         reg.get("query") or ""},
                        "build": None, "refine": {},
                        "stage": reg.get("stage") or "",
                        "error": reg.get("error") or "",
                        "resume": reg.get("resume") or _no_resume})
    if reg_status != "done":
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
                    "build": None, "refine": {},
                    "stage": reg.get("stage") or "",
                    "error": "",
                    "resume": reg.get("resume") or _no_resume})

_FETCH_URLS_CAP = 8
_FETCH_URLS_WALL_S = 180.0
_WAVE_LOCKS: dict = {}
_WAVE_LOCKS_GUARD = threading.Lock()

# A rescanned row still reading "running" gets this many seconds of zombie
# guard before the sweep may call it interrupted: a reader thread that is
# actively writing page records is never declared dead by the sweep and
# never double-reaped by a resume (W-3).
READ_STALE_S = float(os.environ.get("GREYSEARCH_READ_STALE_S") or 120.0)


def _resume_plan(run_id: str, reg: dict | None = None) -> dict:
    """W-3 owner trigger: whether a failed or interrupted run can re-enter,
    and from which stage. Artifact = truth, never the capped journal: the
    durable search record rides the row (row.search), the judged-page
    records ride runs/pages, and guide completeness is judged from the
    sibling set on disk (md + .run-report.json + .curation.json). A row
    still reading running is refused — the interrupted sweep keeps a
    READ_STALE_S zombie guard, so a reader still writing page records is
    never double-reaped — and every answer records that the optional model
    rewrite is not part of a resume (a resume rebuilds the rules-built
    guide, which is the original)."""
    reg = reg if (isinstance(reg, dict) and reg) else _registry_read(run_id)
    _empty = {"can": False, "reason": "unknown run", "from_stage": "",
              "attempt": 0, "search": {}, "pages": []}
    if not reg:
        return _empty
    status = str(reg.get("status") or "")
    if status == "running":
        _empty["reason"] = ("the row still reads running (the interrupted "
                            "sweep keeps a %d s zombie guard); wait for it "
                            "to settle") % int(READ_STALE_S)
        return _empty
    if status not in ("error", "interrupted"):
        _empty["reason"] = "only failed or interrupted runs resume"
        return _empty
    _search = reg.get("search") if isinstance(reg.get("search"), dict) else {}
    plan = list(_search.get("plan") or [])
    pool = [r for r in (_search.get("pool") or [])
            if isinstance(r, dict) and str(r.get("url") or "").strip()]
    pool_urls = {str(r.get("url") or "").strip() for r in pool}
    pages = _pages_read(run_id)
    page_urls = set()
    for rec in pages:
        u = str(((rec.get("page") or {}).get("url")) or "")
        if u:
            page_urls.add(u)
    gp = Path(str(reg.get("guide_path") or ""))
    siblings_done = (bool(str(reg.get("guide_path") or "")) and gp.is_file()
                     and gp
                     .with_suffix(gp.suffix + ".run-report.json").is_file()
                     and gp
                     .with_suffix(gp.suffix + ".curation.json").is_file())
    if siblings_done and pool_urls:
        from_stage = "output"
    elif not pool_urls:
        from_stage = "search"
    elif pool_urls <= page_urls:
        from_stage = "output"
    else:
        from_stage = "read"
    reasons: list = []
    refused = _REFUSED_PAGES.get(run_id) or []
    if refused:
        reasons.append("%d page(s) were too large to journal; the resume "
                       "re-reads them" % len(refused))
    reasons.append("the optional model rewrite is not part of a resume; "
                   "the rules-built guide always rebuilds")
    return {"can": True,
            "reason": "; ".join(reasons),
            "from_stage": from_stage,
            "attempt": int(reg.get("resumed") or 0) + 1,
            "search": {"plan": plan, "pool": pool},
            "pages": pages}


@app.post("/api/resume/<run_id>")
def api_resume(run_id: str):
    """W-3 owner trigger: re-enter a failed (error) or interrupted run
    from its durable state. The plan comes from disk artifacts; the new
    attempt takes the row's next epoch (a stale attempt's writes stop at
    the journal and it exits as an "abandoned" ghost); the optional model
    rewrite is never part of a resume. A per-run lock keeps a resume and
    a fetch-urls wave from dancing on the same row at the same time."""
    with _RUNS_LOCK:
        live = _RUNS.get(run_id)
        live_status = (live or {}).get("status")
    reg = _registry_read(run_id)
    if not reg and not live:
        return jsonify({"error": "unknown run"}), 404
    if live_status == "running":
        return jsonify({"error": "this run is still in progress"}), 409
    plan = _resume_plan(run_id, reg or None)
    if not plan.get("can"):
        # covers done rows ("only failed or interrupted runs resume") and
        # the zombie-guard window (a row still reading running after a
        # crash whose sweep has not settled it yet)
        return jsonify({"error": plan.get("reason")
                        or "this run cannot resume"}), 409
    q = str(reg.get("query") or "").strip()
    length = str(reg.get("length") or "standard")
    max_pages = int(reg.get("max_pages") or LENGTH_PAGES.get(length, 4))
    engines = reg.get("engines") if isinstance(reg.get("engines"), list) \
        else []
    if not q:
        return jsonify({"error": "this run's row lost its query; nothing "
                                 "to resume"}), 409
    with _WAVE_LOCKS_GUARD:
        lock = _WAVE_LOCKS.setdefault(run_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return jsonify({"error": "a resume or fetch is already running "
                                 "for this run"}), 409
    try:
        attempt = int(plan.get("attempt") or 1)
        epoch = int(reg.get("epoch") or 1) + 1
        with _RUNS_LOCK:
            _RUNS[run_id] = {"status": "running", "events": [],
                             "queue": queue.Queue(), "result": None,
                             "query": q,
                             "length": length,
                             "engines": engines,
                             "origin": str(reg.get("origin") or "webui"),
                             "stage": "",
                             "error": "",
                             "max_pages": max_pages,
                             "started_at": time.time(),
                             "epoch": epoch,
                             "resumed": attempt,
                             "search": plan["search"],
                             "resume": {"can": False, "reason": "",
                                        "from_stage": ""}}
        _row_write(run_id, _RUNS[run_id])
        _emit(run_id, "resume", {"from_stage": plan.get("from_stage") or "",
                                 "attempt": attempt,
                                 "note": "the optional model rewrite is "
                                         "not part of a resume; the "
                                         "rules-built guide always rebuilds"})
        _pages_known(run_id)  # warm the idempotency cache from disk
        _runner_payload = {"attempt": attempt,
                           "search": plan["search"],
                           "pages": plan.get("pages") or []}
        threading.Thread(target=_runner,
                         args=(run_id, q, length, max_pages, engines,
                               _runner_payload),
                         daemon=True).start()
        global _LAST_RUN_ID
        with _RUNS_LOCK:
            _LAST_RUN_ID = run_id
        return jsonify({"run_id": run_id, "status": "running",
                        "from_stage": plan.get("from_stage") or "",
                        "attempt": attempt, "epoch": epoch})
    finally:
        lock.release()


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
        run_status = (run.get("status") if run else None)
    if run_status in ("error", "interrupted"):
        return jsonify({"error": "this run did not finish; resume it first "
                                 "(the run page's Resume control or POST "
                                 "/api/resume) before fetching more "
                                 "pages"}), 409
    if not guide_path:
        reg = _registry_read(run_id)
        reg_status = str(reg.get("status") or "")
        if reg_status in ("error", "interrupted"):
            return jsonify({"error": "this run did not finish; resume it "
                                     "first (the run page's Resume control "
                                     "or POST /api/resume) before fetching "
                                     "more pages"}), 409
        if reg_status == "done":
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
                try:
                    import greysearch_mcp as _gm2
                    # this request's scrapes ride their own lane (a free
                    # slot or a freshly spawned one), never another run's
                    # browser; the binding dies with the request thread
                    _lane2, _lane2_note = _gm2._bind_slot("")
                    _bs.set_thread_slot(_lane2)
                except Exception:
                    _bs.set_thread_slot("")
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
        try:
            import browser_session as _bs
            _bs.clear_thread_slot()
        except Exception:
            pass
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

def _main():
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
    sweep is a broken record, so picks stay durable). 2026-11-04 (W-8): a
    themed guide .md whose run artifacts (run report or curation sidecar)
    still exist is NOT disposable either — the guide itself survives even
    when its name carries a theme suffix; only artifact-less theme-mid
    build twins get swept."""
    name = os.path.basename(str(path))
    if name.endswith(".md") or name.endswith(".md.run-report.json"):
        for th in _THEMES:
            if name.endswith(f"-{th}.md"):
                _p = Path(str(path))
                if (_p.with_suffix(
                        _p.suffix + ".run-report.json").is_file()
                        or _p.with_suffix(
                            _p.suffix + ".curation.json").is_file()):
                    return False
                return True
        return False
    return "_site" in name

_JANITOR_LOG = REPO / "runs" / "janitor.jsonl"
_JANITOR_LOG_MAX_BYTES = 1_000_000
_JANITOR_LOG_KEEP = 250

def _janitor_log(entries: list) -> None:
    """Sweep honesty: every sweep that removed something logs the full
    removed paths to the portal log AND appends one JSON line to capped
    runs/janitor.jsonl, so "my site vanished" is answerable from disk.
    Cap: past the byte budget the file is rewritten with its last
    _JANITOR_LOG_KEEP lines (tmp + os.replace, the registry-row atomic
    pattern); append failures never break the sweep."""
    if not entries:
        return
    print("greysearch janitor: removed %d item(s): %s"
          % (len(entries), ", ".join(entries[:8])), flush=True)
    try:
        _JANITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "removed": entries}, ensure_ascii=False) + "\n"
        if (_JANITOR_LOG.exists()
                and _JANITOR_LOG.stat().st_size > _JANITOR_LOG_MAX_BYTES):
            keep = _JANITOR_LOG.read_text(
                errors="ignore").splitlines()[-_JANITOR_LOG_KEEP:]
            tmp = _JANITOR_LOG.with_name(_JANITOR_LOG.name + ".tmp")
            tmp.write_text("".join(l + "\n" for l in keep))
            os.replace(tmp, _JANITOR_LOG)
        with _JANITOR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as _jl:
        print("greysearch: janitor log failed: %s" % str(_jl)[:120],
              flush=True)

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
            gone.append(str(path))
        except Exception:
            continue
    _janitor_log(gone)
    return gone

def _sweep_stale_rows() -> list:
    """The interrupted-state sweep: a registry row stuck on status
    "running" whose events journal has no __end__ line is a run whose
    runner died without finishing (portal restart, crash). The row is
    rewritten IN PLACE to status "interrupted" and the same pass computes
    the resume table from the durable artifacts; nothing is deleted —
    the stage story stays in the journal, artifacts stay on disk, and
    POST /api/resume re-enters the run. A capped journal never gets the
    sweep (its tail cannot prove how the run really ended), so its row
    keeps its status. Returns the swept run ids."""
    swept = []
    try:
        _REG_DIR.mkdir(parents=True, exist_ok=True)
        for p in _REG_DIR.glob("*.json"):
            try:
                m = json.loads(p.read_text())
            except Exception:
                continue
            if str(m.get("status") or "") != "running":
                continue
            rid = str(m.get("run_id") or p.stem)
            with _RUNS_LOCK:
                live = _RUNS.get(rid)
            if live is not None:
                # a runner thread in this process owns the run: no
                # __end__ yet just means it is still working
                continue
            story = _events_read(rid) or {}
            if story.get("capped"):
                continue
            if any(isinstance(e, dict) and e.get("type") == "stage"
                   and e.get("stage") == "__end__"
                   for e in (story.get("events") or [])):
                continue
            stage = str(m.get("stage") or "")
            m["status"] = "interrupted"
            # W-3: the same pass computes and writes the real resume table
            # from the artifacts (search record on the row, judged pages in
            # runs/pages, sibling set on disk) so the owner sees "resume"
            # the moment the sweep speaks, without a second read.
            _plan = _resume_plan(rid, {**m, "status": "interrupted"})
            m["resume"] = {"can": bool(_plan.get("can")),
                           "reason": _plan.get("reason") or "",
                           "from_stage": _plan.get("from_stage") or stage}
            m["updated_at"] = time.time()
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(m, ensure_ascii=False))
            os.replace(tmp, p)
            swept.append(rid)
    except Exception as _sw:
        print("greysearch: interrupted-row sweep failed: %s"
              % str(_sw)[:160], flush=True)
    return swept


def _janitor():
    while True:
        try:
            _janitor_sweep()
            _sweep_stale_rows()
        except Exception:
            pass
        time.sleep(60)

_start_janitor = threading.Thread(
    target=_janitor, daemon=True, name="gr-janitor").start()

_sweep_stale_rows()

if __name__ == "__main__":
    _main()
