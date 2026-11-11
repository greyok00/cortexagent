#!/usr/bin/env python3
"""
Research integration bridge: patchright stealth scraper + SearXNG ladder + the
research pipeline's site tiers.

- no `site:` query variants (engines ignore them; they waste most of a deep
  run's wall-clock and pollute results with off-topic domains).
- deep runs are BUDGET-BOUNDED (per-page cap + wall-clock), polite to
  domains, and report every skipped page WITH its reason: a thin result
  says exactly what was attempted and why it came up short instead of
  pretending to be a complete answer.
- paragraph structure preserved end-to-end (flattening pages to one line
  turns published guides into word-walls).
- one process-wide bridge (constructing a full bridge + engine test per
  call is wasteful).
"""

from __future__ import annotations

import html
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import (parse_qsl, unquote, urlencode, urlparse, urlunparse)
from datetime import datetime, timezone

from patchright_scraper import PatchrightScraper
from searxng_integrated import (SearXNGEngineManager, _split_selection, _instance_probes,
                               _rotate_order)
import proxy_mode as _proxy_mode

try:
    import page_clean as _page_clean
    import relevance as _relevance
except Exception:
    import page_clean as _page_clean
    import relevance as _relevance

_repo_root = os.path.dirname(os.path.abspath(__file__))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import pipeline_sites as pipeline

DEFAULT_MAX_PAGES = 12
DEFAULT_BUDGET_S = 240.0
try:
    import tuning as _tuning
except Exception:
    _tuning = None

# Auto-resume: the durable search record rides the search_done emit and
# the run's registry row; a resume replays it verbatim instead of redoing
# the search. One cap at emit keeps the record bounded on
# the live stream. SEARCH_POOL_MAX caps the replayed pool one time at emit;
# resume reads the stored copy un-capped (it was never stored bigger).
# Overrides: GREYSEARCH_SEARCH_POOL_MAX / GREYSEARCH_SEARCH_PLAN_MAX.
SEARCH_POOL_MAX = int(os.environ.get("GREYSEARCH_SEARCH_POOL_MAX") or 120)
SEARCH_PLAN_MAX = int(os.environ.get("GREYSEARCH_SEARCH_PLAN_MAX") or 24)
SEARCH_LADDER_MAX = 20

_PREFLIGHT_TIMEOUT_S = 5.0
_PREFLIGHT_GAP_S = 3.0

_LANE_ADD_SHAPES = (
    ("local", re.compile(r"^local:\s*[1-9]\d* results")),
    ("local unfiltered rescue",
     re.compile(r"^local unfiltered rescue:\s*[1-9]\d* results")),
    ("searx.space", re.compile(r"^searx\.space: total after lane [1-9]\d*")),
    ("searx.space browser",
     re.compile(r"^searx\.space browser:\s*[1-9]\d* results$")),
    ("searx_fallback merge",
     re.compile(r"^searx_fallback merge:\s*\+[1-9]\d*")),
    ("direct keyless", re.compile(r"^direct keyless:\s*\+[1-9]\d*")),
    ("archive-org",
     re.compile(r"^direct keyless:\s*\+[1-9]\d* "
                r"\([^)]*archive-org[^)]*\)")),
    ("google browser", re.compile(r"^google browser:\s*[1-9]\d* results\b")),
    ("direct catalog",
     re.compile(r"^direct catalog: \S+ (?:rss|sitemap|forum|page) "
                r"\+[1-9]\d*$")),
)

def _lane_keys_from_ladder(records: Any) -> List[str]:
    """Lane keys read off a run's own ladder records: each record whose text
    matches a shape that means that lane ADDED results to the merged pool
    names its lane. Records for 0 results, +0, off-topic-only drops, held
    back, not engaged, or skipped lanes never match, so a lane that ran and
    swept nothing is never attributed as producing. First appearance in the
    records wins the order."""
    keys: List[str] = []
    for rec in (records or []):
        text = str(rec).strip()
        for key, shape in _LANE_ADD_SHAPES:
            if key not in keys and shape.match(text):
                keys.append(key)
    return keys

_LANE_ADD_KEYS = frozenset(key for key, _shape in _LANE_ADD_SHAPES)

def _is_lane_record(rec: Any) -> bool:
    """True when the record's colon prefix names one of the run's search
    lanes (the _LANE_ADD_SHAPES key family, producing or not): run-level
    lane truth keeps priority in the persisted ladder, so per-entity
    detail can never crowd an engaged lane's records out of it."""
    return str(rec or "").split(":", 1)[0].strip() in _LANE_ADD_KEYS

def _engine_attribution(search_result: Optional[Dict[str, Any]],
                        fallback: Optional[List[str]] = None) -> List[str]:
    """Per-search engine attribution for the persisted records: the manager's
    engines_tried KEPT IN THE LEAD, and when the run's own ladder records
    name a producing lane the manager did not report, that lane is appended
    (deduplicated, in first-seen ladder order) so an external lane that
    added rows keeps its credit (the union with the manager's list, not a
    swap).
    When engines_tried itself is empty, the ladder scan stands alone and
    every record that shows results ADDED names its lane key. When no
    ladder record names a producing lane, the caller's selection keeps the
    selection context."""
    result = search_result if isinstance(search_result, dict) else {}
    tried = result.get("engines_tried")
    ladder_keys = _lane_keys_from_ladder(result.get("ladder"))
    if isinstance(tried, list):
        tried_str = [str(e) for e in tried if str(e)]
        if tried_str:
            if not ladder_keys:
                return tried_str
            merged = list(tried_str)
            for key in ladder_keys:
                if key not in merged:
                    merged.append(key)
            return merged
    return (ladder_keys or [str(e) for e in (fallback or [])])

def _pace(key: str) -> float:
    """Pacing helper: doctor.py writes research/tuning.json; its floors rule."""
    return _tuning.scaled(key) if _tuning is not None else 3.0

_FLOOR_HUNT_EXTENSIONS_DEFAULT = 0

def floor_hunt_extensions() -> int:
    """This run's floor-hunt extension allowance: the relevant-floor ladder
    may keep climbing its rungs, but it may extend the run budget for the
    hunt at most GREYSEARCH_FLOOR_HUNT_EXTENSIONS times per run; the
    default 0 hunts inside the budget the run was handed. Junk or negative
    values fall back to the default."""
    try:
        v = int(str(os.environ.get("GREYSEARCH_FLOOR_HUNT_EXTENSIONS", "")
                    or _FLOOR_HUNT_EXTENSIONS_DEFAULT))
    except ValueError:
        v = _FLOOR_HUNT_EXTENSIONS_DEFAULT
    return max(_FLOOR_HUNT_EXTENSIONS_DEFAULT, v)

