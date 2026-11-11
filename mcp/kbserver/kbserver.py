#!/usr/bin/env python3
import json, sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbcore

SERVER = {"name": "knowledge-ingestor", "version": "0.2.0"}
PROTO = "2024-11-05"
import jobs as jobs_mod

def p(path):
    return kbcore.db_dir(path) if len(path) < 60 and not os.sep in path else path

def tool_status(a):
    return {"dbs": kbcore.dbs(), "model": os.path.basename(kbcore.MODEL),
            "model_state": jobs_mod.model_state(),
            "model_required_for": "embedding only: ingest, keyword search and resume work without it"}

def tool_search(a):
    path = p(a["db"])
    k = int(a.get("k", 5))
    e = jobs_mod.enc_factory()
    results = kbcore.search(path, a["query"], k, e)
    if not results:
        out = {"query": a["query"], "hits": 0, "note": "no match — not covered by this database; escalate, do not guess"}
        if e is None:
            out["band_context"] = "model off: lexical terms only this call"
        return out
    lines = []
    for r in results:
        tag = r["band"]
        lines.append(f"{r['i']} [{tag} {r['cos']}] | {r['t'][:90]} | {r['d']} | {r['src']}")
        lines.append(f"    {r['u']}")
        x = re.sub(r"\s+", " ", r["x"])
        lines.append(f"    {x[:700]}{' …' if len(x) > 700 else ''}")
        lines.append("")
    return {"query": a["query"], "hits": len(results), "text": "\n".join(lines),
            "results": [{k2: r[k2] for k2 in ("i", "t", "d", "u", "cos", "band")} for r in results]}

def tool_get(a):
    path = p(a["db"])
    want = set(a["ids"] if isinstance(a["ids"], list) else [a["ids"]])
    out = [r for r in kbcore.pack_rows(path) if r.get("i") in want]
    if not out:
        raise ValueError("no such record id in this db")
    return out

def _run_inline(path, j, db_label):
    jid = j["jobid"]
    if not jobs_mod.try_claim(path, jid):
        return {"db": db_label, "jobid": jid, "state": "queued",
                "note": "another worker holds this db; the journal resumes it"}
    try:
        state = jobs_mod.run_job(path, j)
    finally:
        jobs_mod.unclaim(path, jid)
    st = j.get("stats", {})
    return {"db": db_label, "jobid": jid, "state": state,
            "added": st.get("added", 0), "dups": st.get("dups", 0),
            "parked": st.get("parked", 0), "pending_embed": j.get("pending_embed", 0),
            "skipped": [{"target": it["target"], "why": it["why"]}
                        for it in j.get("items", []) if it.get("status") == "parked"]}

def tool_ingest_urls(a):
    path = p(a["db"])
    kbcore.init_db(path)
    urls = [u.strip() for u in (a.get("urls") or []) if u.strip().startswith("http")]
    lim = int(a.get("limit", 12))
    urls = urls[:lim]
    if not urls:
        return {"db": a["db"], "added": 0, "note": "no http urls in input"}
    meta = {"d": a.get("domain", "general"), "f": "mcp", "t": a.get("title", "")}
    jobs_mod.reconcile(path, autostart=False)
    j = jobs_mod.create_job(path, [("url", u, meta) for u in urls],
                            note=f"mcp urls:{a.get('domain', '')}")
    return _run_inline(path, j, a["db"])

def tool_ingest_pdf(a):
    path = p(a["db"])
    kbcore.init_db(path)
    srcs = []
    for f in (a.get("paths") or []):
        f = os.path.expanduser(f)
        if os.path.isdir(f):
            srcs += [os.path.join(f, x) for x in sorted(os.listdir(f)) if x.lower().endswith(".pdf")]
        elif f.lower().endswith(".pdf"):
            srcs.append(f)
    srcs = srcs[: int(a.get("limit", 20))]
    if not srcs:
        return {"db": a["db"], "added": 0, "note": "no pdf paths in input"}
    meta = {"d": a.get("domain", "document"), "f": "mcp", "t": a.get("title", "")}
    jobs_mod.reconcile(path, autostart=False)
    j = jobs_mod.create_job(path, [("pdf", s, meta) for s in srcs],
                            note=f"mcp pdfs:{a.get('domain', '')}")
    return _run_inline(path, j, a["db"])

def tool_rebuild(a):
    path = p(a["db"])
    e = jobs_mod.enc_factory()
    if e is None:
        return {"db": a["db"], "error": "embedding model unavailable; db remains keyword-searchable; rebuild runs when the model returns"}
    n = kbcore.rebuild(path, e)
    return {"db": a["db"], "records": n}

def tool_jobs(a):
    return {"db": a["db"], "jobs": jobs_mod.jobs_view(p(a["db"]))}




def tool_delete(a):
    path = p(a["db"])
    import shutil
    if int(a.get("confirm", 0)) == 1:
        shutil.rmtree(path, ignore_errors=True)
        return {"deleted": a["db"]}
    return {"note": "no deletion: pass confirm=1 or use the web UI trash button"}

