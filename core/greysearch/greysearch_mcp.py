#!/usr/bin/env python3
"""
greysearch — the one web researcher MCP server.

Exposes exactly two tools:

- greysearch          the researcher: deep search + scrape + Master Guide by
                      default (background-task behaviour: the call returns
                      run_id + guide path immediately, the run continues in a
                      thread, greysearch_health reports the finished digest);
                      one-URL scrape via url=; ranked search-only via
                      scrape_all=false. Every deep run is auto-assigned a
                      conflict-free browser task slot; a slot another live
                      session owns is never taken.
- greysearch_health   diagnostics + background-run status/digests + slot map.

Removed tool names (greyscrape, greysearch_engines, research_search,
research_scrape, research_deep, research_sites, research_task_registry) are
NOT listed in TOOLS any more; calling one returns a dict naming the exact
greysearch(...) call to use instead, so stale habits self-heal on the first
try instead of looping.

The search lane ladder is automatic inside one call: local SearXNG (:8888)
first, then searx.space public instances, then direct keyless lanes.
Scraping always runs through the ONE browser assigned to this session's
task slot; owners' standing rules live in the memory dir, never here.

MCP name: greysearch
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

_BANNED_SEARCH_MARKERS = (
    "chatgpt.com", "api.openai.com", "openai.azure.com", ":13200",
    "g4f", "tavily", "serper", "brave-search", "brave_search",
    "api.firecrawl.dev", "firecrawl-mcp",
)

def _guard_search_lane() -> None:
    """Refuse to start if a banned search endpoint is reachable in env/config.

    Checks env vars for banned endpoints. The greysearch MCP itself never
    calls these — this is a tripwire so a future edit or env var that
    re-introduces a banned lane crashes at import."""
    for var in ("FIRECRAWL_API_KEY", "TAVILY_API_KEY",
                "SERPER_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY",
                "GREYSEARCH_URL", "SEARXNG_URL"):
        val = (os.environ.get(var) or "").lower()
        if not val:
            continue
        for marker in _BANNED_SEARCH_MARKERS:
            if marker in val:
                raise RuntimeError(
                    f"greysearch AUDIT GUARD: banned search endpoint in "
                    f"{var}={val!r} (marker {marker!r}). greysearch is the "
                    f"ONLY researcher; OpenAI/g4f/ChatGPT and paid lanes "
                    f"(Tavily/Serper/Brave/Firecrawl) are forbidden by the "
                    f"standing bans recorded in the memory dir.")

_guard_search_lane()

import research_integration as research_bridge
from research_integration import (
    get_bridge, research_scrape, research_search, research_deep)
from searxng_integrated import SearXNGEngineManager
try:
    import keys as research_keys
except Exception:
    research_keys = None

import pipeline_sites as pipeline

DEFAULT_MAX_RESULTS = 10
_LINKS_PER_PAGE_IN_RESPONSE = 150
_THIN_FILL_LIMIT = 5
_THIN_FILL_BUDGET_S = 90.0
_RUNS_KEEP = 25
_GUIDE_PREVIEW = 1600

_DEEP_LOCK = threading.Lock()
_RUN_GUARD = threading.Lock()
_RUNS: Dict[str, dict] = {}

_BROWSER_EXEC = ThreadPoolExecutor(max_workers=1,
                                   thread_name_prefix="greysearch-browser")

def _redacted(obj):
    if research_keys is None:
        return obj
    try:
        return json.loads(research_keys.redact(json.dumps(obj, default=str)))
    except Exception:
        return obj

_REMOVED = {
    "greyscrape":             "greysearch(url=..., keep_raw_html=...)",
    "research_deep":          "greysearch(query=..., background=...)  [deep IS the default — do NOT call the removed name again]",
    "research_search":        "greysearch(query=..., scrape_all=false)",
    "research_scrape":        "greysearch(url=...)",
    "research_sites":         "no tool — site tiers live in research/data/sites.json in this repo",
    "research_task_registry": "greysearch(query=...) — slot assignment is automatic; pass task_id only to pin a specific slot",
    "greysearch_engines":     "greysearch_health()  [engine stats are in the searxng section]",
}

TOOLS = [
    {
        "name": "greysearch",
        "description": (
            "THE ONE WEB RESEARCHER. Default flow = deep search + scrape + "
            "Master Guide, fired like a background task: call it ONCE "
            "(background=true default) and it returns immediately with run_id "
            "and the guide path; greysearch_health then reports the finished "
            "digest (pages, findings, guide path, warned lanes); you read the "
            "guide file when done. Do not re-call greysearch with tweaked "
            "arguments while health shows a run active — that is the retry "
            "loop this design exists to kill. The search lane ladder is "
            "automatic inside one call: local SearXNG (:8888) first, then "
            "searx.space public instances, then direct keyless lanes. Long "
            "questions are decomposed into separate short keyword searches "
            "(one per entity; connective words stripped) — never long-tail "
            "queries. Full pages are scraped headless through patchright on "
            "the session's own browser slot (tables/headings/links/images/"
            "videos/code all captured, paragraph structure preserved). Thin "
            "runs auto-fill from public instances and report exactly what "
            "failed or was skipped — they never pretend to be complete. "
            "Provide url INSTEAD of query to scrape ONE known page "
            "synchronously and fast. scrape_all=false = ranked search "
            "results only (no scraping, no guide)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Research question. Required unless url is given."},
                "url": {"type": "string",
                        "description": "Scrape ONE page instead of researching (sync, fast; full payload with media/tables/code)."},
                "scrape_all": {"type": "boolean",
                               "description": "true (default) = full deep run with scraping + Master Guide; false = search-only, ranked sources"},
                "max_results": {"type": "integer",
                                "description": "Max pages scraped in a deep run (default 10, hard max 25)"},
                "categories": {"type": "array", "items": {"type": "string"},
                               "description": "Optional SearXNG categories (news/it/science/…; unknown ones are normalized to general)"},
                "write_guide_to": {"type": "string",
                                   "description": "Override the Master Guide output path (.md file or dir)"},
                "keep_raw_html": {"type": "boolean",
                                  "description": "Include raw page HTML in the response (default false)"},
                "max_seconds": {"type": "number",
                                "description": "Wall-clock budget for the whole deep run (default 300)"},
                "tier": {"type": "string", "enum": ["brief", "standard", "deep", "report"],
                         "description": "Run tier — brief 3/240s, standard 4/300s, deep 6/420s, report 8/540s (pages/seconds). Explicit max_results/max_seconds always win."},
                "background": {"type": "boolean",
                               "description": "true (DEFAULT) = fire like a task: return run_id now, digest arrives via greysearch_health; false = synchronous full run in this call (blocks until finished)"},
                "task_id": {"type": "string",
                            "description": "Optional 'task-N' (any number) or bare 'N': pin a browser lane; a number not in the map creates a new lane with its own port and profile. Omitted = AUTO-ASSIGN a conflict-free lane (a brand-new lane is spawned when all lanes are busy): slots owned by another live session are never taken."},
                "pinned_sources": {"type": "array", "items": {"type": "string"},
                                   "description": "Exact primary-domain URLs fetched FIRST (ranked ahead of search); each contributes its top same-site topical links to the pool. Use when general search drifts off-topic."},
            },
            "required": [],
        },
    },
    {
        "name": "greysearch_health",
        "description": (
            "ONE status call for greysearch: SearXNG engine/lane stats, "
            "searx.space instances, browser-slot map (which session owns "
            "which port), AND the digest list for every background greysearch "
            "run (running / done / failed, pages, findings, guide path). "
            "Call this after a background greysearch to learn its outcome — "
            "do not poll in a tight loop, and do not re-call greysearch "
            "while a run is active."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

def _unique_derived_target(target: Path) -> Path:
    """A rerun of the same query on the same day derives the same slug and,
    before the 2026-11-03 fix, stamped straight over the earlier run's guide,
    run-report and curation record — its research became unreadable through
    every path (registry, ledger, saved sets). Derived targets only: a free
    path passes through; a taken one gets -2, -3, … instead of a clobber."""
    if not target.exists():
        return target
    for n in range(2, 1000):
        cand = target.with_name(f"{target.stem}-{n}{target.suffix}")
        if not cand.exists():
            return cand
    return target.with_name(
        f"{target.stem}-{int(time.time())}{target.suffix}")

def _guide_output_path(query: str, slug_tag: str = "") -> Path:
    """Master Guide destination: GREYSEARCH_OUT_DIR env (file or dir) >
    RESEARCH_PAGES env when it is an existing dir >
    <repo>/guides/<UTC-date>/MASTER-GUIDE-<slug>.md (repo dir = this file's dir).
    slug_tag (pass-3 fix) appends the run tier so tier runs never overwrite
    each other's guide; derived names never clobber an existing file."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in query.lower())[:60].strip("-") or "guide"
    if slug_tag:
        slug = f"{slug}-{slug_tag}"[:80]
    out = os.environ.get("GREYSEARCH_OUT_DIR", "")
    if not out:
        pages_env = os.environ.get("RESEARCH_PAGES", "")
        if pages_env and Path(pages_env).is_dir():
            out = pages_env
    if out:
        b = Path(out)
        if b.suffix == ".md":
            b.parent.mkdir(parents=True, exist_ok=True)
            return b
        b.mkdir(parents=True, exist_ok=True)
        return _unique_derived_target(b / f"MASTER-GUIDE-{slug}.md")
    day_dir = Path(__file__).resolve().parent / "guides" / \
        f"{datetime.now(timezone.utc):%Y-%m-%d}"
    return _unique_derived_target(day_dir / f"MASTER-GUIDE-{slug}.md")

def _resolve_guide_path(spec, query: str, slug_tag: str = "") -> Path:
    """write_guide_to must NEVER land as a bare directory — a 2026-10-18 run
    lost a complete deep run to IsADirectoryError at publish time. Resolve:
    existing dir, or missing .md suffix  ->  <dir>/MASTER-GUIDE-<slug>.md
    (same convention as _guide_output_path); a real .md file passes through.
    slug_tag (pass-3 fix): run tier ("brief"/"standard"/...) appended to the
    slug so tier reruns of the same query keep each tier's guide on disk,
    and derived names never clobber an existing file (dir-spec branch)."""
    if not spec:
        return _guide_output_path(query, slug_tag)
    b = Path(str(spec))
    slug = "".join(ch if ch.isalnum() else "-" for ch in query.lower())[:60].strip("-") or "guide"
    if slug_tag:
        slug = f"{slug}-{slug_tag}"[:80]
    if b.is_dir() or b.suffix != ".md":
        b.mkdir(parents=True, exist_ok=True)
        return _unique_derived_target(b / f"MASTER-GUIDE-{slug}.md")
    b.parent.mkdir(parents=True, exist_ok=True)
    return b

def _thin_fill(query: str, result: dict) -> None:
    """AUTOMATIC SEARX.SPACE FILL, REBUILT 2026-10-19 with the
    relevance gate: when the deep run came back thin, ladder-search searx.space
    directly and scrape what it finds — but the fill lane is held to the SAME
    standard as the main lane:

      1. every ladder result passes the deterministic pre-filter BEFORE any
         scrape (no unranked raw results are ever fetched);
      2. every scraped page is cleaned (page_clean) and semantically judged
         (relevance.judge_pages) BEFORE it may join pages_fetched;
      3. only ACCEPTED pages join the corpus. Quarantined/rejected fill pages
         are counted and reported with reasons;
      4. thresholds are never lowered to hit a page-count target — a fill
         that survives with too few pages is reported as a thin run.

    Every outcome — success or failure — is recorded, never swallowed."""
    import page_clean as _page_clean
    import relevance as _relevance

    fill = {"triggered": True, "searched": False, "scraped": 0, "urls": [],
            "accepted": 0, "quarantined": 0, "rejected": 0,
            "rejected_detail": [], "errors": []}
    try:
        import searx_fallback as _sf
        _fill_engines = None
        try:
            from searxng_integrated import _split_selection as _sps
            _fill_engines = _sps(result.get("engines") or [])["text"]
        except Exception:
            _fill_engines = None
        lad = _sf.search(query, max_results=10, engines=_fill_engines)
        fill["searched"] = True
        if not (lad.get("ok") and lad.get("results")):
            fill["errors"].append(f"ladder search: {lad.get('source', 'no results')}")
        else:
            fill["ladder_source"] = lad.get("source")
            have = {p["url"] for p in result.get("pages_fetched", [])}
            fresh = [r for r in lad["results"] if r.get("url") not in have]
            bridge = get_bridge()
            deadline = time.time() + _THIN_FILL_BUDGET_S
            gated: list = []
            for r in fresh:
                dom = r.get("domain") or bridge._extract_domain(r.get("url", ""))
                pf = _relevance.prefilter(
                    r.get("url", ""), title=r.get("title", ""),
                    snippet=r.get("content", "") or r.get("snippet", ""),
                    domain=dom, tier=r.get("tier") or bridge._get_tier(dom),
                    question=query)
                if pf["decision"] == "reject":
                    fill["rejected"] += 1
                    fill["rejected_detail"].append(
                        {"url": r.get("url", ""), "reason": pf["reason"]})
                    continue
                r = dict(r)
                r["prefilter"] = pf
                gated.append(r)
            fill["prefilter_kept"] = len(gated)
            candidates: list = []
            for r in gated[:_THIN_FILL_LIMIT]:
                if time.time() > deadline:
                    fill["errors"].append("fill scrape budget reached")
                    break
                sr = bridge.research_scrape(r["url"])
                if not sr.get("ok"):
                    fill["errors"].append(
                        f"scrape {r['url'][:80]}: {str(sr.get('error'))[:120]}")
                    fill["rejected"] += 1
                    fill["rejected_detail"].append(
                        {"url": r["url"], "reason": "scrape failed"})
                    continue
                sr = dict(sr)
                sr["title"] = r.get("title") or sr.get("title", "")
                sr["tier"] = r.get("tier") or sr.get("tier", "unlisted")
                cleaned = _page_clean.clean_page(sr)
                if _page_clean.is_thin(cleaned):
                    fill["rejected"] += 1
                    fill["rejected_detail"].append(
                        {"url": r["url"],
                         "reason": f"thin_content ({cleaned.get('main_chars', 0)} chars)"})
                    continue
                sr["clean"] = cleaned
                candidates.append(sr)
                fill["scraped"] += 1
            if candidates and _relevance.judge_available():
                decisions = _relevance.judge_pages(
                    query,
                    [research_bridge._judge_view(sr) for sr in candidates])
                for sr, d in zip(candidates, decisions):
                    sr["relevance"] = d
            elif candidates:
                for sr in candidates:
                    sr["relevance"] = {
                        "decision": "quarantine", "relevance_score": 50,
                        "source_type": _relevance.classify_source_type(
                            sr.get("domain", ""), sr.get("tier", ""),
                            sr.get("title", "")),
                        "reason": "judge_unavailable — quarantined, never auto-accepted",
                        "allowed_content": [], "risk_flags": []}
            for sr in candidates:
                rel = sr.get("relevance") or {}
                if rel.get("decision") == "accept":
                    result.setdefault("pages_fetched", []).append(sr)
                    result.setdefault("sources", []).append(sr["url"])
                    fill["urls"].append(sr["url"])
                    fill["accepted"] += 1
                elif rel.get("decision") == "quarantine":
                    fill["quarantined"] += 1
                    fill["rejected_detail"].append(
                        {"url": sr["url"], "decision": "quarantine",
                         "reason": rel.get("reason", "")})
                    result.setdefault("fill_curation_surplus", []).append(sr)
                else:
                    fill["rejected"] += 1
                    fill["rejected_detail"].append(
                        {"url": sr["url"], "decision": "reject",
                         "reason": rel.get("reason", "")})
                    result.setdefault("fill_curation_surplus", []).append(sr)
            if fill["accepted"] == 0 and gated:
                fill["errors"].append(
                    "fill lane produced 0 accepted pages — thin run reported "
                    "honestly, thresholds not lowered")
    except Exception as e:
        fill["errors"].append(f"{type(e).__name__}: {str(e)[:160]}")
    result["fill_lane"] = fill

def _shape_response(result: dict, keep_raw: bool) -> dict:
    """Response discipline: full text + all tables/images/headings/code are
    KEPT (that is the research depth); raw_text and html are dropped (they
    tripled payload size with nothing new); links trimmed to nav-sane caps."""
    shaped = {k: v for k, v in result.items() if k != "pages_fetched"}
    pages = []
    for p in result.get("pages_fetched", []):
        sp = dict(p)
        if not keep_raw:
            sp.pop("raw_text", None)
        sp.pop("html", None)
        links = sp.get("links") or []
        if len(links) > _LINKS_PER_PAGE_IN_RESPONSE:
            sp["links"] = links[:_LINKS_PER_PAGE_IN_RESPONSE]
            sp["links_capped_at"] = _LINKS_PER_PAGE_IN_RESPONSE
        pages.append(sp)
    shaped["pages_fetched"] = pages
    warnings = list(shaped.get("warnings") or [])
    for p in pages:
        if p.get("html_capped"):
            warnings.append(f"html capped for {p.get('url')}")
        flags = p.get("injection_flags") or []
        if flags:
            warnings.append(f"{len(flags)} injection-pattern flag(s) on {p.get('url')}")
    shaped["warnings"] = warnings
    rr = result.get("run_report")
    if isinstance(rr, dict):
        shaped["relevance_summary"] = {
            "candidate_count": rr.get("candidate_count"),
            "scraped_count": rr.get("scraped_count"),
            "accepted_count": rr.get("accepted_count"),
            "quarantined_count": rr.get("quarantined_count"),
            "rejected_count": rr.get("rejected_count"),
            "accepted_sources": rr.get("accepted_sources", [])[:50],
            "quality_warnings": rr.get("quality_warnings", []),
        }
        shaped["skipped_pages_summary"] = {
            "count": len(rr.get("skipped_pages") or []),
            "sample": (rr.get("skipped_pages") or [])[:20],
        }
    qp = result.get("quarantined_pages")
    if qp:
        shaped["quarantined_pages"] = qp[:50]
    return shaped

def _set_run(run_id: str, **fields) -> None:
    with _RUN_GUARD:
        d = _RUNS.setdefault(run_id, {})
        d.update(fields)
        if len(_RUNS) > _RUNS_KEEP:
            old = sorted(_RUNS, key=lambda k: _RUNS[k].get("started_ts", 0))[:-_RUNS_KEEP]
            for rid in old:
                _RUNS.pop(rid, None)
        try:
            _runs_dir = Path(__file__).resolve().parent / "runs"
            _runs_dir.mkdir(exist_ok=True)
            (_runs_dir / f"{run_id}.json").write_text(
                json.dumps(d, default=str), encoding="utf-8")
        except Exception:
            pass

def _busy_response(what: str) -> dict:
    with _RUN_GUARD:
        running = {rid: {k: d.get(k) for k in ("query", "started_at", "status")}
                   for rid, d in _RUNS.items() if d.get("status") == "running"}
    return {"ok": False, "busy": True, "waiting_for": what, "active_runs": running,
            "note": "one deep run at a time (the private browser is reused per process). "
                    "Ask greysearch_health for the active run's digest; do not re-call greysearch."}

def _refresh_run_report(result: dict) -> None:
    """Re-derive the run report from the merged corpus.

    research_deep writes the run report before the fill lane runs, so a thin
    run that the fill lane rescues ended up with a persisted report saying
    '0 accepted' while the guide said '4 accepted source(s)'. The report is
    the machine-readable record, so it is recomputed here after the merge
    instead of being left inconsistent with its own guide.
    """
    rr = result.get("run_report")
    if not isinstance(rr, dict):
        return
    acc = [p for p in (result.get("pages_fetched") or []) if isinstance(p, dict)]
    urls = [p["url"] for p in acc if p.get("url")]
    rr["accepted_count"] = len(acc)
    rr["accepted_sources"] = urls
    rr["scraped_count"] = max(int(rr.get("scraped_count") or 0), len(acc))
    accepted = set(urls)
    skipped = [s for s in (rr.get("skipped_pages") or [])
               if not (isinstance(s, dict) and s.get("url") in accepted)]
    rr["skipped_pages"] = skipped
    funnel = set(accepted)
    funnel.update(s.get("url") for s in skipped
                  if isinstance(s, dict) and s.get("url"))
    rr["candidate_count"] = len(funnel)
    warnings = [w for w in (rr.get("quality_warnings") or [])
                if not str(w).startswith("thin run:")]
    if len(acc) < 3:
        warnings.append(
            f"thin run: only {len(acc)} accepted page(s) — the guide "
            "reports DATA NOT CAPTURED rather than padding")
    rr["quality_warnings"] = warnings

def _execute_deep(query: str, categories: Optional[List[str]],
                  max_results: int, budget: float, pinned=None) -> dict:
    result = research_deep(query, categories=categories, max_pages=max_results,
                           max_total_seconds=budget,
                           pinned_sources=list(pinned or []))
    if len(result.get("pages_fetched", [])) < 3:
        _thin_fill(query, result)
        fill = result.get("fill_lane") or {}
        result["ladder_lane"] = (str(fill.get("ladder_source") or "")
                                 if isinstance(fill.get("ladder_source", ""), str) else "")
        _refresh_run_report(result)
    return result

_CORPUS_GLOBS = (
    str(Path(__file__).resolve().parent / "guides" / "**" / "*.md"),

)

def _corpus_related(query: str, guide_path: Path, top: int = 6) -> str:
    """OUR RESEARCH: every published guide ends with a machine-selected
    'Related research in our corpus' section ranking our existing work by
    filename/heading token overlap. LINKS ONLY — content is never blended
    into the new guide, so there is no poisoning path."""
    import glob as _g
    tokens = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 3}
    if not tokens:
        return ""
    cands = []
    seen = set()
    for pat in _CORPUS_GLOBS:
        for f in _g.glob(pat):
            fp = str(f)
            if fp == str(guide_path) or fp in seen:
                continue
            seen.add(fp)
            try:
                st = os.stat(fp)
                if st.st_size < 800:
                    continue
                hay = Path(fp).name.lower()
                with open(fp, errors="ignore") as fh:
                    for ln in fh.readlines()[:25]:
                        if ln.startswith("#"):
                            hay += " " + ln.lstrip("# ").strip().lower()
                            break
                n = sum(1 for t in tokens if t in hay)
                if n:
                    cands.append((n, st.st_mtime, st.st_size, fp))
            except Exception:
                continue
    cands.sort(reverse=True)
    clean = []
    for n, mtime, size, fp in cands[:20]:
        try:
            with open(fp, errors="ignore") as fh:
                markers = fh.read().count("DATA NOT CAPTURED")
        except Exception:
            markers = 0
        if markers <= 8:
            clean.append((n, mtime, size, fp))
        if len(clean) >= top:
            break
    cands = clean
    if not cands:
        return ""
    lines = ["---", "", "## Related research in our corpus",
             "Machine-selected by filename/heading match with this run's "
             "question — links only; verify before trusting.", ""]
    for n, mtime, size, fp in cands[:top]:
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        lines.append(f"- `{Path(fp).name}` ({size:,} bytes, {ts}) — {fp}")
    text = "\n".join(lines) + "\n"
    try:
        with open(guide_path, "a", errors="ignore") as fh:
            fh.write("\n" + text)
        return text
    except Exception:
        return ""

