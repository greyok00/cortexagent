"""Real run records + engine-state endpoints for the Greysearch web portal.

Registered on the Flask app by bin/greysearch-portal.py. Reads real files:
the shared guides folder and the slot map. Serves no fixtures.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

from flask import request, Response, jsonify

GUIDE_ROOT = Path(__file__).resolve().parent / "guides"
SLOT_MAP = Path(__file__).resolve().parent / "research" / "browser-ports.json"
SETS_ROOT = Path(__file__).resolve().parent / "research" / "sets"
SET_SELECT_CAP = 4000


_HTTP = re.compile(r"^https?://", re.I)


def render_markdown(text):
    import markdown as _md
    safe = re.sub(r"<(?=[A-Za-z/!])", "&lt;", text)
    return _md.markdown(safe, extensions=["tables", "sane_lists", "fenced_code"])


def real_runs(days=3, limit=300, origin=None):
    """Newest-first tile records from the real guides tree.

    Tiles are DEDUPED by research question: the same query used to show
    once per tier slug (a rerun produced "-2-standard" twins), which
    read as three different researches when it was one. Key: the run
    report's query when it names one (whitespace-collapsed, case-folded),
    else the guide stem with the MASTER-GUIDE- prefix and trailing tier
    suffix stripped. The NEWEST guide per key wins; nothing on disk is
    renamed or removed (display-level dedupe only).

    Every row carries the run's origin and, for the portal's own runs,
    its run_id. The portal registry (runs/portal/<id>.json) maps finished
    portal submissions to their guides; a guide it names is origin
    "webui" (or "qa" for acceptance-gate submissions). A guide in the
    SHARED guides tree that no registry row names was written by some
    other tool on this machine: origin "automation", no run_id. The
    origin filter applies BEFORE the query dedupe so a portal run of a
    query is never hidden by a newer same-query automation guide; rows
    without a known registry origin read as "webui" (that registry only
    ever held portal submissions)."""
    import time as _time
    now = _time.time()
    out = {}
    if not GUIDE_ROOT.exists():
        return []
    reg_dir = GUIDE_ROOT.parent / "runs" / "portal"
    registry = {}
    if reg_dir.is_dir():
        for _p in reg_dir.glob("*.json"):
            try:
                _m = json.loads(_p.read_text())
            except (ValueError, OSError):
                continue
            _gp = _m.get("guide_path")
            if _gp:
                registry[str(_gp)] = _m
    for day in sorted(GUIDE_ROOT.iterdir(), reverse=True):
        if not day.is_dir():
            continue
        try:
            if now - day.stat().st_mtime > days * 86400:
                continue
        except OSError:
            continue
        for guide in sorted(day.glob("MASTER-GUIDE-*.md"), reverse=True):
            try:
                if now - guide.stat().st_mtime > days * 86400:
                    continue
            except OSError:
                continue
            reg = registry.get(str(guide))
            org = "automation"
            rid = ""
            if reg is not None:
                rid = str(reg.get("run_id") or "")
                org = str(reg.get("origin") or "").strip() or "webui"
            if origin and origin not in ("all",) and org != origin:
                continue
            report = guide.with_suffix(guide.suffix + ".run-report.json")
            meta = {}
            if report.exists():
                try:
                    meta = json.loads(report.read_text())
                except (ValueError, OSError):
                    meta = {}
            stem = guide.stem.replace("MASTER-GUIDE-", "")
            for _t in ("brief", "standard", "deep", "report"):
                if stem.endswith("-" + _t):
                    stem = stem[: -len("-" + _t)]
            q = " ".join(str(meta.get("query") or "").lower().split())
            # slug-queries carry hyphens where the rerun carries spaces;
            # same research, so the key collapses every non-alphanumeric run
            flat = re.sub(r"[^a-z0-9]+", "", q or stem.strip("-").lower())
            key = flat if flat else (q or stem)
            row = {
                "day": day.name,
                "name": guide.name,
                "query": meta.get("query") or guide.stem.replace("MASTER-GUIDE-", ""),
                "origin": org,
                "run_id": rid,
                "bytes": guide.stat().st_size,
                "modified": int(guide.stat().st_mtime),
                "candidates": meta.get("candidate_count"),
                "scraped": meta.get("scraped_count"),
                "accepted": meta.get("accepted_count"),
                "quarantined": meta.get("quarantined_count"),
                "rejected": meta.get("rejected_count"),
                "skipped": len(meta.get("skipped_pages") or []),
                "warnings": len(meta.get("quality_warnings") or []),
                "accepted_sources": [
                    s.get("url") if isinstance(s, dict) else str(s)
                    for s in (meta.get("accepted_sources") or [])
                ][:12],
            }
            if key in out:
                if row["modified"] <= out[key]["modified"]:
                    continue
            out[key] = row
    out_sorted = list(out.values())
    out_sorted.sort(key=lambda r: r["modified"], reverse=True)
    return out_sorted[:limit]


def engine_state():
    """The REAL research lane and honest engine facts for the strip: the
    lane comes from THIS process's RESEARCH_TASK environment (the unit
    drop-in), its port from the slot map, plus a live probe; the enabled
    engine catalog comes from the local SearXNG's own /config endpoint
    (read-only); the newest guide fact stays. The older static pinned-slot
    file is no longer read: it named a slot the portal never actually
    ran, so the strip could disagree with this process's real lane. Also
    carries the plain-language search note so the UI can describe, in the
    UI's own words, what the research pipeline does (heuristics + a real
    browser; the model step is optional and off)."""
    import os as _os
    import socket as _socket
    slots = []
    tasks = {}
    try:
        tasks = json.loads(SLOT_MAP.read_text()).get("tasks", {})
    except (OSError, ValueError):
        tasks = {}
    for name, cfg in sorted(tasks.items(), key=lambda kv: kv[1].get("port", 0)):
        port = cfg.get("port", 0) if isinstance(cfg, dict) else None
        up = False
        if isinstance(port, int):
            s = _socket.socket()
            s.settimeout(0.25)
            try:
                up = s.connect_ex(("127.0.0.1", port)) == 0
            finally:
                s.close()
        slots.append({"task": name, "port": port, "up": up})
    lane_task = (_os.environ.get("RESEARCH_TASK") or "").strip()
    lane_cfg = tasks.get(lane_task) if lane_task else None
    lane_port = lane_cfg.get("port") if isinstance(lane_cfg, dict) else None
    lane_up = False
    if isinstance(lane_port, int):
        s = _socket.socket()
        s.settimeout(0.25)
        try:
            lane_up = s.connect_ex(("127.0.0.1", lane_port)) == 0
        finally:
            s.close()
    newest = None
    runs = real_runs(limit=1, origin="webui")
    if runs:
        newest = {"query": runs[0]["query"], "written": runs[0]["modified"],
                  "accepted": runs[0]["accepted"], "bytes": runs[0]["bytes"]}
    catalog = []
    try:
        from searxng_integrated import engine_catalog
        catalog = engine_catalog()
    except Exception:
        catalog = []
    return {
        "slots": slots,
        "listening": sum(1 for s in slots if s["up"]),
        "browser": {"task": lane_task, "port": lane_port, "up": lane_up},
        "newest": newest,
        "search_note": ("searches: deterministic heuristics + the real "
                        "browser; the model step is optional and off"),
        "engine_catalog": catalog,
        "engines_enabled": len(catalog),
    }


def _realpath(p):
    """Older records carry absolute paths under the tree's former
    greysearch-public name; rewrite them onto the tree that lives at
    ~/greysearch."""
    s = str(p or "")
    _tree = str(Path.home() / "greysearch")
    _old = str(Path.home() / "greysearch-public") + "/"
    if s.startswith(_old):
        return Path(_tree + s[len(_old) - 1:])
    return Path(s)


def _curation_path_for_run(run_id: str):
    """Resolve a run_id to its curation.json by asking the portal's own run
    route (the in-process route keeps run_id -> guide path for recent runs);
    after the janitor ages a run out, curation stays on disk beside the guide,
    but the run_id -> guide mapping is gone; saved sets carry the guide path
    themselves, so they never depend on this resolution."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
        return None
    try:
        import portal_server as _ps
        resp = _ps.app.test_client().get(f"/api/run/{run_id}")
        payload = resp.get_json(silent=True) or {}
        path = ((payload.get("result") or {}).get("master_guide") or {}).get("path")
    except Exception:
        return None
    if not path:
        return _curation_on_disk(run_id)
    cpath = _realpath(str(path))
    cpath = cpath.with_suffix(cpath.suffix + ".curation.json")
    return cpath if cpath.is_file() else None