TOOLS = [
    ("kb_status", "List knowledge-base databases and index stats.", {"type": "object", "properties": {}, "required": []}),
    ("kb_search", "Semantic+keyword search of an offline knowledge base. Returns records with id, url and confidence band (firm=may cite; soft=verify; soft results can be token-adjacent misses). Empty means not covered: escalate, never guess.",
     {"type": "object", "properties": {"db": {"type": "string", "description": "database name"}, "query": {"type": "string"}, "k": {"type": "integer", "default": 5}}, "required": ["db", "query"]}),
    ("kb_get", "Full text of specific record ids from a db.", {"type": "object", "properties": {"db": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}}, "required": ["db", "ids"]}),
    ("kb_ingest_urls", "Fetch web pages (politely, 3s apart), extract text, chunk, embed and APPEND to a db. Offline use thereafter.",
     {"type": "object", "properties": {"db": {"type": "string"}, "urls": {"type": "array", "items": {"type": "string"}}, "domain": {"type": "string", "description": "topic tag"}, "limit": {"type": "integer", "default": 12}}, "required": ["db", "urls"]}),
    ("kb_ingest_pdf", "Extract text from local PDF paths or a directory, strip repeated headers/footers, chunk, embed, append.",
     {"type": "object", "properties": {"db": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}, "description": "pdf files or dirs (uploaded files land in <db>/uploads)"}, "domain": {"type": "string"}, "limit": {"type": "integer", "default": 20}}, "required": ["db", "paths"]}),
    ("kb_rebuild", "Re-embed the whole db (use after mass edits). Needs the embedding model; without it the db stays keyword-searchable.", {"type": "object", "properties": {"db": {"type": "string"}}, "required": ["db"]}),
    ("kb_delete", "Delete a db (needs confirm=1).", {"type": "object", "properties": {"db": {"type": "string"}, "confirm": {"type": "integer"}}, "required": ["db", "confirm"]}),
    ("kb_jobs", "Job journal for a db: ingest history with states, parked items and reasons, duplicates, pending embeds.", {"type": "object", "properties": {"db": {"type": "string"}}, "required": ["db"]}),
]

# ── auto-learn bridge (2026-11-08): quality-gated greysearch→RAG pipeline ──
import kbserver_patch as _auto

def tool_kb_ingest_text_w(a):
    return _auto.tool_kb_ingest_text(a or {})

def tool_kb_learn_topic_w(a):
    return _auto.tool_kb_learn_topic(a or {})

_OLD_TOOLS = TOOLS
TOOLS = _OLD_TOOLS + [
    ("kb_ingest_text", "Ingest local text/markdown VERBATIM into a db (owner-curated lane: no auto-gate). Provenance recorded (source, url). Use for solved-incident notes, command references, master guides you trust.",
     {"type": "object", "properties": {"db": {"type": "string"}, "text": {"type": "string"},
       "title": {"type": "string"}, "source": {"type": "string", "description": "where this text came from"},
       "url": {"type": "string"}, "provenance": {"type": "string"}}, "required": ["db", "text", "title"]}),
    ("kb_learn_topic", "FIRE-AND-FORGET like greysearch: run greysearch deep research on a topic in a background worker, quality-gate every page (official docs domains, doc paths, content density; junk/forums/shops REJECTED and reported), ingest admitted pages section-by-section PLUS the Master Guide, all with per-record provenance. Returns run_id at once; watch kb_learn_status; do not re-fire the db while running.",
     {"type": "object", "properties": {"db": {"type": "string"}, "topic": {"type": "string"},
       "tier": {"type": "string", "enum": ["brief", "standard", "deep", "report"], "default": "standard"},
       "max_results": {"type": "integer", "default": 8},
       "max_seconds": {"type": "number", "default": 420},
       "background": {"type": "boolean", "default": True, "description": "false = legacy synchronous run (blocks until finished)"},
       "pinned_sources": {"type": "array", "items": {"type": "string"}},
       "categories": {"type": "array", "items": {"type": "string"}}}, "required": ["db", "topic"]}),
    ("kb_learn_status", "ONE status call for kb_learn_topic runs: running / done / failed, records added, pages, guide path, admitted/rejected and why. Call it after firing a learn; do not poll in a tight loop and do not re-fire while a db has a running learn.",
     {"type": "object", "properties": {"db": {"type": "string", "description": "filter runs by db (optional)"}}}),
]

def dispatch(name, a):
    return {
        "kb_status": tool_status, "kb_search": tool_search, "kb_get": tool_get,
        "kb_ingest_urls": tool_ingest_urls, "kb_ingest_pdf": tool_ingest_pdf,
        "kb_rebuild": tool_rebuild, "kb_delete": tool_delete, "kb_jobs": tool_jobs,
        "kb_ingest_text": tool_kb_ingest_text_w, "kb_learn_topic": tool_kb_learn_topic_w,
        "kb_learn_status": _auto.tool_kb_learn_status,
    }[name](a or {})

TOOLS_DEF = [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]  # includes auto-learn bridge

def respond(w, id, res=None, err=None):
    if id is None:
        return
    out = {"jsonrpc": "2.0", "id": id, "result": res} if err is None else {"jsonrpc": "2.0", "id": id, "error": err}
    w.write(json.dumps(out, ensure_ascii=False) + "\n")
    w.flush()

def main():
    w = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("jsonrpc") != "2.0":
            continue
        m, id = msg.get("method", ""), msg.get("id")
        if m == "initialize":
            respond(w, id, {"protocolVersion": PROTO, "capabilities": {"tools": {}}, "serverInfo": SERVER})
        elif m.startswith("notifications/"):
            continue
        elif m == "ping":
            respond(w, id, {})
        elif m == "tools/list":
            respond(w, id, {"tools": TOOLS_DEF})
        elif m == "tools/call":
            n = (msg.get("params") or {}).get("name")
            a = (msg.get("params") or {}).get("arguments", {})
            try:
                r = dispatch(n, a)
                respond(w, id, {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}], "isError": False})
            except Exception as e:
                respond(w, id, {"content": [{"type": "text", "text": f"error: {type(e).__name__}: {e}"}], "isError": True})
        elif m in ("shutdown", "exit"):
            return
        elif id is not None:
            respond(w, id, err={"code": -32601, "message": f"method not found: {m}"})

if __name__ == "__main__":
    main()