#!/usr/bin/env python3
"""
Research integration bridge: patchright stealth scraper + SearXNG ladder + the
research pipeline's site tiers. 2026-10-16 rebuild — every defect below was
verified live before this rewrite:

- `site:` query variants removed (engines ignore them; they wasted most of a
  deep run's wall-clock and polluted results with off-topic domains).
- deep runs are now BUDGET-BOUNDED (per-page cap + wall-clock), polite to
  domains, and report every skipped page WITH its reason — a thin result now
  says exactly what was attempted and why it came up short instead of
  pretending to be a complete answer.
- paragraph structure preserved end-to-end (old code flattened pages to one
  line, so published guides were word-walls).
- one process-wide bridge (old code constructed a full bridge + engine test
  per call).
"""

from __future__ import annotations

import base64
import html
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import (parse_qsl, unquote, urlencode, urljoin,
                          urlparse, urlunparse)
from datetime import datetime, timezone

from patchright_scraper import PatchrightScraper
from searxng_integrated import (SearXNGEngineManager, searxng_search,
                               _split_selection)

try:
    import page_clean as _page_clean
    import relevance as _relevance
except Exception:
    import page_clean as _page_clean
    import relevance as _relevance

_repo_root = os.path.dirname(os.path.abspath(__file__))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import keys as research_keys
import pipeline_sites as pipeline

DEFAULT_MAX_PAGES = 12
DEFAULT_BUDGET_S = 240.0
try:
    import tuning as _tuning
except Exception:
    _tuning = None

def _pace(key: str) -> float:
    """Obedient pacing: doctor.py writes research/tuning.json; floors rule."""
    return _tuning.scaled(key) if _tuning is not None else 3.0

_POLITENESS_S = 3.0
_THIN_RESULTS_THRESHOLD = 3

_NAV_NOISE = re.compile(
    r"(?i)(skip to content|open our|about us|our etfs|merch\b|contact us|"
    r"subscribe\b|tune into|sign in|log in|trending now|watchlist|"
    r"\bsymbol name\b|\bmenu\b|\bcookie\b|\b×\b|invest now|open education)")
_REPEATED_TOKEN = re.compile(
    r"(\b\w[\w@®™×-]{2,}\b)(?:[ \n,|·:]*\b\1\b){2,}", re.IGNORECASE)

def _clean_result_url(url: str) -> str:
    """Strip tracking/redirect residue from a search-result URL before it
    can enter any pool: html-escaped ampersands (&amp;), DuckDuckGo's
    trailing rut= id, utm_* links, bing's msockid session tag. Live evidence
    the accepted URL in the 09:47 smoke run carried '&amp;rut=<hash>'."""
    if not url:
        return ""
    u = html.unescape(str(url))
    u = re.sub(r"[?&;]rut=[^&?\s]*;?", "", u)
    try:
        p = urlparse(u)
        if p.netloc and "uddg=" in u:
            m = re.search(r"uddg=([^&]+)", u)
            if m:
                u = unquote(m.group(1))
                p = urlparse(u)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")
             and k.lower() not in ("rut", "msockid")]
        return urlunparse(p._replace(query=urlencode(q)))
    except Exception:
        return u