_CURATION_STOP = frozenset(
    "a about after all also an and any are as at be because been before being but by can could did "
    "do does doing done down during each even for from further had has have having he her here hers "
    "him his how if in into is it its just like may me more most my no nor not now of off on once "
    "one only or other our out over per should so some such than that the their them then there "
    "these they this those through to too two under until up use used using very was we were what "
    "when where which while who whom why will with within without would you your com www html http "
    "https".split())

def _split_paragraphs(body_text, para_cap=0, char_cap=400000):
    """Split a page's body_text into paragraphs. Structure is preserved by
    page_clean (blank-line separated); single-newline listings fall back
    line-per-entry. UNcapped by default (2026-11-03, owner decision "full
    capture": the old 40-paragraph cap threw away most of a long page's
    record); para_cap > 0 restores the old cap, and char_cap bounds the
    total captured text. Each individual paragraph keeps its 4000-char clip
    (one runaway paragraph cannot dominate a record). Honest either way:
    truncated=true when anything was cut."""
    text = str(body_text or "")
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p and p.strip()]
    if not paras:
        paras = [l.strip() for l in text.splitlines() if l and l.strip()]
    out, used, truncated = [], 0, False
    for p in paras:
        if (para_cap and len(out) >= para_cap) or used >= char_cap:
            truncated = True
            break
        out.append(p[:4000])
        used += len(p)
    return out, truncated