_POLITENESS_S = 3.0
_THIN_RESULTS_THRESHOLD = 3

_NAV_NOISE = re.compile(
    r"(?i)(skip to content|open our|about us|our etfs|merch\b|contact us|"
    r"subscribe\b|tune into|sign in|log in|trending now|watchlist|"
    r"\bsymbol name\b|\bmenu\b|\bcookie\b|\b×\b|invest now|open education)")
_REPEATED_TOKEN = re.compile(
    r"(\b\w[\w@®™×-]{2,}\b)(?:[ \n,|·:]*\b\1\b){2,}", re.IGNORECASE)

# Named gating constants: the fact extractor (_extract_facts) decides
# which sentences become guide evidence and how many exist; each cap below is
# that decision made explicit.
FACT_MIN_SENTENCE_CHARS = 60   # shorter than this is a fragment, not a fact
FACT_MAX_SENTENCE_CHARS = 500  # longer is narrative prose, not a fact
FACT_MIN_TERM_HITS = 2         # a fact must mention >=2 question terms
FACT_NAV_NOISE_MAX_HITS = 2    # >=2 nav-chrome hits -> menu residue, not prose
FACT_MAX_FACTS = 40            # overall corpus cap after dedupe
# A run accepting fewer pages than this is reported thin ("DATA NOT
# CAPTURED" rather than padding): the warning threshold only; nothing is
# deleted because of it.
THIN_RUN_MIN_ACCEPTED = 3

def _clean_result_url(url: str) -> str:
    """Strip tracking/redirect residue from a search-result URL before it
    can enter any pool: html-escaped ampersands (&amp;, e.g. DuckDuckGo URL
    fragments arriving as '&amp;rut=<hash>'), DuckDuckGo's trailing rut=
    id, utm_* links, bing's msockid session tag. Unescape BEFORE parsing:
    the encoded ampersand would otherwise split a query pair."""
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
    question is NEVER one query (short keyword searches only, never
    long-tail)."""
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
    when it matches ANY entity's tokens (two minimum): a page about one
    entity of a multi-entity question must survive the gate."""
    return [set(re.split(r"[^a-z0-9]+", _s.lower())) - {""}
            for _s in _decompose_query(question)]