def _judge_view(page: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten ``page["clean"]`` onto the page for the relevance judge.

    Scraped pages keep the chrome-free content under ``clean`` (``h2s``,
    ``excerpt``, ``body_text``, ``canonical_url``), while ``judge_pages`` and
    ``contamination_check`` read those keys at the top level.  Without this
    merge the judge sees only the title and URL.
    """
    if not isinstance(page, dict):
        return page
    clean = page.get("clean")
    if not isinstance(clean, dict):
        return page
    return {**page, **clean}

def _judge_batch(question: str, batch: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """Judge one batch on its cleaned view and store decisions on the
    ORIGINAL page objects, so downstream page data is unchanged."""
    decisions = _relevance.judge_pages(
        question, [_judge_view(page) for page in batch])
    for k, decision in enumerate(decisions):
        batch[k]["relevance"] = decision
    return decisions


_LIVE_PARA_CAP = 120    # paragraphs per page inside a live SSE payload
_LIVE_PARA_CHARS = 320  # per-paragraph clip inside a live SSE payload


def _slim_curation(page: Dict[str, Any], page_id: str) -> Optional[Dict[str, Any]]:
    """Live preview record for the portal's scraped stage event: the same
    curation record the run will finally save (built by the same builder,
    so page and paragraph ids are identical by construction), clipped so
    the SSE stream stays light. The full text lands when the run finishes
    and writes the sidecar; the live pane says so in plain words."""
    try:
        import greysearch_mcp as _gm
        rec = _gm._curation_page(page, page_id)
    except Exception:
        return None
    paras = rec.get("paragraphs") or []
    total = len(paras)
    long_p = any(len(str(p.get("text") or "")) > _LIVE_PARA_CHARS
                 for p in paras)
    if total > _LIVE_PARA_CAP or long_p:
        rec["paragraphs"] = [
            {"id": p.get("id"),
             "text": str(p.get("text") or "")[:_LIVE_PARA_CHARS]}
            for p in paras[:_LIVE_PARA_CAP]]
        rec["paragraphs_truncated"] = True
        rec["paragraphs_total"] = total
    return rec

_CONNECTIVE_WORDS = {
    "and", "or", "but", "for", "with", "the", "a", "an", "of", "in", "on",
    "to", "from", "by", "about", "into", "over", "after", "before",
    "between", "vs", "versus", "that", "this", "it", "its", "is", "are",
    "was", "were", "be", "been", "how", "what", "why", "when", "which",
    "who", "do", "does", "did", "can", "could", "should", "would", "will",
    "not", "no", "as", "at", "if", "so", "up", "down", "get", "make",
}
_MAX_ENTITY_WORDS = 4
_MAX_ENTITY_QUERIES = 4

def _is_camel(word: str) -> bool:
    """Mixed-case single word = a strong NAME boundary (PrismML, NInfer)."""
    core = word.strip("._-")
    if len(core) < 2 or not core[0].isalpha() or not core[0].isupper():
        return False
    rest = core[1:]
    return any(c.isupper() for c in rest) and any(c.islower() for c in rest)

def _decompose_query(question: str) -> List[str]:
    """Split a research question into short per-entity keyword queries.

    Splitting rules: comma/semicolon/pipe/newline/'vs' boundaries; CamelCase
    and digit-capped names ("27B") act as entity anchors; connective words
    are stripped everywhere. Each query keeps at most a few words. The full
    question is NEVER one query (the owner's rule: no long-tail searches)."""
    q = (question or "").strip()
    if not q:
        return []
    chunks = re.split(r"[,\n;|]+|\bvs\b|\bversus\b", q, flags=re.IGNORECASE)
    entities: List[str] = []
    cur: List[str] = []
    for chunk in chunks:
        for tok in re.split(r"[^\w\-.']+", chunk):
            low = tok.lower().strip(".'")
            if not tok or not low or low in _CONNECTIVE_WORDS:
                continue
            if cur and _is_camel(tok):
                entities.append(" ".join(cur))
                cur = [tok]
                continue
            cur.append(tok)
            if len(cur) >= _MAX_ENTITY_WORDS:
                entities.append(" ".join(cur))
                cur = []
        if cur:
            entities.append(" ".join(cur))
            cur = []
    out, seen = [], set()
    for e in entities:
        e = re.sub(r"\s+", " ", e).strip(" .,;:()'-").strip()
        k = e.lower()
        words = e.split()
        named = any(ch.isdigit() for ch in e) \
            or any(_is_camel(w) for w in words) \
            or any(w.isupper() and len(w) >= 2 for w in words)
        if e and k not in seen and len(words) <= _MAX_ENTITY_WORDS \
                and (len(words) >= 2 or named):
            seen.add(k)
            out.append(e)
    if not out:
        out = [_strip_connectives(q)]
    if len(out) > _MAX_ENTITY_QUERIES:
        out = out[:_MAX_ENTITY_QUERIES]
    return out

def _strip_connectives(query: str, max_words: int = 6) -> str:
    """Remove connective/stopword tokens from a query; keeps the rest in order."""
    keep = [t for t in re.split(r"[^\w\-.']+", query or "")
            if t and t.lower() not in _CONNECTIVE_WORDS]
    return " ".join(keep[:max_words]).strip(" .,;:()")

def _entity_token_sets(question: str) -> List[set]:
    """Per-entity token sets for the topical gate: a pool candidate is on-topic
    when it matches ANY entity's tokens (two minimum) — a page about one
    entity of a multi-entity question must survive the gate."""
    return [set(re.split(r"[^a-z0-9]+", _s.lower())) - {""}
            for _s in _decompose_query(question)]

def _cap_reason(reason: str, cap: int = 200) -> str:
    """Truncate a composed reason WITHOUT cutting mid-token — the [:200]
    slice produced visually broken strings like "...itself | title )"
    (QA pass-1, 2026-10-23). Semicolon-separated segments are whole
    information units; keep whole ones up to the cap."""
    r = (reason or "").strip()
    if len(r) <= cap:
        return r
    kept, used = [], 0
    for seg in r.split("; "):
        if used + len(seg) + (2 if kept else 0) > cap and kept:
            break
        if not kept and len(seg) > cap:
            cut = r[:cap].rsplit(" ", 1)[0]
            return cut.rstrip(" ,;|") + " ..."
        kept.append(seg)
        used += len(seg) + 2
    return "; ".join(kept)

def _dedupe_skipped(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One report entry per URL (first occurrence wins). Gate rejections land
    in both `rejected_by_gate` and `skipped`; the run report concatenates the
    two lists, so without this every rejection was listed twice
    (observed live, pass 1 2026-10-23, in both the run and its rerun)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for e in entries:
        key = (e.get("url") or "", str(e.get("reason") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

class ResearchScraperBridge:
    """Bridge between the patchright scraper and the research pipeline."""

    def __init__(self):
        self._scrape_slot = None
        self._active_scrapes = set()
        self.scraper = PatchrightScraper(stealth_level="high")
        self.searxng_manager = SearXNGEngineManager()
        self.sites_data = pipeline.SITES
        self.excluded_domains = set(pipeline.EXCLUDED)
        self._last_domain_hit: Dict[str, float] = {}
        self._sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

    def research_scrape(self, url: str, max_chars: int = 0) -> Dict[str, Any]:
        """Scrape a URL on the session's ONE slot browser. max_chars=0/None =
        whole page, never truncated. Truncation happens ONLY when a caller
        explicitly passes a positive max_chars, and it is then FLAGGED via
        truncated=True so no silent truncation can masquerade as ok."""
        start_time = time.time()
        domain = self._extract_domain(url)
        if domain in self.excluded_domains:
            return {"ok": False, "error": f"{domain} is on the excluded list",
                    "url": url, "domain": domain, "tier": "excluded",
                    "truncated": False}

        self._politeness_wait(domain)
        fetch_result = self.scraper.fetch_url(url)
        fetch_ok = bool(fetch_result.get("ok"))
        if not fetch_ok:
            return {
                "ok": False,
                "url": url,
                "domain": domain,
                "tier": self._get_tier(domain),
                "error": fetch_result.get("error", "Fetch failed"),
                "fetched": self._now(),
                "truncated": False,
            }

        text_content = fetch_result.get("text", "") or ""
        truncated = False
        if max_chars and max_chars > 0 and len(text_content) > max_chars:
            text_content = text_content[:max_chars]
            last_space = text_content.rfind(' ')
            if last_space > max_chars * 0.8:
                text_content = text_content[:last_space]
            truncated = True

        return {
            "ok": bool(text_content),
            "url": url,
            "final_url": fetch_result.get("final_url", url),
            "title": fetch_result.get("title", ""),
            "domain": domain,
            "tier": self._get_tier(domain),
            "fetched": self._now(),
            "chars": len(text_content),
            "truncated": truncated,
            "text": text_content,
            "raw_text": fetch_result.get("raw_text", ""),
            "html": fetch_result.get("html", ""),
            "html_capped": fetch_result.get("html_capped", False),
            "links": fetch_result.get("links", []),
            "images": fetch_result.get("images", []),
            "videos": fetch_result.get("videos", []),
            "audios": fetch_result.get("audios", []),
            "pdfs": fetch_result.get("pdfs", []),
            "canvases": fetch_result.get("canvases", []),
            "iframes": fetch_result.get("iframes", []),
            "meta": fetch_result.get("meta", {}),
            "status_code": fetch_result.get("status_code", 0),
            "tables": fetch_result.get("tables", []),
            "headings": fetch_result.get("headings", []),
            "code_blocks": fetch_result.get("code_blocks", []),
            "injection_flags": fetch_result.get("injection_flags", []),
            "injection_scanned": fetch_result.get("injection_scanned", False),
            "elapsed_s": fetch_result.get("elapsed_s", round(time.time() - start_time, 2)),
            "key_backends_available": {"patchright": True},
        }

    def research_search(self,
                        query: str,
                        category: str = "general",
                        max_results: int = 12,
                        time_range: str = "",
                        language: str = "",
                        engines: Optional[List[str]] = None) -> Dict[str, Any]:
        """Research-oriented search. The SearXNG manager itself now runs the
        automatic ladder (local -> searx.space -> direct keyless); this adds a
        merge of the searx_fallback ladder when local results come back thin
        (< 3), and always records which lanes produced what. Connective words
        are stripped from the search string (never long-tail); the original
        question stays on the result for gate/judge use.

        engines (2026-11-03): optional user selection; when non-empty it rides
        BOTH the manager's additive request and the thin-merge fallback search
        (the fallback lane can only accept it in its local query param)."""
        search_q = _strip_connectives(query) or query
        search_result = self.searxng_manager.search(
            query=search_q, category=category, max_results=max_results,
            time_range=time_range, language=language, engines=engines)

        ladder = list(search_result.get("ladder") or [])
        results = list(search_result.get("results") or [])

        if len(results) < _THIN_RESULTS_THRESHOLD:
            try:
                import searx_fallback as _sf
                lad = _sf.search(query, max_results=max_results,
                                 engines=engines)
                if lad.get("ok") and lad.get("results"):
                    have = {r.get("url") for r in results}
                    fresh = [r for r in lad["results"] if r.get("url") not in have]
                    results.extend(fresh[:max_results])
                    ladder.append(f"searx_fallback merge: +{len(fresh[:max_results])} "
                                  f"(source: {lad.get('source')})")
            except Exception as e:
                ladder.append(f"searx_fallback merge failed: {str(e)[:120]}")

        for r in results:
            if isinstance(r, dict) and r.get("url"):
                r["url"] = _clean_result_url(r.get("url", ""))

        processed = []
        seen_urls = set()
        q_toks = _relevance.question_tokens(query)
        for result in results:
            url = result.get("url", "")
            domain = result.get("domain") or self._extract_domain(url)
            if not url or url in seen_urls or domain in self.excluded_domains:
                continue
            seen_urls.add(url)
            title = (result.get("title", "") or "")[:200]
            snippet = (result.get("content", "") or result.get("snippet", "") or "")[:300]
            tier = result.get("tier") or self._get_tier(domain)
            pf = _relevance.prefilter(url, title=title, snippet=snippet,
                                      domain=domain, tier=tier,
                                      tokens=q_toks, question=query)
            processed.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "domain": domain,
                "tier": tier,
                "engine": result.get("engine", ""),
                "relevance": {
                    "decision": {"accept": "accept",
                                 "deprioritize": "quarantine",
                                 "reject": "reject"}[pf["decision"]],
                    "relevance_score": int(round(pf["coverage"] * 100)),
                    "source_type": _relevance.classify_source_type(domain, tier, title),
                    "reason": pf["reason"] or "deterministic pre-filter pass",
                    "coverage": round(pf["coverage"], 2),
                    "procedural": pf["procedural"],
                },
            })
            if len(processed) >= max_results:
                break
        processed = _relevance.rank_results(
            query, processed,
            judged={r["url"]: r["relevance"] for r in processed})

        return {
            "ok": bool(processed),
            "query": query,
            "category": category,
            "results": processed,
            "ladder": ladder,
            "last_error": search_result.get("last_error"),
            "key_backends_available": {
                "patchright": True,
                "searxng": len(self.searxng_manager.get_working_engines()) > 0,
            },
        }

    def research_deep(self,
                      question: str,
                      categories: Optional[List[str]] = None,
                      max_pages: int = 0,
                      max_chars_per_page: int = 0,
                      max_total_seconds: float = DEFAULT_BUDGET_S,
                      pinned_sources: Optional[List[str]] = None,
                      enable_semantic_judge: bool = True,
                      min_accept_score: int = _relevance.ACCEPT_SCORE,
                      progress_cb: Optional[Any] = None,
                      scrape_wall_s: int = 100,
                      engines: Optional[List[str]] = None) -> Dict[str, Any]:
        def _emit(stage: str, data: Optional[Dict[str, Any]] = None) -> None:
            """Portal/progress hook: never load-bearing, never raises."""
            if progress_cb is None:
                return
            try:
                progress_cb(stage, data or {})
            except Exception:
                pass

        _emit("searching", {"question": question[:120]})

        """Budget-bounded deep research: search the question (merged engines),
        rank, then scrape up to max_pages within max_total_seconds. Reports
        skipped pages and per-lane outcomes honestly. No fake 'all done'.
        2026-10-18: optional pinned_sources = exact primary-domain URLs the
        run fetches FIRST (audits proved SearXNG search never surfaces
        registry-primary design domains); each pinned page also contributes
        its top same-site topical links to the pool as primary followers.
        2026-10-19 relevance-gated rebuild: the pool passes a deterministic
        pre-filter; every scraped page is cleaned (page_clean) and judged
        (relevance.judge_pages). pages_fetched is the ACCEPTED corpus ONLY;
        quarantined/rejected pages are reported with reasons and never feed
        facts, prose, tables, citations, or images. Ranking uses the semantic
        score — snippet length is no longer a signal. Optional kwargs only, so
        frozen importers are unaffected."""
        start_time = time.time()
        deadline = start_time + float(max_total_seconds)
        _budget = float(max_total_seconds)
        search_deadline = start_time + _budget * 0.55
        scrape_deadline = start_time + _budget * 0.85
        page_cap = int(max_pages) if max_pages and max_pages > 0 else DEFAULT_MAX_PAGES

        cats = categories or self._pick_categories(question)
        _sel = _split_selection(engines)

        search_plan: List[Dict[str, Any]] = []
        pool: Dict[str, Dict[str, Any]] = {}
        entity_queries = _decompose_query(question)
        search_plan.append({"category": "decomposition",
                            "query": " → ".join(entity_queries)[:160],
                            "ok": bool(entity_queries), "n": len(entity_queries),
                            "ladder": entity_queries,
                            "engines": list(engines or [])})
        for i, eq in enumerate(entity_queries):
            cat_i = cats[0] if (cats and i == 0) else "general"
            _sw = __import__("concurrent.futures", fromlist=["x"])
            _search_pool = _sw.ThreadPoolExecutor(max_workers=1)
            try:
                _sfut = _search_pool.submit(
                    self.research_search, eq, category=cat_i, max_results=8,
                    engines=_sel["text"])
                search_result = _sfut.result(timeout=240.0)
            except Exception as _sw_err:
                search_result = {"ok": False, "results": [],
                                 "ladder": [f"search lane abandoned after "
                                            f"240s wall ({str(_sw_err)[:60]})"]}
            finally:
                _search_pool.shutdown(wait=False, cancel_futures=True)
            search_plan.append({
                "category": cat_i,
                "query": eq,
                "ok": search_result.get("ok", False),
                "n": len(search_result.get("results", [])),
                "ladder": search_result.get("ladder", []),
                "engines": list(_sel["text"]),
            })
            for result in search_result.get("results", []):
                pool.setdefault(result["url"], result)
            if time.time() > search_deadline:
                break

        q_tokens_pinned = {t for t in re.split(r"[^a-z0-9]+", question.lower()) if len(t) > 3}
        for pu in list(dict.fromkeys(pinned_sources or []))[:12]:
            pu = str(pu).strip()
            if not pu:
                continue
            dom = self._extract_domain(pu)
            pool.setdefault(pu, {"title": "", "url": pu,
                                 "snippet": "pinned primary source",
                                 "domain": dom or pu,
                                 "tier": self._get_tier(dom) if dom else "primary",
                                 "engine": "pinned"})
            try:
                pr = self.research_scrape(pu, max_chars=0)
                if not pr.get("ok"):
                    continue
                n_follow = 0
                for link in (pr.get("links") or []):
                    if n_follow >= 5:
                        break
                    lu = (link.get("href") if isinstance(link, dict)
                          else link.get("url") if isinstance(link, dict) else str(link)) or ""
                    text = (link.get("text") if isinstance(link, dict) else "") or ""
                    ldom = self._extract_domain(lu)
                    if not lu or lu in pool or ldom != dom:
                        continue
                    if sum(1 for t in q_tokens_pinned if t in text.lower()) >= 1:
                        pool[lu] = {"title": text[:120], "url": lu,
                                    "snippet": "pinned-page topical link",
                                    "domain": ldom, "tier": "primary",
                                    "engine": "pinned-link"}
                        n_follow += 1
            except Exception as e:
                search_plan.append({"category": "pinned", "query": pu[:100],
                                    "ok": False, "n": 0,
                                    "ladder": [f"pinned harvest failed: {str(e)[:80]}"]})

        _entity_sets = _entity_token_sets(question)
        _full_set = set(q_tokens_pinned)
        def _pool_relevant(r: Dict[str, Any]) -> bool:
            hay = " ".join([str(r.get("title", "")), str(r.get("snippet", "")),
                            str(r.get("url", ""))]).lower()
            for etoks in _entity_sets:
                matched = [t for t in etoks if t in hay]
                if len(matched) >= 2:
                    return True
            return len([t for t in _full_set if t in hay]) >= 2

        _pool_before = len(pool)
        _gate_rejected: Dict[str, Dict[str, Any]] = {
            u: r for u, r in pool.items()
            if not _pool_relevant(r) and r.get("engine") != "pinned"}
        pool = {u: r for u, r in pool.items()
                if _pool_relevant(r) or r.get("engine") == "pinned"}
        _pool_filtered_out = _pool_before - len(pool)
        search_plan.append({"category": "relevance-gate",
                            "query": "(pool topical filter)",
                            "ok": True,
                            "n": len(pool),
                            "filtered_out": _pool_filtered_out,
                            "ladder": []})

        _pre_before = len(pool)
        _pre_rejects: List[Dict[str, str]] = []
        _kept: Dict[str, Dict[str, Any]] = {}
        for u, r in pool.items():
            if r.get("engine") == "pinned":
                _kept[u] = r
                continue
            pf = _relevance.prefilter(
                u, title=r.get("title", ""), snippet=r.get("snippet", ""),
                domain=r.get("domain", ""), tier=r.get("tier", ""),
                question=question)
            r = dict(r)
            r["prefilter"] = pf
            if pf["decision"] == "reject":
                _pre_rejects.append({"url": u, "decision": "reject",
                                     "reason": pf["reason"]})
                continue
            _kept[u] = r
        pool = _kept
        search_plan.append({"category": "prefilter",
                            "query": "(deterministic URL/title/coverage gate)",
                            "ok": True,
                            "n": len(pool),
                            "filtered_out": _pre_before - len(pool),
                            "ladder": []})
        prefilter_rejects = _pre_rejects

        if len(pool) < 4 and _gate_rejected and time.time() < search_deadline:
            _readmitted = 0
            for u, r in _gate_rejected.items():
                if len(pool) >= 4:
                    break
                if u in pool:
                    continue
                r = dict(r)
                r["pool_rescue"] = True
                pool[u] = r
                _readmitted += 1
            if _readmitted:
                search_plan.append({
                    "category": "pool-rescue",
                    "query": "(gate-rejected candidates re-enter; judged with body evidence)",
                    "ok": True, "n": _readmitted, "ladder": []})

        if len(pool) < 4 and time.time() < search_deadline:
            try:
                rescue = self.research_search(question, category="news",
                                              max_results=12,
                                              engines=_sel["news"])
                _rescue_before = len(rescue.get("results", []) or [])
                _rescue_gated = {r["url"]: r for r in rescue.get("results", []) or []
                                 if _pool_relevant(r)}
                _rescue_added = 0
                for u, r in _rescue_gated.items():
                    if u not in pool:
                        pf = _relevance.prefilter(
                            u, title=r.get("title", ""), snippet=r.get("snippet", ""),
                            domain=r.get("domain", ""), tier=r.get("tier", ""),
                            question=question)
                        if pf["decision"] == "reject":
                            continue
                        pool[u] = {**r, "engine": (r.get("engine") or "") + "+rescue-news"}
                        _rescue_added += 1
                search_plan.append({
                    "category": "news-rescue", "query": question[:120],
                    "ok": bool(_rescue_gated), "n": _rescue_added,
                    "filtered_out": _rescue_before - len(_rescue_gated),
                    "ladder": rescue.get("ladder", [])})
            except Exception as e:
                search_plan.append({"category": "news-rescue", "query": question[:120],
                                    "ok": False, "n": 0, "filtered_out": 0,
                                    "ladder": [f"{type(e).__name__}: {e}"]})

        q_tokens = {t for t in re.split(r"[^a-z0-9]+", question.lower()) if len(t) > 3}

        def _pre_rank(r: Dict[str, Any]) -> tuple:
            pf = r.get("prefilter") or {}
            tier_score = 0 if r.get("tier") == "primary" else 1 if r.get("tier") == "secondary" else 2
            deprio = 1 if pf.get("decision") == "deprioritize" else 0
            overlap = sum(1 for t in q_tokens
                          if t in (r.get("title") or "").lower())
            procedural = 1 if (pf.get("procedural")
                               or _relevance._PROCEDURAL_TITLE.search(
                                   r.get("title") or "")) else 0
            return (deprio, tier_score, -procedural, -overlap)

        ordered = sorted(pool.values(), key=_pre_rank)
        scraped: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = list(prefilter_rejects)
        rejected_by_gate: List[Dict[str, Any]] = []
        budget_hit = False
        domain_counts: Dict[str, int] = {}
        canonical_seen: set = set()

        _emit("search_done", {"pool": len(ordered)})
        for result in ordered:
            dom = result.get("domain") or ""
            if domain_counts.get(dom, 0) >= 2:
                skipped.append({"url": result["url"], "decision": "deprioritized",
                                "reason": "same-domain cap (2) reached"})
                continue
            if len(scraped) >= page_cap:
                skipped.append({"url": result["url"], "decision": "deprioritized",
                                "reason": f"page cap {page_cap} reached"})
                continue
            if time.time() > scrape_deadline:
                skipped.append({"url": result["url"], "decision": "deprioritized",
                                "reason": "time budget reached"})
                budget_hit = True
                continue
            if result.get("engine") != "pinned" and _relevance.judge_available():
                if not (result.get("title", "").strip()
                        or (result.get("snippet", "")
                            or result.get("content", "")).strip()):
                    skipped.append({"url": result["url"], "decision": "reject",
                                    "reason": "lane entry has no title/snippet"})
                    rejected_by_gate.append({"url": result["url"],
                                             "decision": "reject",
                                             "reason": "no title/snippet"})
                    continue
            # snippet-only evidence no longer kills a candidate here: coverage
            # scores on a two-line snippet rejected whole pages the run never
            # read ("not pulling content"). Every candidate goes to the scrape
            # lane; the post-scrape judge — same judge, full page body — owns
            # the verdict.
            if self._scrape_slot is None:
                self._scrape_slot = ThreadPoolExecutor(max_workers=2)
                self._active_scrapes = set()
            still_busy = {f for f in self._active_scrapes if f.running()}
            self._active_scrapes = still_busy
            if len(still_busy) >= 2:
                skipped.append({"url": result["url"], "decision": "reject",
                                "reason": "scrape wall: both scrape "
                                          "workers wedged on earlier pages "
                                          "— skipping further scrapes "
                                          "this run"})
                continue
            _wall_fut = self._scrape_slot.submit(
                self.research_scrape, result["url"],
                max_chars=max_chars_per_page
                if max_chars_per_page and max_chars_per_page > 0 else 0)
            self._active_scrapes.add(_wall_fut)
            try:
                scrape_result = _wall_fut.result(timeout=scrape_wall_s)
            except Exception as _wall_err:
                is_timeout = "timed out" in str(_wall_err) or \
                    "TimeoutError" in type(_wall_err).__name__
                scrape_result = {"ok": False, "url": result["url"],
                                 "error": ("scrape wall ("
                                           + str(scrape_wall_s)
                                           + "s) exceeded"
                                           if is_timeout else
                                           "scrape worker error: "
                                           + str(_wall_err)[:120])}
            self._active_scrapes.discard(_wall_fut)
            if not scrape_result.get("ok"):
                skipped.append({"url": result["url"], "decision": "reject",
                                "reason": (scrape_result.get("error") or "scrape failed")[:160]})
                rejected_by_gate.append({"url": result["url"], "decision": "reject",
                                         "reason": (scrape_result.get("error")
                                                    or "scrape failed")[:160]})
                continue
            domain_counts[dom] = domain_counts.get(dom, 0) + 1

            cleaned = _page_clean.clean_page(scrape_result)
            canon = cleaned.get("canonical_url") or result["url"]
            if canon in canonical_seen:
                reason = f"duplicate/canonical-equivalent of {canon[:80]}"
                skipped.append({"url": result["url"], "decision": "reject",
                                "reason": reason})
                rejected_by_gate.append({"url": result["url"],
                                         "decision": "reject", "reason": reason})
                continue
            canonical_seen.add(canon)
            if _page_clean.is_thin(cleaned):
                reason = (f"thin_content: {cleaned.get('main_chars', 0)} "
                          f"chars of main text (< {_page_clean.MIN_MAIN_CHARS})")
                skipped.append({"url": result["url"], "decision": "reject",
                                "reason": reason})
                rejected_by_gate.append({"url": result["url"],
                                         "decision": "reject", "reason": reason})
                continue
            if cleaned.get("boilerplate_ratio", 0) >= 0.85:
                reason = (f"boilerplate_ratio {cleaned.get('boilerplate_ratio')}"
                          " — page is mostly navigation/chrome")
                skipped.append({"url": result["url"], "decision": "reject",
                                "reason": reason})
                rejected_by_gate.append({"url": result["url"],
                                         "decision": "reject", "reason": reason})
                continue

            page = {
                "url": result["url"],
                "title": scrape_result.get("title") or result.get("title", ""),
                "domain": scrape_result.get("domain", result.get("domain", "")),
                "tier": scrape_result.get("tier", "unlisted"),
                "ok": True,
                "text": scrape_result.get("text", ""),
                "raw_text": scrape_result.get("raw_text", ""),
                "links": scrape_result.get("links", []),
                "images": scrape_result.get("images", []),
                "videos": scrape_result.get("videos", []),
                "tables": scrape_result.get("tables", []),
                "headings": scrape_result.get("headings", []),
                "code_blocks": scrape_result.get("code_blocks", []),
                "injection_flags": scrape_result.get("injection_flags", []),
                "chars": scrape_result.get("chars", 0),
                "clean": cleaned,
                "relevance": None,
            }
            scraped.append(page)
            _emit("scraped", {"url": result["url"], "n": len(scraped),
                              "title": (page.get("title") or "")[:80],
                              "page": _slim_curation(page,
                                                     f"pg{len(scraped)-1}")})
            if time.time() < scrape_deadline:
                time.sleep(random.uniform(_pace("page_gap_min_s"),
                                          _pace("page_gap_max_s")))

        judge_decisions: List[Optional[Dict[str, Any]]] = [None] * len(scraped)
        quality_warnings: List[str] = []
        judge_ran = False
        if enable_semantic_judge and scraped:
            judge_ran = _relevance.judge_available()
            if not judge_ran:
                time.sleep(2.0)
                judge_ran = _relevance.judge_available()
                if not judge_ran:
                    quality_warnings.append(
                        "judge liveness probe failed twice — all scraped "
                        "pages quarantined (probe flapped)")
            if judge_ran:
                i = 0
                while i < len(scraped):
                    if time.time() > deadline:
                        for j in range(i, len(scraped)):
                            scraped[j]["relevance"] = {
                                "decision": "quarantine",
                                "relevance_score": 50,
                                "source_type": _relevance.classify_source_type(
                                    scraped[j].get("domain", ""),
                                    scraped[j].get("tier", ""),
                                    scraped[j].get("title", "")),
                                "reason": "judge_budget_exceeded",
                                "allowed_content": [], "risk_flags": ["thin_content"],
                            }
                        budget_hit = True
                        _emit("judged", {"judged_so_far": len(scraped),
                                         "of": len(scraped),
                                         "accepted_so_far": sum(
                                             1 for p in scraped
                                             if ((p.get("relevance") or {})
                                                 .get("decision")) == "accept"),
                                         "start": 0,
                                         "decisions": [
                                             str((p.get("relevance") or {})
                                                 .get("decision")
                                                 or "quarantine")
                                             for p in scraped]})
                        break
                    batch = scraped[i:i + _relevance.JUDGE_BATCH]
                    _judge_batch(question, batch)
                    i += _relevance.JUDGE_BATCH
                    _d = [p["relevance"] or {} for p in batch]
                    _n_accept = sum(1 for d in _d if d.get("decision") == "accept")
                    _emit("judged", {"judged_so_far": i, "of": len(scraped),
                                     "accepted_so_far": _n_accept,
                                     "start": i - _relevance.JUDGE_BATCH,
                                     "decisions": [str(d.get("decision") or "")
                                                   for d in _d]})
            if not judge_ran:
                for p in scraped:
                    p["relevance"] = {
                        "decision": "quarantine",
                        "relevance_score": 50,
                        "source_type": _relevance.classify_source_type(
                            p.get("domain", ""), p.get("tier", ""),
                            p.get("title", "")),
                        "reason": "judge_unavailable (intern endpoint down) — "
                                  "page quarantined, never auto-accepted",
                        "allowed_content": [], "risk_flags": [],
                    }
                _emit("judged", {"judged_so_far": len(scraped),
                                 "of": len(scraped), "accepted_so_far": 0,
                                 "start": 0,
                                 "decisions": ["quarantine"] * len(scraped)})

        accepted: List[Dict[str, Any]] = []
        quarantined: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for p in scraped:
            rel = p.get("relevance") or {}
            entry = {"url": p["url"], "decision": rel.get("decision", "quarantine"),
                     "reason": _cap_reason(rel.get("reason") or ""),
                     "relevance_score": rel.get("relevance_score")}
            dec = rel.get("decision")
            if dec == "accept":
                if min_accept_score != _relevance.ACCEPT_SCORE and \
                        int(rel.get("relevance_score", 0)) < int(min_accept_score):
                    quarantined.append({**entry, "reason": entry["reason"] +
                                        " (below caller min_accept_score)"})
                    continue
                accepted.append(p)
            elif dec == "quarantine":
                quarantined.append(entry)
            else:
                rejected.append(entry)
        for e in rejected_by_gate:
            rejected.append({k: e.get(k) for k in ("url", "decision", "reason")})

        judged_map = {p["url"]: (p.get("relevance") or {}) for p in accepted}
        accepted = _relevance.rank_results(question, accepted, judged=judged_map)
        for p in accepted:
            if not p.get("title") and p.get("clean", {}).get("title"):
                p["title"] = p["clean"]["title"]

        facts = self._extract_facts(question, accepted)
        elapsed = round(time.time() - start_time, 2)

        if not judge_ran and scraped:
            quality_warnings.append(
                "semantic judge unavailable — all scraped pages quarantined; "
                "the guide will be thin or empty by design")
        if budget_hit:
            quality_warnings.append("run hit its time budget — later pages unjudged/unscraped")
        if len(accepted) < 3:
            quality_warnings.append(
                f"thin run: only {len(accepted)} accepted page(s) — the guide "
                "reports DATA NOT CAPTURED rather than padding")
        for p in accepted:
            for flag in (p.get("relevance") or {}).get("risk_flags", []):
                quality_warnings.append(
                    f"{p['url'][:80]}: risk flag '{flag}' on an accepted page")
        _skipped_pages = _dedupe_skipped(
            rejected + quarantined +
            [{k: e.get(k) for k in ("url", "decision", "reason")}
             for e in skipped])
        _all_candidates = set(pool)
        _all_candidates.update(p.get("url") for p in accepted if p.get("url"))
        _all_candidates.update(e.get("url") for e in _skipped_pages
                               if e.get("url"))
        run_report = {
            "query": question,
            "engines": list(engines or []),
            "candidate_count": len(_all_candidates),
            "scraped_count": len(scraped),
            "accepted_count": len(accepted),
            "quarantined_count": len(quarantined),
            "rejected_count": len(rejected),
            "accepted_sources": [p["url"] for p in accepted],
            "skipped_pages": _skipped_pages,
            "quality_warnings": quality_warnings,
        }

        _emit("done", {"accepted": len(accepted), "scraped": len(scraped),
                       "elapsed_s": round(elapsed, 1)})
        return {
            "question": question,
            "categories": cats,
            "engines": list(engines or []),
            "searches": search_plan,
            "pages_fetched": accepted,
            "quarantined_pages": quarantined,
            "rejected_pages": rejected,
            "all_scraped_pages": scraped,
            "skipped_pages": skipped,
            "sources": sorted({p["url"] for p in accepted}),
            "findings": facts,
            "page_cap": page_cap,
            "budget_s": max_total_seconds,
            "budget_hit": budget_hit,
            "judge_ran": judge_ran,
            "run_report": run_report,
            "elapsed_s": elapsed,
            "note": ("pages_fetched is the ACCEPTED evidence corpus only "
                     "(relevance decision == accept, score >= "
                     f"{min_accept_score}). Quarantined and rejected pages are "
                     "listed with reasons and never feed facts, prose, tables, "
                     "citations, or images. facts carry source_urls. "
                     "skipped_pages lists every URL not scraped or not accepted, "
                     "and why; a thin result is an honest thin result, never a "
                     "claim of completeness."),
            "key_backends_available": {
                "patchright": True,
                "searxng": len(self.searxng_manager.get_working_engines()) > 0,
            },
        }

    def _politeness_wait(self, domain: str) -> None:
        last = self._last_domain_hit.get(domain, 0.0)
        wait = _pace("politeness_s") - (time.time() - last)
        if wait > 0:
            time.sleep(min(wait, _POLITENESS_S))
        self._last_domain_hit[domain] = time.time()

    def _extract_facts(self,
                       question: str,
                       pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract question-relevant sentences with source attribution."""
        q_terms = {w for w in re.findall(r"[a-z]{4,}", (question or "").lower())}
        facts: List[Dict[str, Any]] = []

        for page in pages or []:
            if not page.get("ok"):
                continue
            text = (page.get("clean") or {}).get("body_text") or ""
            if not text:
                continue
            sentences = self._sent_split.split(text)
            for sentence in sentences:
                sentence = " ".join(sentence.split())
                if not (60 <= len(sentence) <= 500):
                    continue
                if _NAV_NOISE.search(sentence) and len(sentence.split()) < 14:
                    continue
                if len(_NAV_NOISE.findall(sentence)) >= 2:
                    continue
                if _REPEATED_TOKEN.search(sentence):
                    continue
                low = sentence.lower()
                score = sum(1 for t in q_terms if t in low)
                if score >= 2:
                    facts.append({
                        "text": sentence,
                        "source_url": page["url"],
                        "source_domain": page.get("domain", ""),
                        "tier": page.get("tier", "unlisted"),
                        "score": score,
                    })

        merged: Dict[str, Dict[str, Any]] = {}
        for fact in facts:
            key = re.sub(r'\W+', ' ', fact["text"][:240].lower()).strip()
            if key not in merged:
                merged[key] = {**fact,
                               "source_urls": [fact["source_url"]],
                               "source_domains": [fact["source_domain"]]}
            else:
                if fact["source_url"] not in merged[key]["source_urls"]:
                    merged[key]["source_urls"].append(fact["source_url"])
                if fact["source_domain"] not in merged[key]["source_domains"]:
                    merged[key]["source_domains"].append(fact["source_domain"])

        out = list(merged.values())
        out.sort(key=lambda f: (-len(f["source_urls"]),
                                f["tier"] != "primary",
                                -f["score"]))
        return out[:40]

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def _get_tier(self, domain: str) -> str:
        if not domain:
            return "unlisted"
        for _category, entries in self.sites_data.get("categories", {}).items():
            for entry in entries:
                if domain.endswith(entry.get("domain", "")):
                    return entry.get("tier", "unlisted")
        return "unlisted"

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

    def _pick_categories(self, question: str) -> List[str]:
        """Registry categories first when the question is about web design:
        searxng_integrated normalizes unknown search categories to general ON
        THE SEARCH SIDE, while the sites.json tier system uses the registry
        category ON THE RANKING SIDE — so 'webdesign' is safe to emit."""
        q = set(re.split(r"[^a-z0-9]+", (question or "").lower()))
        design_words = {
            "typography", "font", "typeface", "whitespace", "pairing", "layout",
            "wordpress", "woocommerce", "theme", "css", "design", "ux",
            "responsive", "avif", "webp", "lqip", "srcset", "editorial",
            "showcase", "typewolf"}
        if q & design_words:
            return ["webdesign", "general"]
        return ["general"]

    def health_check(self) -> Dict[str, Any]:
        scraper_health = self.scraper.health_check()
        searxng_stats = self.searxng_manager.get_engine_stats()
        return {
            "scraper": scraper_health,
            "searxng": searxng_stats,
            "research_bridge": {
                "excluded_domains_count": len(self.excluded_domains),
                "pages_fetched_this_process": PatchrightScraper._pages_fetched,
                "politeness_s": _POLITENESS_S,
            },
            "timestamp": time.time(),
        }

_BRIDGE: Optional[ResearchScraperBridge] = None

def get_bridge() -> ResearchScraperBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = ResearchScraperBridge()
    return _BRIDGE

def research_scrape(url: str, max_chars: int = 0) -> Dict[str, Any]:
    return get_bridge().research_scrape(url, max_chars=max_chars)

def research_search(query: str,
                    category: str = "general",
                    max_results: int = 12,
                    time_range: str = "",
                    language: str = "",
                    engines: Optional[List[str]] = None) -> Dict[str, Any]:
    return get_bridge().research_search(
        query, category=category, max_results=max_results,
        time_range=time_range, language=language, engines=engines)

def research_deep(question: str,
                  categories: Optional[List[str]] = None,
                  max_pages: int = 0,
                  max_chars_per_page: int = 0,
                  max_total_seconds: float = DEFAULT_BUDGET_S,
                  pinned_sources: Optional[List[str]] = None,
                  enable_semantic_judge: bool = True,
                  min_accept_score: int = _relevance.ACCEPT_SCORE,
                  progress_cb: Optional[Any] = None,
                  engines: Optional[List[str]] = None) -> Dict[str, Any]:
    return get_bridge().research_deep(
        question, categories=categories, max_pages=max_pages,
        max_chars_per_page=max_chars_per_page,
        max_total_seconds=max_total_seconds,
        pinned_sources=pinned_sources,
        enable_semantic_judge=enable_semantic_judge,
        min_accept_score=min_accept_score, progress_cb=progress_cb,
        engines=engines)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "search" and len(sys.argv) > 2:
            result = research_search(" ".join(sys.argv[2:]), max_results=3)
            print(json.dumps({k: v for k, v in result.items() if k == "ok"},
                             indent=2) if False else json.dumps(
                {**{k: v for k, v in result.items() if k != "results"},
                 "results": [r["url"] for r in result["results"]]}, indent=2))
        elif sys.argv[1] == "scrape" and len(sys.argv) > 2:
            result = research_scrape(sys.argv[2])
            print(json.dumps({**{k: v for k, v in result.items()
                                 if k not in ("raw_text", "html", "text", "links")},
                              "text_head": result.get("text", "")[:400],
                              "n_links": len(result.get("links", []))}, indent=2))
        else:
            result = research_deep(" ".join(sys.argv[1:]), max_pages=3, max_total_seconds=120)
            print(json.dumps({k: result[k] for k in
                              ("question", "page_cap", "pages_ok", "elapsed_s", "budget_hit")
                              if k in result} |
                             {"pages_ok": len(result["pages_fetched"]),
                              "skipped": len(result["skipped_pages"]),
                              "sources": result["sources"][:8],
                              "findings_head": [f["text"][:80] for f in result["findings"][:5]]},
                             indent=2))
    else:
        print("Usage:\n  python research_integration.py search <query>\n"
              "  python research_integration.py scrape <url>\n"
              "  python research_integration.py <question>")