def _page_keywords(body_text, title, n=12):
    counts = {}
    for tok in re.split(r"[^a-z0-9#+./]+", (str(title or "") + " " + str(body_text or "")).lower()):
        tok = tok.strip("._/")
        if len(tok) > 3 and tok not in _CURATION_STOP and not tok.isdigit():
            counts[tok] = counts.get(tok, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]

def _curation_page(p, page_id: str) -> dict:
    """One judged page's curation record: verdict plus the extraction the run
    saw (paragraphs, keywords, images, headings). Ids are stable keys into
    THIS file only: <page_id>#p<N> and <page_id>#img<N>."""
    clean = p.get("clean") or {}
    rel = p.get("relevance") or {}
    body = clean.get("body_text") or p.get("text") or ""
    paras, truncated = _split_paragraphs(body, 0, 400000)
    imgs = []
    gate = None
    try:
        import relevance as _rel
        gate = getattr(_rel, "gate_image", None)
    except Exception:
        gate = None
    for im in (clean.get("images") or p.get("images") or [])[:40]:
        if isinstance(im, dict):
            src = str(im.get("src") or im.get("url") or "")[:500]
            attrs = {"src": src,
                     "title": str(im.get("title") or im.get("alt") or "")[:160]}
        else:
            src = str(im)[:500]
            attrs = {"src": src, "title": ""}
        mark = None
        reason = ""
        if callable(gate) and src:
            try:
                verdict = gate({**im, "src": src} if isinstance(im, dict)
                               else {"src": src})
                if isinstance(verdict, dict):
                    mark = not bool(verdict.get("keep"))
                    reason = str(verdict.get("reason") or "")[:120]
                else:
                    mark = not bool(verdict)
            except Exception:
                mark = None
        attrs["gated"] = mark
        if reason:
            attrs["gate_reason"] = reason
        if src:
            imgs.append(attrs)
    return {
        "id": page_id,
        "url": str(p.get("url") or "")[:500],
        "final_url": str(clean.get("final_url") or p.get("url") or "")[:500],
        "title": str(p.get("title") or clean.get("title") or "")[:200],
        "domain": str(p.get("domain") or "")[:120],
        "tier": str(p.get("tier") or "")[:40],
        "decision": str(rel.get("decision") or p.get("decision") or "")[:20],
        "reason": str(rel.get("reason") or p.get("reason") or "")[:240],
        "relevance_score": rel.get("relevance_score"),
        "source_type": rel.get("source_type"),
        "risk_flags": rel.get("risk_flags") or [],
        "chars": int(clean.get("main_chars") or p.get("chars") or 0),
        "paragraphs": [{"id": f"{page_id}#p{i}", "text": t}
                       for i, t in enumerate(paras)],
        "paragraphs_truncated": truncated,
        "keywords": _page_keywords(body, p.get("title") or clean.get("title")),
        "headings": [str(h)[:160] for h in (clean.get("h2s") or p.get("headings") or [])[:20]],
        "images": imgs,
    }

