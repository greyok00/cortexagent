#!/usr/bin/env python3
"""kbserver_patch.py — extends knowledge-ingestor MCP with:
  1. kb_ingest_text   (local text/markdown ingest — guides, solved incidents)
  2. kb_learn_topic   (THE AUTO-LEARN LOOP: greysearch deep run on a topic,
                       quality-gates every page, ingests what passes)
Design rules honored:
  - uses kbcore content_route + add_records (same dedup/hash/embed path as every other lane)
  - every learned record carries provenance (source url / guide path / why it qualified)
  - quality gate BEFORE ingest (docs-only policy): official domains, doc paths,
    real content density; junk never enters the library
  - no silent trust: results report exactly what was admitted/rejected and why
"""
import json, os, sys, re, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbcore
import jobs as jobs_mod
import extractors as _ex

# ── quality gate: "docs and dependable info, not junk" ────────────────────
DOC_DOMAINS = re.compile(
    r"(^|\.)(developer\.android\.com|docs\.(gradle|python|llvm|kernel)\.org|"
    r"developer\.mozilla\.org|learn\.microsoft\.com|docs\.oracle\.com|"
    r"readthedocs\.io|docs\.rs|man7\.org|wiki\.archlinux\.org|"
    r"redis\.io|sqlite\.org|openjdk\.java\.net|docs\.docker\.com|"
    r"sqlite|golang\.org|pkg\.go\.dev|github\.com|git-scm\.com|nginx\.org|"
    r"postgresql\.org|docs\.python\.org|peps\.python\.org|wiki\.debian\.org|"
    r"help\.ubuntu\.com|wiki\.gentoo\.org|kubernetes\.io|reactjs\.org|"
    r"vuejs\.org|angular\.io|nodejs\.org|deno\.com|bun\.sh|swift\.org|rust-lang\.org"
    r")$", re.I)
DOC_PATHSIG = re.compile(
    r"(/docs?(/|$)|/reference(/|$)|/guide|/manual|/api|/library|/apidoc|"
    r"/command|/cli|/tools/|/sdk|/develop|/build|/install|/configuration|"
    r"/peps/|/tutorials?|/howto|/javadoc|/reference/)", re.I)
JUNK_PATHSIG = re.compile(
    r"(/forum|/forums|/thread|/posts?/|/questions?/|/discussion|/comments?|"
    r"/news|/blog(?!/)|/coupon|/deal|/shopping|/review-|/top-10|/best-|-vs-|"
    r"/download|/setup\.exe|/release/download|/register|/login|/signup|/subscribe)", re.I)
JUNK_SIGS = re.compile(
    r"(sign in to continue|subscribe now|cookie consent|enable javascript|"
    r"buy now|limited offer|download the app|install our app|your download will begin)", re.I)

def _domain_quality(url: str, text: str) -> tuple[bool, str, str]:
    """(admit, verdict, provenance) — deterministic, explainable, no model."""
    host = ""
    m = re.match(r"https?://([^/]+)", url or "")
    if m: host = m.group(1).lower()
    if not host:
        return True, "local/guide", "provenance=local-guide"
    score = 0
    prov = [f"host={host}"]
    if DOC_DOMAINS.search(host.rstrip(".") + "$") or DOC_DOMAINS.search(host):
        score += 3; prov.append("official-domain+3")
    if DOC_PATHSIG.search(url or ""):
        score += 2; prov.append("doc-path+2")
    if re.search(r"guide|reference|manual|docs", (url or ""), re.I):
        score += 1
    if JUNK_PATHSIG.search(url or ""):
        score -= 2; prov.append("junk-path-2")
    # stackoverflow CANONICAL questions are exempt from the forum penalty when
    # they carry an accepted answer (dev references live there in practice)
    if host.endswith("stackoverflow.com") and re.search(r"/questions?/\d+/", url or "") \
            and len((text or "")) > 800:
        if not JUNK_SIGS.search((text or "")[:4000]):
            score += 4; prov.append("so-canonical+4 (junk-path exempted)")
    # UGC feeds: never, regardless of size
    if re.search(r"(reddit|medium\.com|dev\.to|quora)\.", host):
        score -= 3; prov.append("ugc-3")
    # content density on the extracted text
    words = len((text or "").split())
    if words > 400: score += 2; prov.append(f"density+2 ({words}w)")
    elif words > 150: score += 1; prov.append(f"density+1 ({words}w)")
    elif words < 60:
        score -= 2; prov.append(f"thin-{words}w-2")
    hits = JUNK_SIGS.findall((text or "")[:4000])
    if len(hits) >= 3:
        score -= 3; prov.append(f"junk-sigs{n}-3")
    # github README/docs blobs are official-adjacent; raw issues are not
    if "github.com" in host:
        if re.search(r"/(blob|raw)/|README", url or "", re.I): score += 2; prov.append("github-doc+2")
        if re.search(r"/issues?/|/pull/|/discussions", url or ""): score -= 3; prov.append("github-issue-3")
    verdict = ";".join(prov)
    return (score >= 3), f"score={score}", verdict