def _cap_reason(reason: str, cap: int = 200) -> str:
    """Truncate a composed reason WITHOUT cutting mid-token: a bare [:200]
    slice can produce visually broken strings like "...itself | title )".
    Semicolon-separated segments are whole
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
    two lists, so without this every rejection was listed twice in the
    report (and again on a rerun)."""
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
        self._scrape_wedges = 0
        self._SCRAPE_WEDGE_MAX = 8
        self.scraper = PatchrightScraper(stealth_level="high")
        self.searxng_manager = SearXNGEngineManager()
        self.sites_data = pipeline.SITES
        self.excluded_domains = set(pipeline.EXCLUDED)
        self._last_domain_hit: Dict[str, float] = {}
        self._sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

    def research_scrape(self, url: str, max_chars: int = 0,
                        slot: str = "", mode: Any = None) -> Dict[str, Any]:
        """Scrape a URL on the session's ONE slot browser. max_chars=0/None =
        whole page, never truncated. Truncation happens ONLY when a caller
        explicitly passes a positive max_chars, and it is then FLAGGED via
        truncated=True so no silent truncation can masquerade as ok.
        slot: when a scrape job lands on a scrape-pool worker thread, the
        run's lane binding rides along with the job and pins the worker's
        browser_session resolution (worker threads share no env with the
        runner). mode rides along ONLY for the
        wayback availability consult (SEARCH-class); the scrape transport
        itself stays direct exactly as before. A wayback miss or failure
        carries an honest note next to the original error; a wayback rescue
        returns the ARCHIVED copy with attribution (via_wayback names it)."""
        if slot:
            try:
                import browser_session as _bs_slot
                _bs_slot.set_thread_slot(slot)
            except Exception:
                pass
        start_time = time.time()
        domain = self._extract_domain(url)
        if domain in self.excluded_domains:
            return {"ok": False, "error": f"{domain} is on the excluded list",
                    "url": url, "domain": domain, "tier": "excluded",
                    "truncated": False}

        self._politeness_wait(domain)
        try:
            fetch_result = self.scraper.fetch_url(url, mode=mode)
        except TypeError:
            fetch_result = self.scraper.fetch_url(url)
        scrape_transport = (fetch_result.get("scrape_transport")
                            or _proxy_mode.scrape_guard_note())
        fetch_ok = bool(fetch_result.get("ok"))
        if not fetch_ok:
            err = fetch_result.get("error", "Fetch failed")
            wbnote = str(fetch_result.get("wayback") or "")
            resc = fetch_result.get("via_wayback") or ""
            return {
                "ok": False,
                "url": url,
                "domain": domain,
                "tier": self._get_tier(domain),
                "error": (err + "; wayback: " + wbnote) if wbnote else err,
                "fetched": self._now(),
                "truncated": False,
                **({"via_wayback": resc} if resc else {}),
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
            "scrape_transport": scrape_transport,
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
            **({"via_wayback": str(fetch_result.get("via_wayback") or "")}
               if fetch_result.get("via_wayback") else {}),
            "elapsed_s": fetch_result.get("elapsed_s", round(time.time() - start_time, 2)),
            "key_backends_available": {"patchright": True},
        }

    def _preflight_ping(self, base_url: str,
                        proxy_res: Dict[str, Any]) -> bool:
        """One /healthz ping against a candidate instance: HTTP 200 marks the
        instance ALIVE for this run, any other outcome (non-200, refusal,
        challenge body, timeout, non-HTTP response) counts it dead for THIS
        run. /healthz is an endpoint SearXNG serves; it is NOT a search
        request, so the ping never feeds results and never benches anyone.
        The ping is a SEARCH transport: the opener resolves per call from
        the mode, or the plain default transport when no mode was resolved."""
        try:
            url = f"{str(base_url or '').rstrip('/')}/healthz"
            with _proxy_mode.open_search(
                    url, timeout=_PREFLIGHT_TIMEOUT_S, mode=proxy_res,
                    headers={"User-Agent": "Mozilla/5.0",
                             "Accept": "application/json"}) as resp:
                return bool(getattr(resp, "status", 0) == 200)
        except Exception:
            return False

    def _instance_preflight(self, proxy_res: Dict[str, Any]) -> Dict[str, Any]:
        """PRE-FLIGHT PING: at the start of a deep
        run, before the first public-instance probe, the run pings its
        candidate instance pool on /healthz. Candidates: up to the
        GREYSEARCH_INSTANCE_PROBES cap of the cached searx.space pool,
        starting at the run's rotating offset, taken one at a time at least
        3 s apart with a 5 s timeout each. The alive instances (HTTP 200)
        become this run's pool ordering via the manager's
        set_run_pool_order, so the searches' searx.space probes start from
        them, and the digest line "instance preflight: alive X of Y tried"
        rides the run plan. Nothing raises: a whole-preflight failure is
        recorded as unavailable and the run continues."""
        out: Dict[str, Any] = {"alive": [], "dead": [], "candidates": [],
                               "tried": 0, "elapsed_s": 0.0, "line": ""}
        _t0 = time.time()
        try:
            _cap = _instance_probes()
            _disc = getattr(self.searxng_manager,
                            "_discover_public_instances", None)
            _pin = getattr(self.searxng_manager, "set_run_pool_order", None)
            if callable(_disc):
                candidates = [u for u in _rotate_order(list(
                    _disc(max_instances=_cap, mode=proxy_res) or []))][:_cap]
                out["candidates"] = list(candidates)
                alive: List[str] = []
                dead: List[str] = []
                for i, _base in enumerate(candidates):
                    if i:
                        time.sleep(_PREFLIGHT_GAP_S)
                    if self._preflight_ping(_base, proxy_res):
                        alive.append(_base)
                    else:
                        dead.append(_base)
                out["alive"], out["dead"], out["tried"] = (
                    alive, dead, len(candidates))
                if candidates:
                    out["line"] = (f"instance preflight: "
                                   f"alive {len(alive)} of "
                                   f"{len(candidates)} tried")
                if callable(_pin):
                    _pin(alive)
        except Exception as _pf_err:
            out["line"] = (f"instance preflight: unavailable "
                           f"({type(_pf_err).__name__}: "
                           f"{str(_pf_err)[:80]})")
        out["elapsed_s"] = round(time.time() - _t0, 2)
        return out

    def research_search(self,
                        query: str,
                        category: str = "general",
                        max_results: int = 12,
                        time_range: str = "",
                        language: str = "",
                        engines: Optional[List[str]] = None,
                        search_proxy: Optional[str] = None,
                        floor_hunt_left: Optional[int] = None) -> Dict[str, Any]:
        """Research-oriented search. The SearXNG manager itself now runs the
        automatic ladder (local -> searx.space -> direct keyless); this adds a
        merge of the searx_fallback ladder when local results come back thin
        (< 3), and always records which lanes produced what. Connective words
        are stripped from the search string (never long-tail); the original
        question stays on the result for gate/judge use.

        engines: optional user selection; when non-empty it rides
        BOTH the manager's additive request and the thin-merge fallback search
        (the fallback lane can only accept it in its local query param).

        search_proxy: "off" (default) or "on"; unset
        means GREYSEARCH_SEARCH_PROXY decides. Both ladder surfaces resolve
        their search openers per call from it and record the mode first in
        every ladder; the resolved mode rides back on the result.

        floor_hunt_left: the budget extensions this run still
        has for the relevant-floor hunt (floor_hunt_extensions() minus what
        earlier lanes of the run already took); the manager engages the
        upper rungs either way and only extends the budget when this is
        above 0."""
        search_q = _strip_connectives(query) or query
        search_result = self.searxng_manager.search(
            query=search_q, category=category, max_results=max_results,
            time_range=time_range, language=language, engines=engines,
            search_proxy=search_proxy, floor_hunt_left=floor_hunt_left)

        ladder = list(search_result.get("ladder") or [])
        results = list(search_result.get("results") or [])

        if len(results) < _THIN_RESULTS_THRESHOLD:
            try:
                import searx_fallback as _sf
                lad = _sf.search(query, max_results=max_results,
                                 engines=engines, search_proxy=search_proxy)
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
            "engines_tried": list(
                search_result.get("engines_tried")
                or []) if isinstance(search_result, dict) else [],
            "search_proxy": search_result.get("search_proxy") or "",
            # the manager's floor record rides through so the MCP search-only
            # surface stays honest about the ladder: how many rows answered
            # the question and what floor the ladder hunted toward
            **({"relevant_count": search_result["relevant_count"],
                "relevant_target": search_result["relevant_target"]}
               if "relevant_count" in search_result else {}),
            **({"floor_hunt_extension_used":
                search_result["floor_hunt_extension_used"]}
               if "floor_hunt_extension_used" in search_result else {}),
            **({"search_proxy_error": search_result.get("search_proxy_error")}
               if search_result.get("search_proxy_error") else {}),
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
                      engines: Optional[List[str]] = None,
                      slot: str = "",
                      search_proxy: Optional[str] = None,
                      resume_pool: Optional[List[Dict[str, Any]]] = None,
                      resume_lanes: Optional[List[Dict[str, Any]]] = None,
                      resume_pages: Optional[List[Dict[str, Any]]] = None,
                      page_cb: Optional[Any] = None,
                      site_catalog: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
        def _emit(stage: str, data: Optional[Dict[str, Any]] = None) -> None:
            """Portal/progress hook: never load-bearing, never raises."""
            if progress_cb is None:
                return
            try:
                progress_cb(stage, data or {})
            except Exception:
                pass

        def _page_out(pages_out: List[Dict[str, Any]], pg_start: int) -> None:
            """Judged-page hook: the portal journals each judged batch
            verbatim under runs/pages so a resume can replay it. Never
            load-bearing, never raises."""
            if page_cb is None:
                return
            try:
                page_cb(pages_out, pg_start)
            except Exception:
                pass

        if not resume_pool:
            # on a resume search_done replays the recorded pool before
            # any searching stage would run; the stage stays silent so the
            # story stays honest about what actually happened.
            _emit("searching", {"question": question[:120]})

        """Budget-bounded deep research: search the question (merged engines),
        rank, then scrape up to max_pages within max_total_seconds. Reports
        skipped pages and per-lane outcomes honestly. No fake 'all done'.
        pinned_sources (optional) = exact primary-domain URLs the
        run fetches FIRST (search never reliably surfaces
        registry-primary design domains); each pinned page also contributes
        its top same-site topical links to the pool as primary followers.
        The pool passes a deterministic
        pre-filter; every scraped page is cleaned (page_clean) and judged
        (relevance.judge_pages). pages_fetched is the ACCEPTED corpus ONLY;
        quarantined/rejected pages are reported with reasons and never feed
        facts, prose, tables, citations, or images. Ranking uses the semantic
        score (snippet length is not a signal). Optional kwargs only, so
        frozen importers are unaffected."""
        proxy_res = _proxy_mode.prepared(search_proxy)
        _preflight = self._instance_preflight(proxy_res)
        start_time = time.time()
        deadline = start_time + float(max_total_seconds)
        _budget = float(max_total_seconds)
        search_deadline = start_time + _budget * 0.55
        scrape_deadline = start_time + _budget * 0.85
        page_cap = int(max_pages) if max_pages and max_pages > 0 else DEFAULT_MAX_PAGES
        _floor_hunt_cap = floor_hunt_extensions()
        _floor_hunt_used = 0

        def _floor_hunt_left() -> int:
            """This run's remaining floor-hunt allowance: the budget may be
            extended for the hunt at most the cap times across the whole
            run's search lanes, never per lane."""
            return max(0, _floor_hunt_cap - _floor_hunt_used)

        cats = categories or self._pick_categories(question)
        _sel = _split_selection(engines)

        search_plan: List[Dict[str, Any]] = []
        pool: Dict[str, Dict[str, Any]] = {}
        entity_queries = _decompose_query(question)
        search_plan.append({"category": "decomposition",
                            "query": " → ".join(entity_queries)[:160],
                            "ok": bool(entity_queries), "n": len(entity_queries),
                            "ladder": entity_queries,
                            "engines": list(engines or []),
                            **({"replayed": True} if resume_pool else {})})
        if _preflight.get("line"):
            search_plan.append({"category": "instance-preflight",
                                "query": "(instance pool /healthz ping)",
                                "ok": True,
                                "n": len(_preflight.get("alive") or []),
                                "ladder": [str(_preflight["line"])],
                                "tried": int(_preflight.get("tried") or 0),
                                "elapsed_s": _preflight.get(
                                    "elapsed_s", 0.0)})
        if resume_pool:
            # RESUME: the durable row replays the finished search
            # verbatim, no new searches run. ok:false lanes from the
            # recorded plan re-run their exact query once (bounded 240 s
            # wall each); everything downstream of the pool (relevance
            # gate, pre-filter, rescue top-ups, pre-rank) is re-derived on
            # the merged pool deterministically, identically to a fresh
            # run. resume_pages seeds the scraped corpus after the
            # pre-rank (right where the read loop starts), so an
            # already-read page is never fetched or judged twice and its
            # pg<n> id stays stable (seeds keep their original order,
            # later pages continue the numbering).
            for _r in (resume_pool or [])[:SEARCH_POOL_MAX]:
                if not isinstance(_r, dict) or not _r.get("url"):
                    continue
                _u = str(_r["url"])
                pool.setdefault(_u, {"title": str(_r.get("title") or "")[:200],
                                     "url": _u,
                                     "snippet": str(_r.get("snippet") or "")[:300],
                                     "domain": str(_r.get("domain") or ""),
                                     "tier": str(_r.get("tier") or ""),
                                     "engine": str(_r.get("engine") or "")})
            # lanes recorded in the plan replay too: ok lanes verbatim
            # (replayed marker), ok:false lanes re-run their exact query
            # exactly once, still bounded, so a search that was mid-flight
            # when the run died gets a second and final chance.
            for _lane_rec in ((resume_lanes or [])[:SEARCH_PLAN_MAX]
                              if resume_pool else []):
                if not isinstance(_lane_rec, dict):
                    continue
                _cat = str(_lane_rec.get("category") or "general")
                _lq = str(_lane_rec.get("query") or "")
                if _cat in ("decomposition", "instance-preflight",
                            "(pool topical filter)",
                            "(deterministic URL/title/coverage gate)",
                            "(gate-rejected candidates re-enter; judged "
                            "with body evidence)"):
                    continue
                if _lane_rec.get("ok"):
                    search_plan.append({**_lane_rec, "replayed": True})
                    continue
                _sw = __import__("concurrent.futures", fromlist=["x"])
                _search_pool = _sw.ThreadPoolExecutor(max_workers=1)
                try:
                    _sfut = _search_pool.submit(
                        self.research_search, _lq, category=_cat,
                        max_results=8, engines=_sel["text"],
                        search_proxy=search_proxy,
                        floor_hunt_left=_floor_hunt_left())
                    search_result = _sfut.result(timeout=240.0)
                except Exception as _sw_err:
                    search_result = {"ok": False, "results": [],
                                     "ladder": [f"resume lane re-run "
                                                f"abandoned after "
                                                f"240s wall "
                                                f"({str(_sw_err)[:60]})"]}
                finally:
                    _search_pool.shutdown(wait=False, cancel_futures=True)
                if isinstance(search_result, dict) and \
                        search_result.get("floor_hunt_extension_used"):
                    _floor_hunt_used += 1
                _results = list(search_result.get("results") or [])
                search_plan.append({"category": _cat, "query": _lq,
                                    "ok": search_result.get("ok", False),
                                    "n": len(_results),
                                    "ladder": search_result.get("ladder", []),
                                    "engines": _engine_attribution(
                                        search_result, _sel["text"]),
                                    "rerun": True})
                for result in _results:
                    pool.setdefault(result["url"], result)
        else:
            for i, eq in enumerate(entity_queries):
                cat_i = cats[0] if (cats and i == 0) else "general"
                _sw = __import__("concurrent.futures", fromlist=["x"])
                _search_pool = _sw.ThreadPoolExecutor(max_workers=1)
                try:
                    _sfut = _search_pool.submit(
                        self.research_search, eq, category=cat_i,
                        max_results=8, engines=_sel["text"],
                        search_proxy=search_proxy,
                        floor_hunt_left=_floor_hunt_left())
                    search_result = _sfut.result(timeout=240.0)
                except Exception as _sw_err:
                    search_result = {"ok": False, "results": [],
                                     "ladder": [f"search lane abandoned after "
                                                f"240s wall ({str(_sw_err)[:60]})"]}
                finally:
                    _search_pool.shutdown(wait=False, cancel_futures=True)
                if isinstance(search_result, dict) and \
                        search_result.get("floor_hunt_extension_used"):
                    _floor_hunt_used += 1
                search_plan.append({
                    "category": cat_i,
                    "query": eq,
                    "ok": search_result.get("ok", False),
                    "n": len(search_result.get("results", [])),
                    "ladder": search_result.get("ladder", []),
                    "engines": _engine_attribution(
                        search_result, _sel["text"]),
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

        _ds = None
        _site_catalog = [c for c in (site_catalog or [])
                         if isinstance(c, dict)]
        try:
            import direct_sources as _ds
        except Exception:
            _ds = None
        if _ds is not None and not _site_catalog:
            try:
                _site_catalog = _ds.load_catalog_env()
            except Exception:
                _site_catalog = []
        if _site_catalog and _ds is not None:
            _cat_added = 0
            _cat_lines: List[str] = []
            try:
                _cat = _ds.read_catalog(_site_catalog,
                                        deadline_ts=search_deadline)
                _cat_lines = [str(x) for x in (_cat.get("lines") or [])]
                for _cr in (_cat.get("rows") or []):
                    _cu = str((_cr or {}).get("url") or "")
                    if not _cu or _cu in pool:
                        continue
                    pool[_cu] = {"title": str((_cr or {}).get("title") or "")[:200],
                                 "url": _cu,
                                 "snippet": str((_cr or {}).get("snippet") or "")[:300],
                                 "domain": str((_cr or {}).get("domain") or ""),
                                 "tier": "direct-catalog",
                                 "engine": str((_cr or {}).get("engine") or "")}
                    _cat_added += 1
            except Exception as _cat_err:
                _cat_lines = [f"direct catalog: lane failed "
                              f"({type(_cat_err).__name__}: "
                              f"{str(_cat_err)[:60]})"]
            search_plan.append({"category": "site-catalog",
                                "query": ("(direct-source tier: "
                                          "named-site catalog)"),
                                "ok": bool(_cat_added),
                                "n": _cat_added,
                                "ladder": _cat_lines})

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
            if not _pool_relevant(r) and r.get("engine") != "pinned"
            and r.get("tier") != "direct-catalog"}
        pool = {u: r for u, r in pool.items()
                if _pool_relevant(r) or r.get("engine") == "pinned"
                or r.get("tier") == "direct-catalog"}
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
                                              engines=_sel["news"],
                                              search_proxy=search_proxy,
                                              floor_hunt_left=_floor_hunt_left())
                if rescue.get("floor_hunt_extension_used"):
                    _floor_hunt_used += 1
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
                    "ladder": rescue.get("ladder", []),
                    "engines": _engine_attribution(rescue)})
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

        # Resume seeding: judged page records replayed verbatim keep
        # their verdict, their domain caps and canonical dedupe; an
        # already-read page is never fetched or judged twice. A record
        # without a verdict (never should happen, since the substrate journals
        # judged pages only) quarantines rather than auto-accepts.
        _seed_urls: set = set()
        for _rec in (resume_pages or []):
            _page = _rec.get("page") if isinstance(_rec, dict) \
                and isinstance(_rec.get("page"), dict) else None
            if not _page:
                continue
            _u = str(_page.get("url") or "")
            if not _u or _u in _seed_urls:
                continue
            _seed_urls.add(_u)
            _rel = _page.get("relevance") \
                if isinstance(_page.get("relevance"), dict) else None
            if not _rel:
                _rel = {"decision": "quarantine", "relevance_score": 50,
                        "source_type": _relevance.classify_source_type(
                            str(_page.get("domain") or ""),
                            str(_page.get("tier") or ""),
                            str(_page.get("title") or "")),
                        "reason": "resumed record without a verdict: "
                                  "quarantined, never auto-accepted",
                        "allowed_content": [], "risk_flags": []}
            _page = dict(_page)
            _page["relevance"] = _rel
            _page["_resumed"] = True
            scraped.append(_page)
            _dom = _page.get("domain") or ""
            domain_counts[_dom] = domain_counts.get(_dom, 0) + 1
            _clean = _page.get("clean") \
                if isinstance(_page.get("clean"), dict) else {}
            canonical_seen.add(str(_clean.get("canonical_url") or _u))
        _resumed_n = len(scraped)

        # The search's durable state rides this emit: the ranked pool
        # and the lane plan, slimmed one time here. It lands on the portal's
        # registry row (never the journal) and a resume replays exactly this
        # record: same pool, same lane outcomes, deterministic gating
        # re-derived downstream, seeded pages re-read verbatim.
        _pool_slim = [{"url": r.get("url") or "",
                       "title": (r.get("title") or "")[:200],
                       "snippet": (r.get("snippet") or "")[:300],
                       "domain": r.get("domain") or "",
                       "tier": r.get("tier") or "",
                       "engine": r.get("engine") or ""}
                      for r in ordered[:SEARCH_POOL_MAX] if r.get("url")]
        _plan_slim = [{"category": str(l.get("category") or "")[:48],
                       "query": str(l.get("query") or "")[:160],
                       "ok": bool(l.get("ok")),
                       "n": max(0, int(l.get("n") or 0))}
                      for l in search_plan[:SEARCH_PLAN_MAX]]

        _emit("search_done", {"pool": len(ordered),
                              "search_proxy": (proxy_res.get("mode") or "off"),
                              "plan": _plan_slim,
                              "results": _pool_slim})
        for result in ordered:
            if result["url"] in _seed_urls:
                # This pool entry was read and judged in the earlier
                # attempt; its record replays from runs/pages, nothing is
                # fetched or judged twice.
                skipped.append({"url": result["url"], "decision": "resumed",
                                "reason": "read in the earlier attempt; the "
                                          "judged record was replayed"})
                continue
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
            # snippet-only evidence does not kill a candidate here: coverage
            # scores on a two-line snippet reject whole pages the run never
            # read. Every candidate goes to the scrape
            # lane; the post-scrape judge (same judge, full page body) owns
            # the verdict.
            # WEDGE-PROOF SCRAPE LANE (owner incident 11-10): two LONG-LIVED
            # scrape workers could wedge forever inside patchright's event
            # loop (py-spy: both parked in select()) and every later page
            # then read the "scrape wall" skip — the zero-page "done" runs.
            # Every scrape now runs on a FRESH single-use executor (the same
            # house pattern the resume lane already uses), bounded by its
            # wall; a wedged call is abandoned, its CDP connection dropped,
            # and repeated wedges abandon the browser lane for this run
            # WITHOUT touching the shared browser itself.
            _scrape_wedges = self._scrape_wedges
            if _scrape_wedges >= self._SCRAPE_WEDGE_MAX:
                skipped.append({"url": result["url"], "decision": "deprioritized",
                                "reason": "browser scrape lane abandoned "
                                          f"after {_scrape_wedges} wedges "
                                          "this run (no forced browser respawn)"})
                continue
            _sw2 = __import__("concurrent.futures", fromlist=["x"])
            _scrape_pool = _sw2.ThreadPoolExecutor(max_workers=1)
            try:
                _wall_fut = _scrape_pool.submit(
                    self.research_scrape, result["url"],
                    max_chars=max_chars_per_page
                    if max_chars_per_page and max_chars_per_page > 0 else 0,
                    slot=slot, mode=proxy_res)
                try:
                    scrape_result = _wall_fut.result(timeout=scrape_wall_s)
                except Exception as _wall_err:
                    is_timeout = "timed out" in str(_wall_err) or \
                        "TimeoutError" in type(_wall_err).__name__
                    if is_timeout:
                        _scrape_wedges += 1
                        self._scrape_wedges = _scrape_wedges
                        try:
                            import browser_session as _bs_d
                            _bs_d.drop_connection()
                        except Exception:
                            pass
                    scrape_result = {"ok": False, "url": result["url"],
                                     "error": ("scrape wall ("
                                               + str(scrape_wall_s)
                                               + "s) exceeded"
                                               if is_timeout else
                                               "scrape worker error: "
                                               + str(_wall_err)[:120])}
            finally:
                _scrape_pool.shutdown(wait=False, cancel_futures=True)
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
            if (cleaned.get("boilerplate_ratio", 0)
                    >= _page_clean.BOILERPLATE_KILL_RATIO):
                reason = (f"boilerplate_ratio {cleaned.get('boilerplate_ratio')}"
                          ": page is mostly navigation/chrome")
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
                "via_wayback": str(scrape_result.get("via_wayback") or ""),
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

        search_plan.append({"category": "scrape-transport",
                            "query": "(page scrapes: the slot browser is "
                                     "launched with no proxy env, so page "
                                     "scrapes never ride the search proxy)",
                            "ok": True, "n": len(scraped),
                            "ladder": [_proxy_mode.scrape_guard_note()]})
        quality_warnings: List[str] = []
        judge_ran = False
        if _resumed_n:
            # The judged pages replayed from runs/pages recount
            # themselves as one judged event; the judge below starts after
            # them, so the story stays monotonic and no verdict is re-made.
            _emit("judged", {"judged_so_far": _resumed_n,
                             "of": _resumed_n,
                             "accepted_so_far": sum(
                                 1 for p in scraped[:_resumed_n]
                                 if ((p.get("relevance") or {})
                                     .get("decision")) == "accept"),
                             "start": 0,
                             "replayed": True,
                             "decisions": [str((p.get("relevance") or {})
                                               .get("decision")
                                               or "quarantine")
                                           for p in scraped[:_resumed_n]]})
        if enable_semantic_judge and scraped:
            judge_ran = _relevance.judge_available()
            if not judge_ran:
                time.sleep(2.0)
                judge_ran = _relevance.judge_available()
                if not judge_ran:
                    quality_warnings.append(
                        "judge liveness probe failed twice, all scraped "
                        "pages quarantined (flapped probe)")
            if judge_ran:
                i = _resumed_n
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
                        # the tail the deadline cut off still lands in the
                        # runs/pages substrate, verdicts and all
                        _page_out(scraped[i:], i)
                        _emit("judged", {"judged_so_far": len(scraped),
                                         "of": len(scraped),
                                         "accepted_so_far": sum(
                                             1 for p in scraped
                                             if ((p.get("relevance") or {})
                                                 .get("decision")) == "accept"),
                                         "start": i,
                                         "decisions": [
                                             str((p.get("relevance") or {})
                                                 .get("decision")
                                                 or "quarantine")
                                             for p in scraped[i:]]})
                        break
                    _pg_start = i
                    batch = scraped[i:i + _relevance.JUDGE_BATCH]
                    _judge_batch(question, batch)
                    i += _relevance.JUDGE_BATCH
                    # each judged batch is journaled verbatim the moment its
                    # verdicts exist, the resume never re-reads what is
                    # already on disk
                    _page_out(scraped[_pg_start:i], _pg_start)
                    _d = [p["relevance"] or {} for p in batch]
                    _n_accept = sum(1 for d in _d if d.get("decision") == "accept")
                    _emit("judged", {"judged_so_far": i, "of": len(scraped),
                                     "accepted_so_far": _n_accept,
                                     "start": _pg_start,
                                     "decisions": [str(d.get("decision") or "")
                                                   for d in _d]})
            if not judge_ran:
                for p in scraped:
                    if isinstance(p.get("relevance"), dict):
                        # A replayed seed keeps its recorded verdict
                        continue
                    p["relevance"] = {
                        "decision": "quarantine",
                        "relevance_score": 50,
                        "source_type": _relevance.classify_source_type(
                            p.get("domain", ""), p.get("tier", ""),
                            p.get("title", "")),
                        "reason": "judge_unavailable (judge endpoint down): "
                                  "page quarantined, never auto-accepted",
                        "allowed_content": [], "risk_flags": [],
                    }
                if len(scraped) > _resumed_n:
                    _page_out(scraped[_resumed_n:], _resumed_n)
                _emit("judged", {"judged_so_far": len(scraped),
                                 "of": len(scraped), "accepted_so_far": sum(
                                     1 for p in scraped
                                     if ((p.get("relevance") or {})
                                         .get("decision")) == "accept"),
                                 "start": 0,
                                 "decisions": [str((p.get("relevance") or {})
                                                   .get("decision")
                                                   or "quarantine")
                                               for p in scraped]})

        # Hybrid assist: the rules stay the default and the model is an
        # opt-in tie-breaker (audit gate open AND the NO_MODEL kill switch
        # unset) that sees ONLY pages the deterministic judge scored into its
        # uncertain band. Clean accepts (>=ACCEPT_SCORE) and rejects (<55) are
        # never touched. A promotion must still pass the same deterministic
        # sanity gates as the primary-source exception (not thin, not
        # marketing, contamination clean); band-to-reject moves are the
        # assist's own; anything else (quarantine, unparsable reply, endpoint
        # down) leaves the deterministic verdict standing, so nothing waits on
        # the model and nothing auto-accepts. Moved pages carry "assist":
        # "llm" plus the model's reason; untouched pages stay deterministic.
        _assist_moved: List[Dict[str, Any]] = []
        _assist_tried = 0
        if judge_ran:
            _la = None
            try:
                import llm_audit as _la
            except Exception:
                _la = None
            if _la is not None and _la.model_allowed():
                for p in scraped:
                    rel = p.get("relevance") or {}
                    try:
                        _sc = int(rel.get("relevance_score") or 0)
                    except Exception:
                        _sc = 0
                    if not (_relevance.QUARANTINE_SCORE <= _sc
                            < _relevance.ACCEPT_SCORE):
                        continue
                    _assist_tried += 1
                    try:
                        _ver = _la.judge_assist(
                            question, _judge_view(p),
                            {"decision": rel.get("decision"),
                             "relevance_score": _sc,
                             "reason": rel.get("reason") or ""})
                    except Exception:
                        _ver = None
                    if not isinstance(_ver, dict):
                        continue
                    _nv = _relevance._normalize_decision(
                        _ver, "assist reply unparsable: "
                              "deterministic verdict stands")
                    _aid_reason = str(_ver.get("reason") or
                                      "band tie-break, model-assisted")
                    _moved = None
                    if _nv.get("decision") == "accept":
                        _jv = _judge_view(p)
                        if (not _relevance._page_is_thin(_jv)
                                and not _relevance._is_marketing_or_listicle(
                                    _jv, str(rel.get("source_type") or ""),
                                    list(rel.get("risk_flags") or []))
                                and not (p.get("injection_flags") or [])):
                            _moved = {
                                "decision": "accept",
                                "relevance_score": _relevance.ACCEPT_SCORE,
                                "source_type": str(rel.get("source_type")
                                                   or "unknown"),
                                "reason": ("deterministic judge scored "
                                           f"{_sc}/100 (uncertain band); "
                                           "model tie-break promoted after "
                                           "the sanity gates kept it: "
                                           + _aid_reason),
                                "allowed_content":
                                    list(rel.get("allowed_content") or []),
                                "risk_flags":
                                    list(rel.get("risk_flags") or []),
                                "judge_score": _sc,
                                "assist": "llm",
                                "assist_model": str(_ver.get("model") or ""),
                            }
                    elif _nv.get("decision") == "reject":
                        _moved = {
                            "decision": "reject",
                            "relevance_score": _nv.get("relevance_score"),
                            "source_type": str(rel.get("source_type")
                                               or "unknown"),
                            "reason": ("deterministic judge scored "
                                       f"{_sc}/100 (uncertain band); "
                                       "model tie-break rejected it: "
                                       + _aid_reason),
                            "allowed_content":
                                list(rel.get("allowed_content") or []),
                            "risk_flags": list(rel.get("risk_flags") or []),
                            "judge_score": _sc,
                            "assist": "llm",
                            "assist_model": str(_ver.get("model") or ""),
                        }
                    # a quarantine answer (or an unparsable reply) moves
                    # nothing: the record stays exactly as the judge wrote it
                    if _moved:
                        p["relevance"] = _moved
                        _assist_moved.append({
                            "url": p.get("url") or "",
                            "decision": _moved["decision"],
                            "relevance_score": _moved["relevance_score"],
                            "judge_score": _sc,
                            "reason": _aid_reason[:200],
                            "model": _moved["assist_model"],
                        })
                if _assist_moved or _assist_tried:
                    _emit("assist", {
                        "policy": "opt-in band tie-breaker",
                        "tried": _assist_tried,
                        "moved": len(_assist_moved),
                        "decisions": [m["decision"] for m in _assist_moved],
                        "pages": _assist_moved[:20],
                    })

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

        # SECOND-PASS REFILL: when the judge killed most of the scraped set
        # (junk-heavy search pool burned the page cap), re-open the cap and
        # scrape the urls that were deprioritized by cap — judged by the same
        # semantic judge, same clean gates. Without this, a run can end with
        # 0 accepted pages while the GOOD urls sit in skipped[].
        if len(accepted) < max(2, (max_pages or 0) // 2):
            _cap_blocked = [s["url"] for s in skipped
                            if s.get("decision") == "deprioritized"
                            and "page cap" in str(s.get("reason") or "")]
            _refill_budget = max(60.0, (deadline - time.time()) * 0.7)
            _refill_deadline = min(scrape_deadline, time.time() + _refill_budget)
            for _u in _cap_blocked[:max_pages * 2]:
                if time.time() > _refill_deadline:
                    break
                try:
                    _sr = self.research_scrape(_u, max_chars=max_chars_per_page
                                               if max_chars_per_page and
                                               max_chars_per_page > 0 else 0,
                                               slot=slot, mode=proxy_res)
                except Exception as _e:
                    _sr = {"ok": False, "url": _u,
                           "error": f"refill scrape error: {str(_e)[:100]}"}
                if not _sr.get("ok"):
                    skipped.append({"url": _u, "decision": "reject",
                                    "reason": ("refill: " + str(_sr.get("error") or "scrape failed"))[:160]})
                    continue
                _cl = _page_clean.clean_page(_sr)
                _canon = _cl.get("canonical_url") or _u
                if _canon in canonical_seen or _cl.get("boilerplate_ratio", 0) >= _page_clean.BOILERPLATE_KILL_RATIO:
                    continue
                canonical_seen.add(_canon)
                _pg = {**_sr, "clean": _cl, "relevance": None}
                _rel2 = (_relevance.judge_pages(question, [_pg]) or [{}]) if _relevance.judge_available() else [{}]
                _pg["relevance"] = (_rel2[0] or {}) if isinstance(_rel2, list) and _rel2 else {}
                _dec2 = str((_pg["relevance"] or {}).get("decision") or "quarantine")
                if _dec2 == "accept" and ((_pg["relevance"] or {}).get("relevance_score", 0) >= (min_accept_score if min_accept_score != _relevance.ACCEPT_SCORE else 0)):
                    accepted.append(_pg)
                    skipped.append({"url": _u, "decision": "resumed",
                                    "reason": "second-pass refill scraped+judged"})
                else:
                    rejected.append({"url": _u, "decision": _dec2,
                                     "reason": "refill: " + _cap_reason(((_pg['relevance'] or {}).get('reason') or 'judge reject'))[:120]})

        judged_map = {p["url"]: (p.get("relevance") or {}) for p in accepted}
        accepted = _relevance.rank_results(question, accepted, judged=judged_map)
        for p in accepted:
            if not p.get("title") and p.get("clean", {}).get("title"):
                p["title"] = p["clean"]["title"]

        facts = self._extract_facts(question, accepted)
        elapsed = round(time.time() - start_time, 2)

        if not judge_ran and scraped:
            quality_warnings.append(
                "semantic judge unavailable: all scraped pages quarantined; "
                "the guide will be thin or empty by design")
        if budget_hit:
            quality_warnings.append("run hit its time budget: later pages unjudged/unscraped")
        if _assist_moved:
            quality_warnings.append(
                f"{len(_assist_moved)} band page(s) moved by the opt-in "
                "model-assisted tie-break; every other verdict is the "
                "deterministic judge's")
        if len(accepted) < THIN_RUN_MIN_ACCEPTED:
            quality_warnings.append(
                f"thin run: only {len(accepted)} accepted page(s); the guide "
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
        search_ladder: List[str] = []
        _seen_lrec: set = set()
        _lane_recs: List[str] = []
        _fill_recs: List[str] = []
        for _lane in search_plan:
            if str(_lane.get("category") or "") == "decomposition":
                continue
            for _rec in (_lane.get("ladder") or []):
                _rec = str(_rec).strip()
                if not _rec or _rec in _seen_lrec:
                    continue
                _seen_lrec.add(_rec)
                if _is_lane_record(_rec):
                    _lane_recs.append(_rec)
                else:
                    _fill_recs.append(_rec)
        search_ladder = _lane_recs + _fill_recs
        _slack = SEARCH_LADDER_MAX - len(_lane_recs)
        if 0 <= _slack < len(_fill_recs):
            search_ladder = _lane_recs + _fill_recs[-_slack:]
        search_ladder = search_ladder[-SEARCH_LADDER_MAX:]
        run_report = {
            "query": question,
            "engines": list(engines or []),
            "search_proxy": proxy_res.get("mode") or "",
            "search_proxy_note": _proxy_mode.ladder_note(proxy_res),
            "scrape_transport": _proxy_mode.scrape_guard_note(),
            "search_ladder": list(search_ladder),
            "instance_preflight": _preflight,
            "candidate_count": len(_all_candidates),
            "scraped_count": len(scraped),
            "accepted_count": len(accepted),
            "quarantined_count": len(quarantined),
            "rejected_count": len(rejected),
            "accepted_sources": [p["url"] for p in accepted],
            "skipped_pages": _skipped_pages,
            "quality_warnings": quality_warnings,
            "judge_assist": {"used": bool(_assist_moved),
                             "moved": len(_assist_moved),
                             "tried": _assist_tried,
                             "policy": ("opt-in band tie-breaker (rules "
                                        + "default)") if _assist_moved
                             else "rules (default)"},
        }

        _emit("done", {"accepted": len(accepted), "scraped": len(scraped),
                       "elapsed_s": round(elapsed, 1)})
        return {
            "question": question,
            "categories": cats,
            "engines": list(engines or []),
            "search_proxy": proxy_res.get("mode") or "",
            "search_proxy_note": _proxy_mode.ladder_note(proxy_res),
            "scrape_transport": _proxy_mode.scrape_guard_note(),
            **({"search_proxy_error": proxy_res.get("error")}
               if proxy_res.get("error") else {}),
            "searches": search_plan,
            "search_ladder": list(search_ladder),
            "instance_preflight": _preflight,
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
            "judge_assist": {"used": bool(_assist_moved),
                             "moved": len(_assist_moved),
                             "tried": _assist_tried,
                             "policy": ("opt-in band tie-breaker (rules "
                                        + "default)") if _assist_moved
                             else "rules (default)"},
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
                if not (FACT_MIN_SENTENCE_CHARS <= len(sentence)
                        <= FACT_MAX_SENTENCE_CHARS):
                    continue
                if _NAV_NOISE.search(sentence) and len(sentence.split()) < 14:
                    continue
                if len(_NAV_NOISE.findall(sentence)) >= FACT_NAV_NOISE_MAX_HITS:
                    continue
                if _REPEATED_TOKEN.search(sentence):
                    continue
                low = sentence.lower()
                score = sum(1 for t in q_terms if t in low)
                if score >= FACT_MIN_TERM_HITS:
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
        return out[:FACT_MAX_FACTS]

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
        category ON THE RANKING SIDE, so 'webdesign' is safe to emit."""
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

def research_scrape(url: str, max_chars: int = 0,
                    slot: str = "") -> Dict[str, Any]:
    return get_bridge().research_scrape(url, max_chars=max_chars, slot=slot)

def research_search(query: str,
                    category: str = "general",
                    max_results: int = 12,
                    time_range: str = "",
                    language: str = "",
                    engines: Optional[List[str]] = None,
                    search_proxy: Optional[str] = None) -> Dict[str, Any]:
    return get_bridge().research_search(
        query, category=category, max_results=max_results,
        time_range=time_range, language=language, engines=engines,
        search_proxy=search_proxy)

def research_deep(question: str,
                  categories: Optional[List[str]] = None,
                  max_pages: int = 0,
                  max_chars_per_page: int = 0,
                  max_total_seconds: float = DEFAULT_BUDGET_S,
                  pinned_sources: Optional[List[str]] = None,
                  enable_semantic_judge: bool = True,
                  min_accept_score: int = _relevance.ACCEPT_SCORE,
                  progress_cb: Optional[Any] = None,
                  engines: Optional[List[str]] = None,
                  slot: str = "",
                  search_proxy: Optional[str] = None,
                  resume_pool: Optional[List[Dict[str, Any]]] = None,
                  resume_lanes: Optional[List[Dict[str, Any]]] = None,
                  resume_pages: Optional[List[Dict[str, Any]]] = None,
                  page_cb: Optional[Any] = None,
                  site_catalog: Optional[List[Dict[str, Any]]] = None
                  ) -> Dict[str, Any]:
    return get_bridge().research_deep(
        question, categories=categories, max_pages=max_pages,
        max_chars_per_page=max_chars_per_page,
        max_total_seconds=max_total_seconds,
        pinned_sources=pinned_sources,
        enable_semantic_judge=enable_semantic_judge,
        min_accept_score=min_accept_score, progress_cb=progress_cb,
        engines=engines, slot=slot, search_proxy=search_proxy,
        resume_pool=resume_pool,
        resume_lanes=resume_lanes, resume_pages=resume_pages,
        page_cb=page_cb, site_catalog=site_catalog)

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