_MAX_RECORD_BYTES = 4_000_000

def _curation_counts(records: list, unscraped: list = None) -> dict:
    """Counts block of a curation payload. Shared by _write_curation and the
    portal's second-wave append so both recompute the same shape."""
    recs = [r for r in (records or []) if isinstance(r, dict)]
    un = [u for u in (unscraped or []) if isinstance(u, dict)]
    return {
        "pages": len(recs),
        "accepted": sum(1 for r in recs if r.get("decision") == "accept"),
        "quarantined": sum(1 for r in recs if r.get("decision") == "quarantine"),
        "rejected": sum(1 for r in recs if r.get("decision") == "reject"),
        "unscraped_candidates": len(un),
    }

def _shrink_curation_to_cap(payload: dict) -> int:
    """Honest record-size shrink for one curation payload: drop the LAST
    page record until the serialized record fits _MAX_RECORD_BYTES; when a
    single page's paragraphs alone would not fit, halve that page's
    paragraph tail repeatedly. Returns the number of dropped pages. The
    caller writes truncated=true plus a note on the payload."""
    if not isinstance(payload.get("pages"), list):
        return 0
    dropped = 0
    while payload["pages"] and len(json.dumps(payload, default=str).encode()) > _MAX_RECORD_BYTES:
        if len(payload["pages"]) > 1:
            payload["pages"].pop()
            dropped += 1
            continue
        last = payload["pages"][0]
        paras = last.get("paragraphs") or []
        if len(paras) <= 1:
            break
        last["paragraphs"] = paras[:len(paras) // 2]
        last["paragraphs_truncated"] = True
    return dropped

def _write_curation(result: dict, query: str, write_path: Path) -> Optional[Path]:
    """Write <guide>.curation.json: every page the run actually READ, with its
    verdicts and extraction (paragraphs/keywords/images), so the portal can
    show and curate the research instead of discarding it. Additive — the auto
    guide and run-report are untouched. Unscraped candidates are listed as
    urls only (nothing but their search snippet ever existed).

    2026-11-03: paragraphs are captured UNCAPPED (owner decision) with the
    honest truncated flags; the whole record is bound by a 4 MB serialized
    guard that shrinks tail pages first and says exactly what it cut. The
    searches record echoes the run's selected engines (empty = default
    lanes) so the curation view can show what was searched."""
    pages = list(result.get("all_scraped_pages") or [])
    pages += [s for s in (result.get("fill_curation_surplus") or [])]
    seen, records = set(), []
    for p in pages:
        if not isinstance(p, dict):
            continue
        u = p.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        records.append(_curation_page(p, f"pg{len(records)}"))
    if not records:
        return None
    try:
        from photos import keyword_ladder
        q_kw = [str(k)[:60] for k in (keyword_ladder(query) or [])][:10]
    except Exception:
        q_kw = []
    rr = result.get("run_report") or {}
    scraped_urls = {r["url"] for r in records}
    unscraped = [
        {"url": s.get("url", ""), "decision": s.get("decision", ""),
         "reason": (s.get("reason") or "")[:240]}
        for s in (rr.get("skipped_pages") or [])
        if isinstance(s, dict) and s.get("url") and s.get("url") not in scraped_urls
    ][:200]
    payload = {
        "query": query,
        "query_keywords": q_kw,
        "counts": _curation_counts(records, unscraped),
        "pages": records,
        "unscraped_candidates": unscraped,
        "image_candidates": list(result.get("image_candidates") or []),
        "searches": [
            {"category": s.get("category"), "query": s.get("query"),
             "ok": s.get("ok"), "n": s.get("n"),
             "engines": (s.get("engines") if isinstance(s.get("engines"), list)
                         else [])}
            for s in (result.get("searches") or []) if isinstance(s, dict)
        ],
    }
    cpath = write_path.with_suffix(write_path.suffix + ".curation.json")
    cpath.parent.mkdir(parents=True, exist_ok=True)
    if len(json.dumps(payload, default=str).encode()) > _MAX_RECORD_BYTES:
        dropped = _shrink_curation_to_cap(payload)
        payload["truncated"] = True
        payload["truncation"] = (
            f"record-size guard 4 MB: dropped {dropped} tail page(s) "
            "from the curation record")
        payload["counts"] = _curation_counts(payload["pages"],
                                             payload["unscraped_candidates"])
    cpath.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return cpath

def _attach_guide(result: dict, query: str, write_path: Path) -> dict:
    output_spec = None
    try:
        import llm_audit as _la
        # W-4 provenance: the mode that WILL run for composition, named
        # before anything is attempted. The kill switch always wins: with
        # GREYSEARCH_NO_MODEL set the lane stays rules-only even when the
        # audit gate itself is opted in.
        if _la.audit_allowed() and not _la.no_model():
            _policy = "llm-fallback (opted in)"
        else:
            _policy = "rules (default)"
        _mode_reason = (
            "rules mode (model lane off by policy: GREYSEARCH_NO_MODEL)"
            if (_la.audit_allowed() and _la.no_model())
            else "audit gate closed (set GREYSEARCH_ALLOW_LLM_AUDIT=1 to opt in)"
            if not _la.audit_allowed()
            else "opted in")
    except Exception as _le:
        _la = None
        _policy = "rules (default)"
        _mode_reason = f"model-lane probe failed: {str(_le)[:120]}"
    result["llm_audit"] = {"used": False, "policy": _policy,
                           "reason": _mode_reason}
    try:
        from dossier import build_dossier
        doss = build_dossier(result, query)
        result["dossier"] = doss
        if _la is not None and _la.audit_allowed() and not _la.no_model() \
                and _la.endpoint_ok():
            output_spec = _la.spec_for_compose(query, doss)
            if output_spec:
                result["llm_audit"] = {"used": True,
                                       "policy": _policy,
                                       "model": output_spec.get("model"),
                                       "dossier_chars": doss and len(doss)}
            else:
                result["llm_audit"] = {"used": False,
                                       "policy": _policy,
                                       "reason": "audit unparsable/insufficient"}
        else:
            if _la is None:
                result["llm_audit"] = {"used": False, "policy": _policy,
                                       "reason": _mode_reason}
            elif not _la.audit_allowed():
                result["llm_audit"] = {"used": False, "policy": _policy,
                                       "reason": _mode_reason}
            elif _la.no_model():
                result["llm_audit"] = {"used": False, "policy": _policy,
                                       "reason": _mode_reason}
            else:
                result["llm_audit"] = {"used": False, "policy": _policy,
                                       "reason": ("endpoint down "
                                                  "(deterministic path)")}
    except Exception as _ae:
        result["llm_audit"] = {"used": False, "policy": _policy,
                               "reason": f"stage error: {str(_ae)[:120]}"}

    try:
        from greysearch_publisher import publish_from_greysearch
        md = publish_from_greysearch(
            title=f"Master Guide — {query[:100]}",
            executive_brief=None,
            greysearch_result=result,
            write_to=str(write_path),
            output_spec=output_spec)
        result["master_guide"] = {
            "path": str(write_path),
            "chars": len(md),
            "written": write_path.exists(),
            "preview": md[:_GUIDE_PREVIEW],
        }
    except Exception as pe:
        result.setdefault("warnings", []).append(f"publisher failed: {str(pe)[:200]}")

    rr = result.get("run_report")
    if isinstance(rr, dict):
        try:
            report_path = write_path.with_suffix(write_path.suffix + ".run-report.json")
            report_path.write_text(json.dumps(rr, indent=2, default=str),
                                   encoding="utf-8")
            result["run_report_path"] = str(report_path)
        except Exception as re_:
            result.setdefault("warnings", []).append(
                f"run report write failed: {str(re_)[:140]}")

    try:
        cp = _write_curation(result, query, write_path)
        if cp:
            result["curation_path"] = str(cp)
    except Exception as ce:
        result.setdefault("warnings", []).append(
            f"curation write failed: {str(ce)[:140]}")

    if result.get("master_guide", {}).get("written"):
        try:
            _corpus_related(query, write_path)
            result["master_guide"]["corpus_related_added"] = True
        except Exception as ce:
            result.setdefault("warnings", []).append(
                f"corpus-related failed: {str(ce)[:140]}")

    try:
        builder = Path(__file__).with_name("greysearch_site_builder.py")
        if result.get("master_guide", {}).get("written") and builder.exists():
            site_out = write_path.with_name(write_path.stem + "_site")
            pr = subprocess.run([sys.executable, str(builder), str(write_path),
                                 "-o", str(site_out), "--max-images", "40"],
                                capture_output=True, text=True, timeout=150)
            result["site"] = {"path": str(site_out),
                              "pages": len(list(site_out.glob("*.html"))),
                              "built": (site_out / "index.html").exists(),
                              "engine_tail": (pr.stdout or "").strip()[-200:]}
            try:
                import json as _json
                _guard = _json.loads((site_out / "guardrails.json").read_text())
                result["site"]["guardrails"] = _guard
                if not _guard.get("ok"):
                    result["site"]["built"] = False
                    result.setdefault("warnings", []).append(
                        "site guardrails FAILED: "
                        + ", ".join(k for k, c in _guard["checks"].items()
                                    if not c["pass"]))
            except Exception:
                pass
            if pr.returncode != 0:
                result.setdefault("warnings", []).append(
                    f"site builder rc={pr.returncode}: {(pr.stderr or '')[-160:]}")
    except Exception as se:
        result.setdefault("warnings", []).append(f"site build failed (isolated): {str(se)[:160]}")
    return result

def _guarded_url_scrape(url: str):
    if not _DEEP_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "another run holds the browser", "url": url}
    try:
        return research_scrape(url, max_chars=0)
    finally:
        _DEEP_LOCK.release()