def _records_from_text(text: str, title: str, url: str, src: str, meta=None):
    """Route any text through kbcore's official chunk/records path."""
    base = {"t": title, "u": url, "s": (meta or {}).get("site") if isinstance(meta, dict) else (src or ""),
            "src": (meta or {}).get("site") if isinstance(meta, dict) else (src or "librar")}
    if meta:
        base["prov"] = meta if isinstance(meta, str) else json.dumps(meta)[:300]
    recs = kbcore.records_from(text, base)
    return recs

def quality_report(db, url, text) -> dict:
    ok, verdict, provenance = _domain_quality(url, text)
    return {"url": url, "admit": ok, "verdict": verdict, "provenance": provenance}

# ── greysearch bridge (same-process import; no subprocess MCP hop) ─────────
# greysearch checkout, same resolution the suite-wide env knob uses
GSPATH = os.path.expanduser(
    os.environ.get("CORTEXAGENT_GREYSEARCH_MCP", os.path.join("~", "greysearch")))
def _gs():
    """Import the greysearch MCP module from its checkout, or fail honestly."""
    if not os.path.isfile(os.path.join(GSPATH, "greysearch_mcp.py")):
        raise RuntimeError(
            f"greysearch checkout not found at {GSPATH} - kb_learn_topic needs it; "
            "clone the greysearch repo or set CORTEXAGENT_GREYSEARCH_MCP")
    if GSPATH not in sys.path: sys.path.insert(0, GSPATH)
    import greysearch_mcp
    return greysearch_mcp

def _extract_guide_sections(md: str):
    """Split a Master Guide into (section_title, text) chunks for targeted ingest."""
    parts = re.split(r"\n(?=#{1,3} )", md)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) < 200: continue
        ttl = p.split("\n", 1)[0].lstrip("# ").strip()[:120] or "section"
        out.append((ttl, p))
    return out or [("full", md[:12000])]

def tool_kb_ingest_text(a: dict) -> dict:
    """Local text/markdown with provenance. No fetch, no gate (trusted-source)."""
    db = a.get("db"); text = a.get("text") or ""
    title = a.get("title") or "untitled"
    src = a.get("source") or "local"
    url = a.get("url") or f"local://{src}"
    if not db or len(text.strip()) < 80:
        return {"error": "need db + meaningful text (>=80 chars)"}
    path = kbcore.db_dir(db)
    if not os.path.isfile(f"{path}/pack.jsonl"):
        return {"error": f"no such db: {db}"}
    enc = jobs_mod.enc_factory()
    recs = _records_from_text(text, title, url, src, a.get("provenance"))
    added = kbcore.add_records(path, recs, enc, src="local-ingest")
    return {"db": db, "title": title, "records_made": len(recs), "added": len(added),
            "duplicates": max(0, len(recs) - len(added)),
            "note": "ingested verbatim (trusted-source lane, no auto-gate)"}