def _curation_on_disk(run_id: str):
    """Restart-proof fallback for runs whose in-memory mapping is gone:
    the portal's registry (runs/portal/<id>.json) names each run's guide."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", str(run_id)):
        return None
    regp = Path(__file__).resolve().parent / "runs" / "portal" / f"{run_id}.json"
    try:
        reg = json.loads(regp.read_text())
    except (OSError, ValueError):
        return None
    if not reg.get("guide_path"):
        return None
    cpath = _realpath(reg["guide_path"])
    cpath = cpath.with_suffix(cpath.suffix + ".curation.json")
    return cpath if cpath.is_file() else None


def _load_set(set_id: str):
    safe = Path(set_id).name
    p = SETS_ROOT / f"{safe}.json"
    if not re.fullmatch(r"[a-z0-9-]{6,48}", safe) or p.suffix != ".json" or not p.is_file():
        return None, p
    try:
        return json.loads(p.read_text()), p
    except (OSError, ValueError):
        return None, p


def _save_set(set_id: str, data: dict, p=None):
    if p is None:
        safe = Path(set_id).name
        if not re.fullmatch(r"[a-z0-9-]{6,48}", safe):
            raise ValueError("bad set id")
        p = SETS_ROOT / f"{safe}.json"
    SETS_ROOT.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    data["updated"] = now
    data.setdefault("created", now)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def _draft_override(data: dict):
    """The set's hand-edited markdown, when the user wrote one. An override
    is a user document: compose/export serve it verbatim so user-removed
    text stays removed, until the user explicitly resets it."""
    if not data.get("draft_md"):
        return None
    return str(data["draft_md"])


def _compose_markdown(data: dict, sets_payload: dict):
    """Deterministic draft from a set's selections: paragraphs grouped by
    source, chosen keywords as a topics line, chosen images with provenance.
    No LLM. Returns (markdown_text, chosen_paragraph_count).
    Selection page keys are namespace-prefixed by run id ("run:pg0") because
    every run's record numbers its own pages pg0..pgN; bare keys are legacy
    sets that resolve across all runs (later records win)."""
    selections = data.get("selections") or {}
    by_page = {p["id"]: p for p in (sets_payload.get("pages") or [])}
    ns = {}
    for rid, lst in (sets_payload.get("namespaces") or {}).items():
        ns[str(rid)] = {p["id"]: p for p in (lst or []) if isinstance(p, dict)}
    lines = [f"# Research set - {data.get('name', data.get('set_id', 'research'))}", ""]
    if data.get("queries"):
        lines += [f"Research questions: {', '.join(map(str, data['queries']))}", ""]
    chosen_paras = 0
    for pgid, para_ids in (selections.get("paragraphs") or {}).items():
        if ":" in str(pgid):
            rid, bare = str(pgid).split(":", 1)
            page = (ns.get(rid) or {}).get(bare)
        else:
            page = by_page.get(pgid)
        if not page:
            continue
        lines += [f"## {page.get('title') or page.get('url', '')[:80]}", ""]
        lines += [f"Source: {page.get('url')} - verdict: "
                  f"{page.get('decision') or 'n/a'}", ""]
        for pid in para_ids[:SET_SELECT_CAP]:
            para = next((q for q in (page.get("paragraphs") or [])
                         if q["id"] == pid), None)
            if not para:
                continue
            lines += ["> " + str(para['text']).replace("\n", "\n> "), ""]
            chosen_paras += 1
    chosen_kws = sorted({k for k in (selections.get("keywords") or [])
                         if isinstance(k, str)})[:40]
    if chosen_kws:
        lines += ["## Keywords across the set", ""]
        lines += [", ".join(chosen_kws), ""]
    cand_by_file = {c["file"]: c for c in (sets_payload.get("image_candidates") or [])
                    if isinstance(c, dict)}
    chosen_imgs = (selections.get("images") or [])[:SET_SELECT_CAP]
    img_lines, seen_href = [], set()
    for c in chosen_imgs:
        if not isinstance(c, dict):
            c = {"file": str(c)}
        f = str(c.get("file") or "")
        src = str(c.get("url") or "")
        t = str(c.get("title") or c.get("keyword") or "")
        lic = str(c.get("license") or "")
        if f and ".." not in f and not f.startswith("/"):
            href = f"/imgcand/{f}"
            page_url = str((cand_by_file.get(f, {}) or {}).get("webpage_url")
                           or c.get("webpage_url") or "")
        elif _HTTP.match(src):
            href = src
            page_url = str(c.get("page") or "")
        else:
            continue
        if href in seen_href:
            continue
        seen_href.add(href)
        img_lines += [f"![{t}]({href})  ", ""]
        prov = "  ".join(x for x in (f"title: {t}" if t else "",
                                     f"license: {lic}" if lic else "",
                                     f"page: {page_url}" if page_url else "") if x)
        if prov:
            img_lines += [f"*{prov}*", ""]
    if img_lines:
        lines += ["## Selected images", ""] + img_lines
    srcs = sorted({p.get("url") for pgid, ids in (selections.get("paragraphs") or {}).items()
                   for p in [by_page.get(pgid)] if p and p.get("url")})
    if srcs:
        lines += ["## Sources used in this selection", ""]
        lines += [f"- {u}" for u in srcs if u]
        lines += [""]
    lines += ["_(composed from your saved selections; deterministic, no model "
              "rewrote this)_", ""]
    return "\n".join(lines), chosen_paras


def _events_save_marker(run_id, set_id):
    """Record the commit boundary in the run's event journal: picks saved
    into this set stop replaying (replay re-applies only the tail after
    the last save marker). Best-effort; a missing run id or a journal
    failure changes nothing the user asked for."""
    try:
        import portal_server as _ps
        _ps._events_write(str(run_id or ""),
                          [{"type": "save", "set_id": str(set_id)}])
    except Exception:
        pass


def register(app):
    @app.route("/runs.html")
    def runs_page():
        body = (Path(__file__).resolve().parent / "portal" / "runs.html").read_bytes()
        return Response(body, mimetype="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    @app.route("/api/runs/portal")
    def api_runs_portal():
        """The runs page's status strip: the registry rows
        (runs/portal/<id>.json) verbatim and newest first, with the
        resume table already on the row. The /api/runs cards stay the
        guides folder's truth; this strip is the run lifecycle's truth
        (running/done/error/interrupted), reading nothing newer than
        what the portal itself recorded."""
        rows_dir = Path(__file__).resolve().parent / "runs" / "portal"
        rows = []
        try:
            files = list(rows_dir.glob("*.json"))
        except Exception:
            files = []
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[:40]:
            try:
                m = json.loads(p.read_text())
            except Exception:
                continue
            rows.append({
                "run_id": str(m.get("run_id") or p.stem),
                "query": str(m.get("query") or ""),
                "status": str(m.get("status") or ""),
                "stage": str(m.get("stage") or ""),
                "origin": str(m.get("origin") or ""),
                "epoch": m.get("epoch"),
                "resumed": m.get("resumed"),
                "resumed_attempt": m.get("resumed"),
                "error": str(m.get("error") or "")[:160],
                "resume": m.get("resume") if isinstance(m.get("resume"), dict) else {},
                "updated_at": m.get("updated_at"),
            })
        return jsonify({"rows": rows, "dir": str(rows_dir)})

    @app.route("/api/runs")
    def api_runs():
        org = (request.args.get("origin") or "").strip().lower()
        if org not in ("webui", "qa", "automation", "all", ""):
            return jsonify({"error": "origin filter: webui|qa|automation|all"})
        return jsonify({"runs": real_runs(
            origin=None if org in ("", "all") else org),
            "root": str(GUIDE_ROOT)})

    @app.route("/api/engine")
    def api_engine():
        return jsonify(engine_state())

    @app.route("/api/curation/<run_id>")
    def api_curation(run_id):
        cpath = _curation_path_for_run(run_id)
        if not cpath:
            return jsonify({"exists": False, "run_id": run_id}), 200
        try:
            payload = json.loads(cpath.read_text())
        except (OSError, ValueError):
            return jsonify({"exists": False, "run_id": run_id}), 200
        return jsonify({"exists": True, "run_id": run_id,
                        "curation_path": str(cpath), "curation": payload})

    @app.route("/api/events/<run_id>", methods=["GET"])
    def api_events_read(run_id):
        """The run's interaction+stage journal (visualcompanion events
        contract): the client replays uncommitted picks from it on every
        load; malformed lines are skipped server-side, never fatal."""
        try:
            import portal_server as _ps
            info = _ps._events_read(run_id)
        except Exception:
            return jsonify({"error": "the event journal is not available "
                                     "right now"}), 500
        if info is None:
            return jsonify({"error": "bad run id"}), 400
        return jsonify(info)

    @app.route("/api/events/<run_id>", methods=["POST"])
    def api_events_write(run_id):
        """Append one batch of client events. Validated by a strict
        server-side whitelist rebuild; only known types with known shapes
        survive, timestamps are server-stamped."""
        body = request.get_json(silent=True) or {}
        objs = body.get("events")
        if not isinstance(objs, list) or len(objs) > 128:
            return jsonify({"ok": False,
                            "error": "events: list of at most 128 required"}), 400
        try:
            import portal_server as _ps
            res = _ps._events_write(run_id, objs, validate=True)
        except Exception:
            return jsonify({"error": "the event journal is not available "
                                     "right now"}), 500
        if res is None:
            return jsonify({"error": "bad run id"}), 400
        return jsonify({"ok": True, "kept": res.get("kept", 0),
                        "refused": res.get("refused", 0)})

    @app.route("/api/sets", methods=["GET"])
    def api_sets_list():
        out = []
        if SETS_ROOT.is_dir():
            for p in sorted(SETS_ROOT.glob("*.json"),
                            key=lambda f: f.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(p.read_text())
                except (OSError, ValueError):
                    continue
                out.append({k: d.get(k) for k in
                            ("set_id", "name", "created", "updated",
                             "queries")})
                out[-1]["runs"] = len(d.get("runs") or [])
        return jsonify({"sets": out})

    @app.route("/api/sets", methods=["POST"])
    def api_sets_create():
        body = request.get_json(silent=True) or {}
        set_id = uuid.uuid4().hex[:16]
        cpath = _curation_path_for_run(str(body.get("run_id") or ""))
        if not cpath:
            return jsonify({"ok": False, "error": "run has no curation record "
                                                 "(run not found or too old)"}), 404
        data = {"set_id": set_id, "name": str(body.get("name") or
                                              body.get("query") or "")[:120],
                "queries": [str(body.get("query") or "")[:300]],
                "runs": [{"run_id": str(body.get("run_id") or ""),
                          "curation_path": str(cpath)}],
                "selections": body.get("selections") or {}}
        if body.get("draft_md"):
            data["draft_md"] = str(body["draft_md"])[:200000]
        _save_set(set_id, data)
        _events_save_marker(body.get("run_id"), set_id)
        return jsonify({"ok": True, "set_id": set_id}), 201

    @app.route("/api/sets/<set_id>", methods=["GET"])
    def api_sets_get(set_id):
        data, p = _load_set(set_id)
        if data is None:
            return jsonify({"ok": False, "error": "no such set"}), 404
        runs_payload = {}
        for r in (data.get("runs") or []):
            cp = _realpath(r.get("curation_path") or "")
            if cp.is_file():
                try:
                    runs_payload[r.get("run_id") or r["curation_path"]] = \
                        json.loads(cp.read_text())
                except (OSError, ValueError):
                    pass
        return jsonify({"ok": True, "set": data, "curation": runs_payload})

    @app.route("/api/sets/<set_id>", methods=["PATCH"])
    def api_sets_save(set_id):
        data, p = _load_set(set_id)
        if data is None:
            return jsonify({"ok": False, "error": "no such set"}), 404
        body = request.get_json(silent=True) or {}
        if "selections" in body:
            data["selections"] = body.get("selections") or {}
            data.setdefault("history", []).append(
                {"t": int(time.time()), "op": "select"})
            _events_save_marker(body.get("run_id"), set_id)
        if "name" in body and str(body["name"]).strip():
            data["name"] = str(body["name"])[:120]
        if "draft_md" in body:
            val = str(body.get("draft_md") or "")[:200000]
            data.setdefault("history", []).append(
                {"t": int(time.time()),
                 "op": "draft-override" if val else "draft-reset"})
            if val:
                data["draft_md"] = val
            else:
                data.pop("draft_md", None)
        _save_set(set_id, data, p)
        return jsonify({"ok": True, "set_id": set_id})

    @app.route("/api/sets/<set_id>/add-run", methods=["POST"])
    def api_sets_add_run(set_id):
        data, p = _load_set(set_id)
        if data is None:
            return jsonify({"ok": False, "error": "no such set"}), 404
        body = request.get_json(silent=True) or {}
        cpath = _curation_path_for_run(str(body.get("run_id") or ""))
        if not cpath:
            return jsonify({"ok": False, "error": "run has no curation record"}), 404
        ids = [r.get("run_id") for r in (data.get("runs") or [])]
        if body.get("run_id") in ids:
            return jsonify({"ok": True, "set_id": set_id, "added": False})
        data.setdefault("runs", []).append(
            {"run_id": str(body.get("run_id") or ""), "curation_path": str(cpath)})
        if body.get("query"):
            data.setdefault("queries", []).append(str(body["query"])[:300])
        data.setdefault("history", []).append({"t": int(time.time()), "op": "add-run"})
        _save_set(set_id, data, p)
        return jsonify({"ok": True, "set_id": set_id, "added": True})

    @app.route("/api/sets/<set_id>/compose", methods=["POST"])
    def api_sets_compose(set_id):
        data, p = _load_set(set_id)
        if data is None:
            return jsonify({"ok": False, "error": "no such set"}), 404
        pages, image_candidates, namespaces = [], [], {}
        for r in (data.get("runs") or []):
            cp = _realpath(r.get("curation_path") or "")
            if not cp.is_file():
                continue
            try:
                cur = json.loads(cp.read_text())
            except (OSError, ValueError):
                continue
            pages += cur.get("pages") or []
            image_candidates += cur.get("image_candidates") or []
            namespaces[str(r.get("run_id") or "")] = cur.get("pages") or []
        md, chosen_paras = _compose_markdown(
            data, {"pages": pages,
                   "image_candidates": image_candidates,
                   "namespaces": namespaces})
        data.setdefault("history", []).append(
            {"t": int(time.time()), "op": "compose", "paragraphs": chosen_paras})
        _save_set(set_id, data, p)
        override = _draft_override(data)
        return jsonify({"ok": True, "set_id": set_id,
                        "paragraphs_used": chosen_paras,
                        "markdown": override if override is not None else md,
                        "draft_override": override is not None})

    @app.route("/api/sets/<set_id>/export.md")
    def api_sets_export(set_id):
        data, p = _load_set(set_id)
        if data is None:
            return jsonify({"ok": False, "error": "no such set"}), 404
        pages, image_candidates, namespaces = [], [], {}
        for r in (data.get("runs") or []):
            cp = _realpath(r.get("curation_path") or "")
            if not cp.is_file():
                continue
            try:
                cur = json.loads(cp.read_text())
            except (OSError, ValueError):
                continue
            pages += cur.get("pages") or []
            image_candidates += cur.get("image_candidates") or []
            namespaces[str(r.get("run_id") or "")] = cur.get("pages") or []
        md, _ = _compose_markdown(
            data, {"pages": pages,
                   "image_candidates": image_candidates,
                   "namespaces": namespaces})
        override = _draft_override(data)
        if override is not None:
            md = override
        return Response(md.encode("utf-8"),
                        mimetype="text/markdown; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    @app.route("/api/guide/<name>")
    def api_guide(name):
        safe = Path(name).name
        if not safe.startswith("MASTER-GUIDE-") or not safe.endswith(".md"):
            return jsonify({"error": "not a guide"}), 404
        for day in sorted(GUIDE_ROOT.iterdir(), reverse=True):
            candidate = day / safe
            if candidate.is_file():
                return Response(candidate.read_text(errors="replace"),
                                mimetype="text/markdown",
                                headers={"Cache-Control": "no-store"})
        return jsonify({"error": "guide not found"}), 404