def _inline_deep(query: str, categories, max_results: int, budget: float,
                 write_path: Path, slot_note: str, pinned=None):
    """background=false deep run, still on the dispatcher thread."""
    if not _DEEP_LOCK.acquire(blocking=False):
        return {"busy": True}
    try:
        result = _execute_deep(query, categories, max_results, budget, pinned=pinned)
    finally:
        _DEEP_LOCK.release()
    return _attach_guide(result, query, write_path)

_TASK_RE = re.compile(r"^(?:task-)?([1-9][0-9]{0,3})$", re.IGNORECASE)

def _slot_candidates() -> List[str]:
    """Free-slot preference order taken straight from the slot maps
    (task-3 first, then every slot sorted by number). The map is the
    truth: nothing is hardcoded, and lanes spawned at runtime appear
    here the moment they are registered."""
    import browser_ports as _bports
    ids = _bports.slot_ids()
    head = ["task-3"] if "task-3" in ids else []
    return head + [t for t in ids if t != "task-3"]

def _cdp_answers(port: int) -> bool:
    """True when a CDP endpoint answers on 127.0.0.1:<port> (1.5s timeout)."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False

def _slot_reg_entry(tid: str) -> dict:
    try:
        reg = pipeline.task_registry()
        return (reg or {}).get(tid) or {}
    except Exception:
        return {}

def _reap_orphan_browser(tid: str, port: int) -> bool:
    """Kill a dead-session slot browser. Scoped: only processes whose cmdline
    carries THIS slot's profile dir or this slot's port. Never touches another
    slot or another session's browser. True when the port stops answering."""
    pids: set = set()
    profile_dir = os.path.join(str(Path.home()), ".cache", "greysearch",
                               f"{tid}-profile")
    for pattern in (profile_dir, f"remote-debugging-port={port}"):
        try:
            r = subprocess.run(["pgrep", "-f", pattern],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.split("\n"):
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
        except Exception:
            pass
    pids.discard(os.getpid())
    if not pids:
        return not _cdp_answers(port)
    for pid in sorted(pids, reverse=True):
        try:
            os.kill(pid, 15)
        except Exception:
            continue
    time.sleep(1.0)
    survivors = []
    for pid in sorted(pids, reverse=True):
        try:
            os.kill(pid, 0)
            survivors.append(pid)
        except Exception:
            pass
    for pid in survivors:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
    time.sleep(0.5)
    return not _cdp_answers(port)


def _slot_busy_reason(tid: str, port: int) -> str:
    """Why this slot is NOT free, or '' when it is. Two conflict signals, per
    the standing behavior: a live registry owner session that is not us, and
    an answering CDP port with no live registered owner (a foreign browser
    nobody registered — never touch, never steal)."""
    entry = _slot_reg_entry(tid)
    pid = entry.get("pid")
    if isinstance(pid, int) and pid > 0 and pid != os.getpid():
        try:
            os.kill(pid, 0)
            return (f"slot {tid} :{port} owned by live session "
                    f"{entry.get('owner_session') or 'unknown'} (pid {pid})")
        except ProcessLookupError:
            pass
        except PermissionError:
            return (f"slot {tid} :{port} owned by live session "
                    f"{entry.get('owner_session') or 'unknown'} (pid {pid})")
    if not entry and _cdp_answers(port):
        return f"a browser is already running on {tid} port {port} (unregistered)"
    if entry and _cdp_answers(port):
        if not _reap_orphan_browser(tid, port):
            return (f"a browser is still answering on {tid} port {port} "
                    f"after an orphan-reap attempt (registered owner is dead)")
    return ""

def _slot_registry_lock_path() -> str:
    """Companion lockfile for the slot registry, next to the registry the
    pipeline keeps. The registry write is a read-modify-write with no lock
    of its own, so two sessions racing _bind_slot could both pass the
    busy-check and claim the same slot; taking this lock around check plus
    assign makes the pair atomic between processes."""
    try:
        base = str(pipeline._TASK_REG_PATH)
    except Exception:
        base = os.path.join(os.path.expanduser("~/.cache/greysearch"),
                            "task-registry.json")
    return base + ".lock"


def _sweep_stale_slots() -> list:
    """Dead-owner sweep (W-9): a registry claim whose owning pid is dead
    AND whose lane port has no live browser lies about lane occupancy —
    it keeps a free lane looking busy forever (the busy check only trusts
    live pids, but re-registration used to overwrite a stale entry while
    the pre-W-9 silent-claim defect let duplicates ride). Dropped from the
    registry under the write lock before the binder's free-slot scan; a
    claim with a live pid or a live browser stays (the busy path reaps
    orphan browsers itself)."""
    swept: list = []
    try:
        reg = dict(pipeline.task_registry() or {})
    except Exception:
        return swept
    import browser_ports as _bports
    for tk, entry in list(reg.items()):
        if not str(tk).startswith("task-"):
            continue
        pid = (entry or {}).get("pid")
        alive = False
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive:
            continue
        try:
            port = int(_bports.resolve(task=tk).get("port") or 0)
        except Exception:
            port = 0
        try:
            alive_cdp = bool(_cdp_answers(port))
        except Exception:
            alive_cdp = False
        if alive_cdp:
            continue
        try:
            pipeline.task_registry(forget=tk)
            swept.append(tk)
        except Exception as _fs:
            print("greysearch: stale slot forget failed for %s: %s"
                  % (tk, str(_fs)[:120]), flush=True)
    if swept:
        print("greysearch: swept %d stale slot claim(s): %s"
              % (len(swept), ", ".join(swept)), flush=True)
    return swept


def _bind_slot(task_id: str = "") -> tuple:
    """Bind this run to a browser task slot. task_id empty = AUTO-ASSIGN:
    prefer task-3, then free map slots by number, and — when every lane is
    busy — spawn a brand-new lane (task-(max+1), own port, own profile,
    registered in the shared slot map) so search volume never queues on a
    slot cap. An explicit task_id may also name a number the map does not
    have yet: that lane is created on demand the same way. Slots owned by
    another live session are never taken; an unregistered browser holding
    a port also blocks that slot. Writes the slot registry and sets
    RESEARCH_TASK so CDP-side resolvers pick the slot's own port. The busy
    check, the map registration and the registry write happen under a
    cross-process lock; the pass also sweeps dead-owner claims (dead pid +
    no live browser = dropped) so a freed lane is findable again. A claim
    write that fails aborts the bind loudly (ValueError): no persisted
    claim, no lane handout — returning an unregistered slot would lie to
    the next session. Raises ValueError for an explicit lane that is
    genuinely busy (never stolen, never substituted), a bad task number,
    or an unwritable claim."""
    import fcntl
    import browser_ports as _bports
    want = ""
    if task_id:
        mt = _TASK_RE.match(str(task_id).strip())
        if not mt:
            raise ValueError(
                f"bad task_id {task_id!r}: use a task number like 'task-3' "
                "(or '3'); unknown numbers are created as new lanes")
        want = f"task-{mt.group(1)}"
        try:
            have = _bports.slot_ids()
        except Exception:
            have = []
        candidates = [want] if want in have else []
        spawn_wanted = want not in have
    else:
        candidates = _slot_candidates()
        spawn_wanted = True
    lockp = _slot_registry_lock_path()
    os.makedirs(os.path.dirname(lockp), exist_ok=True)
    with open(lockp, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            _sweep_stale_slots()
            conflicts = []
            for tid in candidates:
                port = int(_bports.resolve(task=tid)["port"])
                reason = _slot_busy_reason(tid, port)
                if reason:
                    conflicts.append(reason)
                    if task_id:
                        break
                    continue
                try:
                    pipeline.task_registry(assign=tid, task_id=tid)
                except Exception as _tr:
                    # the claim MUST persist: a silent write failure lies to
                    # the next session about the slot, so refuse the handout
                    raise ValueError(
                        f"the slot claim for {tid} could not be written to "
                        "the task registry; refusing to hand out a lane the "
                        "next session cannot see ("
                        + str(_tr)[:160] + ")") from _tr
                os.environ["RESEARCH_TASK"] = tid
                note = (f"task slot assigned: {tid} (port {port}, "
                        "registry written)")
                if len(candidates) > 1:
                    taken = list(conflicts)
                    note += (f"; skipped: {'; '.join(taken)}" if taken else
                             "; no other live greysearch sessions")
                return tid, note
            if not spawn_wanted:
                raise ValueError("no free browser slot: "
                                 + "; ".join(conflicts))
            # every lane is busy (or the requested number is brand-new):
            # spawn a new lane instead of failing the run on volume
            entry = _bports.bind_new_slot(
                int(want.split("-")[1]) if want else None)
            tid = str(entry["key"])
            port = int(entry["port"])
            try:
                pipeline.task_registry(assign=tid, task_id=tid)
            except Exception as _tr:
                # same rule as the free-slot claim: no persisted claim, no
                # lane handout
                raise ValueError(
                    f"the slot claim for {tid} could not be written to "
                    "the task registry; refusing to hand out a lane the "
                    "next session cannot see ("
                    + str(_tr)[:160] + ")") from _tr
            os.environ["RESEARCH_TASK"] = tid
            note = (f"new browser lane spawned: {tid} (port {port}"
                    f"{'' if want else ', all lanes busy'}, registry written)")
            return tid, note
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)

def _slot_map() -> Dict[str, dict]:
    """Slot map for health: per-slot port, CDP-alive, registry owner."""
    import browser_ports as _bports
    reg = {}
    try:
        reg = pipeline.task_registry() or {}
    except Exception:
        pass
    out: Dict[str, dict] = {}
    for tid in _slot_candidates():
        try:
            port = int(_bports.resolve(task=tid)["port"])
        except Exception:
            continue
        entry = reg.get(tid) or {}
        pid = entry.get("pid")
        owner_alive = False
        if isinstance(pid, int) and pid > 0 and pid != os.getpid():
            try:
                os.kill(pid, 0)
                owner_alive = True
            except OSError:
                owner_alive = False
        out[tid] = {
            "port": port,
            "cdp_alive": _cdp_answers(port),
            "owner_session": entry.get("owner_session", ""),
            "owner_pid": pid if isinstance(pid, int) else None,
            "owner_alive": owner_alive,
        }
    return out

def _deep_worker(run_id: str, query: str, categories: Optional[List[str]],
                 max_results: int, budget: float, write_path: Path,
                 slot_note: str, pinned=None) -> None:
    started = time.time()
    if not _DEEP_LOCK.acquire(blocking=True, timeout=2.0):
        _set_run(run_id, status="failed",
                 error="could not take the browser within 2s — another run holds it",
                 elapsed_s=round(time.time() - started, 1))
        return
    try:
        _watch = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deepwatch")
        _sub = _watch.submit(_execute_deep, query, categories, max_results, budget, pinned)
        try:
            result = _sub.result(timeout=float(budget) + 240.0)
        except _FutTimeout:
            try:
                _m = _TASK_RE.search(str(slot_note))
                if _m:
                    _rt = f"task-{_m.group(1)}"
                    import browser_ports as _bp
                    _rp = int(_bp.resolve(task=_rt)["port"])
                    _reap_orphan_browser(_rt, _rp)
            except Exception:
                pass
            try:
                _watch.shutdown(wait=False)
            except Exception:
                pass
            _set_run(run_id, status="failed",
                     error="watchdog: deep run over budget +240s (lane wedged); "
                           "slot browser reaped; the leaked worker thread exits "
                           "with the process",
                     elapsed_s=round(time.time() - started, 1))
            return
        finally:
            _watch.shutdown(wait=False)
        result = _attach_guide(result, query, write_path)
        guide = result.get("master_guide") or {}
        fill = result.get("fill_lane") or {}
        rr = result.get("run_report") or {}
        _set_run(run_id, status="done",
                 elapsed_s=round(time.time() - started, 1),
                 pages_ok=len(result.get("pages_fetched", [])),
                 pages_skipped=len(result.get("skipped_pages", [])),
                 findings=len(result.get("findings", [])),
                 sources=len(result.get("sources", [])),
                 fill_lane={"triggered": bool(fill.get("triggered")),
                            "scraped": fill.get("scraped", 0),
                            "accepted": fill.get("accepted", 0),
                            "quarantined": fill.get("quarantined", 0),
                            "rejected": fill.get("rejected", 0)},
                 relevance={"accepted": rr.get("accepted_count", 0),
                            "quarantined": rr.get("quarantined_count", 0),
                            "rejected": rr.get("rejected_count", 0),
                            "candidate_count": rr.get("candidate_count", 0),
                            "judge_ran": result.get("judge_ran", False)},
                 run_report_path=result.get("run_report_path"),
                 master_guide={"path": str(write_path),
                               "chars": guide.get("chars"),
                               "written": guide.get("written")},
                 preview=(guide.get("preview") or "")[:_GUIDE_PREVIEW],
                 site=result.get("site", {}),
                 skip_sample=[str((s.get("reason") if isinstance(s, dict) else s) or "")[:120]
                              for s in (rr.get("skipped_pages")
                                        or result.get("skipped_pages") or [])[:5]],
                 warnings_tail=[str(w)[:160] for w in (result.get("warnings") or [])[-6:]],
                 slot=slot_note)
    except Exception as e:
        _set_run(run_id, status="failed",
                 error=f"{type(e).__name__}: {str(e)[:300]}",
                 elapsed_s=round(time.time() - started, 1))
    finally:
        _DEEP_LOCK.release()

def dispatch(name: str, args: dict) -> dict:
    if name in _REMOVED:
        return {"ok": False, "removed": True, "tool": name,
                "use_instead": _REMOVED[name],
                "note": "Renamed tools: greysearch + greysearch_health are the "
                        "only surfaces. This is a rename hint, not something "
                        "to retry."}

    if name in ("greysearch",):
        url = str(args.get("url") or "").strip()
        query = str(args.get("query") or "").strip()
        keep_raw = bool(args.get("keep_raw_html", False))

        if url:
            try:
                _tid, _note = _bind_slot(str(args.get("task_id") or ""))
            except ValueError as be:
                return {"ok": False, "busy": True, "error": str(be),
                        "browser_slots": _slot_map()}
            if _DEEP_LOCK.locked():
                return _busy_response("one-URL scrape needs the private browser")
            fut = _BROWSER_EXEC.submit(_guarded_url_scrape, url)
            try:
                r = fut.result(timeout=180)
            except _FutTimeout:
                return _busy_response("one-URL scrape waited >180s behind an active run")
            if isinstance(r, dict) and not keep_raw:
                r.pop("html", None)
            return _redacted(r)

        if not query:
            return {"ok": False,
                    "error": "provide query (research question) or url (single-page scrape)"}

        max_results = max(1, min(int(args.get("max_results", DEFAULT_MAX_RESULTS)), 25))
        categories = args.get("categories")
        pinned = args.get("pinned_sources") or []
        if pinned and not isinstance(pinned, list):
            pinned = [pinned]
        scrape_all = bool(args.get("scrape_all", True))

        if not scrape_all:
            _engines_raw = args.get("engines")
            if _engines_raw and not isinstance(_engines_raw, list):
                _engines_raw = [_engines_raw]
            _engines_clean = [str(x).strip() for x in (_engines_raw or [])
                              if str(x).strip()] or None
            r = research_search(query, category=categories[0] if categories else "general",
                                max_results=max_results, engines=_engines_clean)
            return _redacted({"mode": "search-only (scrape_all=false)", **r})

        write_path = _resolve_guide_path(args.get("write_guide_to"), query)
        try:
            tid, slot_note = _bind_slot(str(args.get("task_id") or ""))
        except ValueError as be:
            return {"ok": False, "busy": True, "error": str(be),
                    "browser_slots": _slot_map()}

        budget = float(args.get("max_seconds", 300.0))
        _TIER = str(args.get("tier") or "").strip().lower()
        _TIER_CAPS = {"brief": (3, 240.0), "standard": (4, 300.0),
                      "deep": (6, 420.0), "report": (8, 540.0)}
        if _TIER in _TIER_CAPS:
            _tp, _tb = _TIER_CAPS[_TIER]
            if "max_results" not in args:
                max_results = _tp
            if "max_seconds" not in args:
                budget = _tb
        background = bool(args.get("background", True))

        if not background:
            if _DEEP_LOCK.locked():
                return _busy_response("background=false deep run")
            fut = _BROWSER_EXEC.submit(_inline_deep, query, categories,
                                       max_results, budget, write_path,
                                       slot_note, pinned)
            try:
                result = fut.result(timeout=float(budget) + 90)
            except _FutTimeout:
                return _busy_response("deep run queued longer than its budget")
            if isinstance(result, dict) and result.get("busy"):
                return _busy_response("deep run (browser was busy)")
            if slot_note:
                result.setdefault("warnings", []).append(slot_note)
            return _redacted(_shape_response(result, keep_raw))

        if _DEEP_LOCK.locked():
            return _busy_response("deep run")

        run_id = f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        _set_run(run_id, query=query, status="running",
                 started_ts=time.time(),
                 started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 guide_path=str(write_path), slot=slot_note)
        _BROWSER_EXEC.submit(_deep_worker, run_id, query, categories,
                             max_results, budget, write_path, slot_note, pinned)
        resp = {"ok": True, "run_id": run_id, "status": "running",
                "started_at": _RUNS[run_id]["started_at"],
                "guide_path": str(write_path),
                "how_to_check": (
                    "call greysearch_health — runs[] carries the digest; when "
                    "status=done, read guide_path. NEVER re-call greysearch with "
                    "tweaked args while a run is active.")}
        if slot_note:
            resp["slot"] = slot_note
        return _redacted(resp)

    if name in ("greysearch_health",):
        bridge = get_bridge()
        base = bridge.health_check()
        try:
            base["browser_slots"] = _slot_map()
        except Exception:
            pass
        try:
            mgr = SearXNGEngineManager()
            base["searx_space_instances"] = mgr._discover_public_instances(max_instances=3)
        except Exception as e:
            base["searx_space_instances"] = f"error: {e}"
        with _RUN_GUARD:
            runs = [dict(r) for r in sorted(_RUNS.values(),
                                            key=lambda d: d.get("started_ts", 0))]
        trimmed = []
        for r in runs[-_RUNS_KEEP:]:
            rr = {k: v for k, v in r.items() if k != "preview"}
            if r.get("preview"):
                rr["preview"] = r["preview"][:400]
            trimmed.append(rr)
        base["greysearch_runs"] = {
            "note": "background greysearch digests; when status=done, read the "
                    "master_guide/preview or open guide_path directly",
            "runs": trimmed,
        }
        return _redacted(base)

    raise ValueError(f"Unknown tool: {name}  (greysearch exposes exactly: "
                     f"greysearch, greysearch_health)")

def _initialize_result() -> dict:
    """initialize handshake result (shape-tested by tests/test_mcp_api.py)."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "greysearch", "version": "1.0.1"},
    }

def reply(rid, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("method") == "initialize":
            reply(req["id"], _initialize_result())
        elif req.get("method") == "notifications/initialized":
            pass
        elif req.get("method") == "tools/list":
            reply(req["id"], {"tools": TOOLS})
        elif req.get("method") == "tools/call":
            try:
                result = dispatch(req["params"].get("name", ""), req["params"].get("arguments", {}))
                reply(req["id"], {"content": [{"type": "text", "text": json.dumps(result)}]})
            except Exception as e:
                reply(req["id"], error={"code": -32000, "message": f"{type(e).__name__}: {e}"})
                traceback.print_exc(file=sys.stderr)
        elif "id" in req:
            reply(req["id"], error={"code": -32601, "message": "Method not found"})

if __name__ == "__main__":
    main()