def tool_kb_learn_topic(a: dict) -> dict:
    """THE LOOP: greysearch researches → gate → ingest what passes → report."""
    db = a.get("db"); topic = a.get("topic") or a.get("query") or ""
    tier = a.get("tier", "standard")
    pinned = a.get("pinned_sources") or []
    max_results = int(a.get("max_results", 8))
    if not db or not topic.strip():
        return {"error": "need db + topic"}
    path = kbcore.db_dir(db)
    if not os.path.isfile(f"{path}/pack.jsonl"):
        return {"error": f"no such db: {db}"}
    try:
        gs = _gs()
    except RuntimeError as e:
        return {"error": str(e)}
    # synchronous deep run — budget is HARD (the caller asked for learning NOW);
    # brief tier keeps interactive loops snappy (3 pages, ~3 min wall)
    tier = a.get("tier", "standard")
    tier_pages = {"brief": 3, "standard": max_results, "deep": max_results, "report": max_results}
    budget = float(a.get("max_seconds", 240 if tier == "brief" else 380))
    result = gs._execute_deep(
        topic, categories=a.get("categories") or ["it", "science"],
        max_results=min(max_results, tier_pages.get(tier, max_results)),
        budget=budget, pinned=pinned or None)
    pages = result.get("pages") or result.get("pages_fetched") or []
    admitted, rejected = [], []
    enc = jobs_mod.enc_factory()
    total = dups = 0
    guide_path = result.get("guide_path") or result.get("guide") or ""
    # 1) per-page ingest — multi-extractor funnel (trafilatura→selectolax→grab)
    #    + robots politeness gate + code/table side-harvest + feed discovery
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        url = pg.get("url") or ""
        title = pg.get("title") or url
        raw_html = pg.get("html") or pg.get("raw_html") or ""
        text = pg.get("text") or pg.get("content") or ""
        ext_used = "scrape-doms"
        code_recs = []
        # robots.txt politeness (skip disallowed paths entirely)
        rob_ok, rob_why = _ex.robots_ok(url)
        if not rob_ok:
            rejected.append({"url": url, "why": rob_why}); continue
        # if scrape gave no text but HTML is present → run the funnel
        if len(text) < 400 and len(raw_html) > 800:
            pr = _ex.process(url, raw_html)
            text = pr["text"] or text
            ext_used = pr["extractor"]
            if pr["code"]:
                code_recs = [(f"code: {title[:60]} #{i+1}", c) for i, c in enumerate(pr["code"])]
        if len(text) < 400:
            rejected.append({"url": url, "why": "thin content"}); continue
        ok, verdict, provenance = _domain_quality(url, text)
        if not ok:
            rejected.append({"url": url, "why": verdict}); continue
        recs = _records_from_text(text, title, url, "greysearch-learn", provenance)
        # code blocks → separate focused records (same url provenance)
        for ct, cb in code_recs[:12]:
            recs += _records_from_text(cb, ct, url + "#code", "greysearch-learn-code", "code block, " + provenance)
        added = kbcore.add_records(path, recs, enc, src="auto-learn")
        total += len(added); dups += max(0, len(recs) - len(added))
        admitted.append({"url": url, "records": len(recs), "added": len(added),
                         "prov": provenance, "extractor": ext_used})
    # 2) Master Guide ingest (the synthesized, highest-value artifact)
    guide_added = 0
    if guide_path and os.path.isfile(guide_path):
        md = open(guide_path, errors="ignore").read()
        if len(md) > 600:
            for ttl, section in _extract_guide_sections(md):
                recs = _records_from_text(
                    section, ttl, f"guide://{os.path.basename(guide_path)}#{ttl[:40]}",
                    "greysearch-guide", f"master guide section, topic='{topic[:90]}'")
                added = kbcore.add_records(path, recs, enc, src="auto-learn-guide")
                guide_added += len(added)
    return {"db": db, "topic": topic, "greysearch_run": {"run_id": result.get("run_id"),
            "pages": len(pages), "guide": guide_path},
            "admitted": admitted, "rejected": rejected,
            "records_added": total, "guide_sections_added": guide_added,
            "duplicates": dups,
            "note": "funnel: robots-gate → trafilatura/selectolax text + code harvest; every rejection reported"}
