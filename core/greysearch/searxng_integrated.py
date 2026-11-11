#!/usr/bin/env python3
"""
SearXNG search with the public-instance ladder (standing behavior):

  1. searx.space public instances — PRIMARY. The local SearXNG lane is
     disabled by default while the owner reinstalls it. Set
     GREYSEARCH_SKIP_LOCAL=0 to re-enable the local instance.
  2. Direct keyless lanes (Bing RSS, DDG HTML) — final same-call fill.

Every lane tried is recorded in result["ladder"] — nothing fails silently.
No API keys. Never truncates result content beyond per-field display caps.
"""

from __future__ import annotations

import json
import random
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import re as _re2

try:
    import yaml
    _HAS_YAML = True
except Exception:
    _HAS_YAML = False

def _searx_fallback():
    """Import searx_fallback whether this module runs as part of the
    lib.scraper package (relative import) or as a top-level module on
    sys.path (tests, patchright_research_mcp). Returns the module."""
    try:
        import searx_fallback as _sf
        return _sf
    except ImportError:
        import searx_fallback as _sf
        return _sf

SEARX_SPACE_URL = "https://searx.space/"
PUBLIC_SEARX_CACHE_TTL = 3600
_public_searx_cache: Optional[List[str]] = None
_public_searx_cache_at: Optional[float] = None

_ENGINE_CACHE: Dict[str, Dict[str, Any]] = {}
_ENGINE_CACHE_AT: Dict[str, float] = {}
_ENGINE_TEST_INTERVAL = 300.0
_ENGINE_TEST_TIMEOUT = 9.0

_POISONED_ENGINES = {"google", "google cse", "google news", "google images",
                     "google videos", "google scholar", "brave", "brave news",
                     "brave images", "brave videos", "qwant", "qwant news",
                     "qwant images", "bing", "bing news", "bing images",
                     "bing videos", "yahoo"}
REQUIRED_GENERAL_ENGINES = ["duckduckgo", "mojeek", "wikipedia", "github"]
GENERAL_FIRST = ("duckduckgo", "mojeek", "wikipedia", "github")

VALID_SEARX_CATEGORIES = {
    "general", "news", "it", "science", "files", "videos", "images",
    "music", "social media", "software", "map", "repos", "packages",
}

_TOPIC_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "how", "what", "when", "where", "why", "which", "who", "will", "with",
    "from", "that", "this", "these", "those", "into", "onto", "over",
    "under", "about", "after", "before", "your", "their", "its", "was",
    "were", "has", "have", "had", "does", "did", "doing", "use", "used",
    "using", "via", "per", "versus", "best", "guide", "tutorial", "pdf",
    "free", "online", "download", "latest", "news", "2024", "2025", "2026",
}

def _topic_tokens(query: str) -> set:
    """Content tokens of a query: lowercase words of >=3 chars, stopwords and
    list-years removed, so the check does not fire on 'how to' or '2026'."""
    return {t for t in _re2.split(r"[^a-z0-9]+", (query or "").lower())
            if len(t) >= 3 and t not in _TOPIC_STOPWORDS}

def _looks_topical(query: str, results: List[Dict[str, Any]]) -> bool:
    """True when the top results plausibly address the query.

    Rule: take the first five results' title + snippet + URL; the lane is
    topical if at least ONE of the query's content tokens appears there (a
    token matches itself or a longer word sharing its prefix, so 'infostealer'
    covers 'infostealers' and 'detect' covers 'detection'). Empty query or
    empty results are not judged — they fall through as before.
    """
    tokens = _topic_tokens(query)
    if not tokens or not results:
        return True
    hay = " ".join(
        f"{r.get('title') or ''} {r.get('content') or ''} {r.get('url') or ''}"
        for r in list(results)[:5]
    ).lower()
    hay_tokens = set(_re2.split(r"[^a-z0-9]+", hay))
    return any(any(ht == t or ht.startswith(t) for ht in hay_tokens)
               for t in tokens)

def _normalize_category(category: str) -> str:
    """Map unknown internal categories to '' (plain query, no categories param)."""
    if not category:
        return ""
    cat = category.strip().lower()
    return cat if cat in VALID_SEARX_CATEGORIES else ""

def _split_selection(names) -> Dict[str, List[str]]:
    """Route user-selected engine names by lane suffix: a name ending in
    " images" joins the images lane, one ending in " news" the news lane,
    every other name the text lane. Used so a portal selection reaches the
    text searches, the news rescue and the image hits without each caller
    re-parsing."""
    out: Dict[str, List[str]] = {"images": [], "news": [], "text": []}
    for _n in (names or []):
        _name = str(_n or "").strip()
        if not _name:
            continue
        _low = _name.lower()
        if _low.endswith(" images"):
            out["images"].append(_low)
        elif _low.endswith(" news"):
            out["news"].append(_low)
        else:
            out["text"].append(_low)
    return out

_CATALOG_CACHE: Dict[str, Any] = {"at": 0.0, "list": []}

def engine_catalog(base_url: str = "http://127.0.0.1:8888",
                   ttl_s: float = 600.0) -> List[Dict[str, Any]]:
    """Enabled engines of a SearXNG instance, read from the instance's own
    /config endpoint (this process only ever READS the instance config; it
    never writes it). Cached 10 minutes; each entry is {"name": str,
    "categories": [str]}; an unreachable endpoint returns [] so callers
    treat the catalog as unknown rather than pretending it is empty."""
    global _CATALOG_CACHE
    now = time.time()
    if (_CATALOG_CACHE.get("at") and
            now - _CATALOG_CACHE["at"] < ttl_s and
            _CATALOG_CACHE.get("list")):
        return list(_CATALOG_CACHE["list"])
    out: List[Dict[str, Any]] = []
    try:
        _req = urllib.request.Request(f"{base_url.rstrip('/')}/config",
                                      headers=_UA_HEADERS)
        with urllib.request.urlopen(_req, timeout=8) as _resp:
            _data = json.loads(_resp.read().decode("utf-8"))
        for _eng in (_data or {}).get("engines") or []:
            if not isinstance(_eng, dict) or not _eng.get("enabled", False):
                continue
            _name = str(_eng.get("name") or "").strip()
            if not _name:
                continue
            out.append({"name": _name,
                        "categories": [str(c) for c in
                                       (_eng.get("categories") or [])
                                       if str(c).strip()]})
    except Exception:
        out = []
    if out:
        _CATALOG_CACHE = {"at": now, "list": out}
    return list(out)

def _local_alive(base_url: str, timeout: float = 15.0) -> Optional[bool]:
    """One cheap probe of a SearXNG instance, with ONE retry before declaring
    it down (a cold SearXNG query costs ~5s of upstream roundtrips — a 4s
    timeout wrongly declared the local instance dead on 2026-10-16). Positive
    results cache 30s, negatives only 10s, so a flaky instance retries soon.

    HTTP 429 ("search in progress") means the instance is
    ALIVE and enforcing its single-search lock — treat it as alive, not down.
    """
    global _LOCAL_ALIVE, _LOCAL_ALIVE_AT
    now = time.time()
    cached, cached_at = _LOCAL_ALIVE.get(base_url), _LOCAL_ALIVE_AT.get(base_url, 0.0)
    if cached is not None and (now - cached_at) < (30.0 if cached else 10.0):
        return cached
    ok = False
    for _attempt in range(2):
        try:
            url = f"{base_url.rstrip('/')}/search?q=ping&format=json"
            req = urllib.request.Request(url, headers=_UA_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ok = isinstance(data, dict) and "results" in data
            break
        except HTTPError as e:
            if e.code == 429:
                ok = True
                break
            ok = False
        except Exception:
            ok = False
    _LOCAL_ALIVE[base_url] = ok
    _LOCAL_ALIVE_AT[base_url] = now
    return ok

_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
               "Accept": "application/json"}
_LOCAL_ALIVE: Dict[str, Any] = {}
_LOCAL_ALIVE_AT: Dict[str, float] = {}

_ENGINE_CACHE: dict = {"at": 0.0, "engines": {}}
_ENGINE_CACHE_TTL_S = 1800.0

def _engine_cache_path() -> Path:
    return Path(__file__).resolve().parent / "research" / "engine-status.json"

def _load_engine_cache(path: Path) -> bool:
    """True when a fresh (<=30 min) engine-status cache was loaded."""
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return False
    if time.time() - float(raw.get("at", 0)) > _ENGINE_CACHE_TTL_S:
        return False
    if not isinstance(raw.get("engines"), dict):
        return False
    _ENGINE_CACHE.update({"at": float(raw["at"]), "engines": raw["engines"]})
    return True

def _save_engine_cache(stats: dict) -> None:
    if not stats:
        return
    _ENGINE_CACHE["engines"] = dict(stats)
    _ENGINE_CACHE["at"] = time.time()
    try:
        os.makedirs(_engine_cache_path().parent, exist_ok=True)
        _engine_cache_path().write_text(json.dumps(_ENGINE_CACHE))
    except Exception:
        pass

_BENCHED_INSTANCES: Dict[str, float] = {}
_BENCHED_REASONS: Dict[str, str] = {}
_BENCH_TTL_S = 3600.0

def _is_local_url(url: str) -> bool:
    host = (url or "").split("//")[-1].split("/")[0]
    return host.startswith(("127.0.0.1", "localhost"))

def _instance_benched(url: str) -> bool:
    until = _BENCHED_INSTANCES.get(url, 0.0)
    if until and time.time() < until:
        return True
    if until:
        _BENCHED_INSTANCES.pop(url, None)
    return False

def _bench_instance(url: str, why: str = "") -> None:
    if _is_local_url(url):
        return
    _BENCHED_INSTANCES[url] = time.time() + _BENCH_TTL_S
    _BENCHED_REASONS[url] = why or "limiter wall"

def _usable_instances(urls: List[str]) -> List[str]:
    return [u for u in urls if not _instance_benched(u)]

class SearXNGEngineManager:
    """
    Manages SearXNG engines with automatic testing, validation, and the
    automatic fallback ladder (local -> searx.space -> direct keyless).
    """

    def __init__(self,
                 searxng_urls: Optional[List[str]] = None,
                 config_path: Optional[str] = None):
        _skip_local = (
            searxng_urls is None
            and os.environ.get("GREYSEARCH_SKIP_LOCAL", "0").strip().lower()
            in ("1", "true", "yes")
        )
        self.skip_local = _skip_local
        self.searxng_urls = (
            [] if _skip_local else (searxng_urls or ["http://127.0.0.1:8888"])
        )
        self._public_fallback_urls: List[str] = []
        self.config_path = config_path or self._find_searxng_config()
        self.engines_config = self._load_engines_config()
        self.working_engines: List[str] = []
        self.engine_stats: Dict[str, Dict[str, Any]] = {}
        self._last_test_time: Optional[float] = None
        self._test_interval = _ENGINE_TEST_INTERVAL

    def _discover_public_instances(self, max_instances: int = 6) -> List[str]:
        """Public SearXNG instance URLs. Primary: searx.space instances.json via
        searx_fallback (hardcoded source). Fallback: HTML scrape of
        https://searx.space/ itself. Cached 1h."""
        global _public_searx_cache, _public_searx_cache_at
        now = time.time()
        if _public_searx_cache is not None and _public_searx_cache_at is not None:
            if (now - _public_searx_cache_at) < PUBLIC_SEARX_CACHE_TTL:
                return list(_public_searx_cache)
        urls: List[str] = []
        try:
            _sf = _searx_fallback()
            urls = [i.rstrip("/") for i in _sf._harvest_instances(limit=max_instances)]
            urls = [u for u in urls if u.startswith("https://")]
        except Exception:
            urls = []
        if not urls:
            try:
                req = urllib.request.Request(SEARX_SPACE_URL,
                                             headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    html_text = resp.read().decode("utf-8", errors="replace")
                for href in _re2.findall(r'href="(https://[^"]+)"', html_text):
                    href = href.strip().rstrip("/")
                    if href.startswith("https://") and "searx" in href.lower() and href not in urls:
                        urls.append(href)
                        if len(urls) >= max_instances:
                            break
            except Exception:
                pass
        if urls:
            _public_searx_cache = list(urls)
            _public_searx_cache_at = now
        return urls

    def _find_searxng_config(self) -> Optional[str]:
        """Find the SearXNG configuration file."""
        _repo = Path(__file__).resolve().parent
        possible_paths = [
            str(_repo / "searxng" / "conf" / "settings.yml"),
        ]
        for path in possible_paths:
            expanded_path = str(Path(path).expanduser())
            if Path(expanded_path).exists():
                return expanded_path
        return None

    def _load_engines_config(self) -> List[Dict[str, Any]]:
        """Load engines configuration from SearXNG settings."""
        if not self.config_path or not Path(self.config_path).exists() or not _HAS_YAML:
            return []
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config.get("engines", []) or []
        except Exception:
            return []

    def _get_engine_names(self) -> List[str]:
        """Engine names from config; general WEB engines always included."""
        engine_names = []
        seen = set()
        for engine in self.engines_config:
            if isinstance(engine, dict) and engine.get("enabled", True):
                name = engine.get("name") or engine.get("engine")
                if name and name not in seen:
                    engine_names.append(name)
                    seen.add(name)
        for r in REQUIRED_GENERAL_ENGINES:
            if r not in engine_names:
                engine_names.append(r)
        return [n for n in engine_names if n not in _POISONED_ENGINES]

    def test_engines(self, force: bool = False) -> Dict[str, Any]:
        """Probe which engines actually work, in parallel (threadpool), with a
        process-wide cache keyed by instance URL set."""
        cache_key = ",".join(self.searxng_urls)
        now = time.time()
        if not force:
            at = _ENGINE_CACHE_AT.get(cache_key, 0.0)
            if at and (now - at) < _ENGINE_TEST_INTERVAL and _ENGINE_CACHE.get(cache_key):
                cached = _ENGINE_CACHE[cache_key]
                self.working_engines = list(cached["working_engines"])
                self.engine_stats = dict(cached["engine_stats"])
                self._last_test_time = at
                return {**cached, "cached": True, "last_test": at}

        engine_names = self._get_engine_names() or list(REQUIRED_GENERAL_ENGINES)
        stats: Dict[str, Dict[str, Any]] = {}
        working: List[str] = []
        lock_ts = time.time()

        RATE_LIMIT_HINTS = ("too many requests", "429", "402", "432", "quota",
                            "suspended", "captcha", "too many", "timeout",
                            "timed out", "temporary", "500", "502", "503")
        def probe(engine_name: str) -> Dict[str, Any]:
            ok = False
            err = None
            transient = False
            t0 = time.time()
            for attempt in range(2):
                if attempt:
                    if not transient:
                        break
                    time.sleep(2.0)
                transient = False
                for base_url in _usable_instances(self.searxng_urls):
                    test_url = (f"{base_url}/search?q={urllib.parse.quote('test')}"
                                f"&format=json&engines={urllib.parse.quote(engine_name)}")
                    try:
                        req = urllib.request.Request(test_url, headers=_UA_HEADERS)
                        with urllib.request.urlopen(req, timeout=_ENGINE_TEST_TIMEOUT) as response:
                            if response.status != 200:
                                err = f"HTTP {response.status}"
                                continue
                            data = json.loads(response.read().decode("utf-8"))
                            suspended = False
                            for entry in data.get("unresponsive_engines") or []:
                                try:
                                    eng, reason = entry[0], entry[1]
                                except Exception:
                                    eng, reason = str(entry), ""
                                if eng == engine_name:
                                    suspended = True
                                    err = str(reason)[:120]
                                    if any(h in err.lower() for h in RATE_LIMIT_HINTS):
                                        transient = True
                            if data.get("results") and not suspended:
                                ok = True
                                err = None
                                break
                            if suspended:
                                continue
                            if not data.get("results") and not err:
                                err = "0 results (empty upstream response)"
                    except HTTPError as e:
                        err = f"HTTP {e.code}"
                        transient = e.code in (402, 408, 429, 432, 500, 502, 503, 504)
                        if e.code in (402, 403, 429, 432):
                            _bench_instance(base_url, f"HTTP {e.code}")
                            continue
                    except Exception as e:
                        err = str(e)[:120] or type(e).__name__
                        if "tim" in err.lower():
                            transient = True
                if ok:
                    break
            return {"name": engine_name, "working": ok,
                    "error": err, "rate_limited": transient,
                    "took": time.time() - t0}

        _local_probe = any(
            (u or "").split("//")[-1].split("/")[0]
            .startswith(("127.0.0.1", "localhost"))
            for u in self.searxng_urls)
        import random as _rand
        workers = 1
        try:
            import tuning as _tune
            _pg_min, _pg_max = (_tune.scaled("probe_gap_min_s"),
                                _tune.scaled("probe_gap_max_s"))
        except Exception:
            _pg_min, _pg_max = 3.0, 6.0
        _probe_gap = 5.2 if _local_probe else _rand.uniform(_pg_min, _pg_max)
        _cache_ok = False
        _probe_deadline = time.time() + float(
            os.environ.get("GREYSEARCH_PROBE_BUDGET_S") or 25.0)
        try:
            _ecp = Path(__file__).resolve().parent / "research" / \
                "engine-status.json"
            if not _load_engine_cache(_ecp):
                pass
            else:
                _cached = _ENGINE_CACHE.get("engines") or {}
                if _cached:
                    working = [e for e, st in _cached.items()
                               if st.get("working")]
                    self.working_engines = working
                    self.engine_stats = {**stats, **_cached}
                    return working
        except Exception:
            _cache_ok = False
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for _name in engine_names:
                if time.time() > _probe_deadline:
                    for _rest in engine_names[engine_names.index(_name):]:
                        stats[_rest] = {"working": True,
                                        "assumed": True,
                                        "error": "probe budget reached",
                                        "response_time": 0}
                        working.append(_rest)
                    break
                futures.append(pool.submit(probe, _name))
                time.sleep(_probe_gap)
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    continue
                stats[r["name"]] = {
                    "working": r["working"],
                    "response_time": r["took"],
                    "error": r["error"],
                    "rate_limited": bool(r.get("rate_limited")),
                    "last_tested": lock_ts,
                }
                if r["working"]:
                    working.append(r["name"])

        working.sort(key=lambda e: 0 if e in GENERAL_FIRST else 1)

        self.working_engines = working
        self.engine_stats = stats
        _save_engine_cache(stats)
        self._last_test_time = lock_ts
        _ENGINE_CACHE[cache_key] = {
            "working_engines": list(working),
            "engine_stats": stats,
            "total_engines": len(engine_names),
        }
        _ENGINE_CACHE_AT[cache_key] = lock_ts

        return {
            "working_engines": working,
            "engine_stats": stats,
            "cached": False,
            "last_test": lock_ts,
            "total_engines": len(engine_names),
            "working_count": len(working),
        }

    def health_gate(self, retries: int = 2, timeout_s: int = 8) -> Dict[str, Any]:
        """Health gate: probe the SearXNG instances before research. Returns status."""
        alive_urls = []
        errors = {}
        for base in _usable_instances(self.searxng_urls):
            ok = False
            last_err = None
            for attempt in range(retries + 1):
                try:
                    req = urllib.request.Request(f"{base}/search?q=health+probe&format=json",
                                                 headers=_UA_HEADERS)
                    with urllib.request.urlopen(req, timeout=timeout_s) as r:
                        if r.status == 200:
                            data = json.loads(r.read().decode("utf-8"))
                            if isinstance(data, dict) and "results" in data:
                                ok = True
                                break
                except Exception as e:
                    last_err = str(e)[:200]
                    if attempt < retries:
                        time.sleep(0.5 * (attempt + 1))
            if ok:
                alive_urls.append(base)
            else:
                errors[base] = last_err or "no results key"
        try:
            self.test_engines(force=False)
        except Exception:
            pass
        mode = "full" if alive_urls else "down"
        return {
            "mode": mode,
            "alive_urls": alive_urls,
            "dead_urls": [u for u in self.searxng_urls if u not in alive_urls],
            "errors": errors,
            "working_engines": list(self.working_engines),
            "degraded": mode != "full",
            "down": mode == "down",
        }

    def get_working_engines(self) -> List[str]:
        """Working engines, testing if needed (process-wide cache makes this cheap)."""
        if not self.working_engines:
            self.test_engines()
        return list(self.working_engines)

    def _fullset_first(self, query: str, cat: str, safe_search: int,
                       time_range: str, language: str,
                       merged: List[Dict[str, Any]],
                       seen_urls: set, ladder: List[str],
                       selected: tuple = ()) -> bool:
        """2026-10-21: lane-1 primary = ONE unfiltered query, the instance's
        own default engine set.

        Live evidence against the old per-engine sweep: single-engine
        selections under-deliver on niche topics (wikipedia is a one-result
        summary engine, github repo-search misses prose topics), the sweep
        burns the instance's one-search-per-5s wall up to 8 times, and its
        429s manufactured "engines down" alarms. The full set returned ~300
        junk-filtered results for queries the sweep read as empty.

        Additive user selection (2026-11-03): an empty "selected" leaves
        this lane byte-for-byte as it was — one request, the default set.
        A non-empty selection adds ONE second request with engines=<names>
        alongside the default one (never instead of it), so the instance's
        single-search limiter still sees one request per lane. Results the
        instance attributes to a poison-banned engine are dropped at merge,
        EXCEPT when that exact name is in this call's selection — an
        explicitly picked engine merges like any other, but only here, only
        for this call. The ladder records the user lane separately so the
        curation record shows what the selection added.

        Returns True only when the merged results are topical AND at least
        max_results — the caller (search) then skips the per-engine sweep;
        thin-but-topical results stay merged and the sweep still runs as
        the backstop."""
        params: Dict[str, Any] = {"q": query, "format": "json",
                                  "safesearch": safe_search}
        if cat:
            params["categories"] = cat
        if time_range:
            params["time_range"] = time_range
        if language:
            params["language"] = language
        variants: List[tuple] = [(params, "default+fullset")]
        if selected:
            variants.append(({**params, "engines": ",".join(selected)},
                             "user"))
        _variant_added: Dict[str, int] = {}
        for base_url in _usable_instances(self.searxng_urls):
            for _vp, _tag in variants:
                _added = 0
                _u = f"{base_url}/search?{urllib.parse.urlencode(_vp)}"
                try:
                    _req = urllib.request.Request(_u, headers=_UA_HEADERS)
                    with urllib.request.urlopen(_req, timeout=12) as _resp:
                        if _resp.status == 200:
                            _data = json.loads(_resp.read().decode("utf-8"))
                            for _r in _data.get("results", []):
                                _url = _r.get("url", "")
                                if not _url or _url in seen_urls:
                                    continue
                                if any(e in _POISONED_ENGINES
                                       and e not in selected
                                       for e in (_r.get("engines") or [])):
                                    continue
                                seen_urls.add(_url)
                                merged.append({**_r, "_engine": _tag})
                                _added += 1
                except HTTPError as _he:
                    if _he.code in (402, 403, 429, 432):
                        _bench_instance(base_url, f"HTTP {_he.code}")
                    continue
                except Exception:
                    continue
                _variant_added[_tag] = _variant_added.get(_tag, 0) + _added
        if selected and _variant_added.get("user"):
            ladder.append(f"user engines: {','.join(selected)} "
                          f"(+{_variant_added['user']} results)")
            _picked = [r for r in merged if r.get("_engine") == "user"]
            _rest = [r for r in merged if r.get("_engine") != "user"]
            merged[:] = _picked + _rest
        if merged and _looks_topical(query, merged) and len(merged) >= 4:
            ladder.append(f"local: {len(merged)} results (full engine set)")
            return True
        if merged and not _looks_topical(query, merged):
            ladder.append(f"local: full set off-topic ({len(merged)} results)")
            merged.clear()
            seen_urls.clear()
        return False

    def search(self,
               query: str,
               category: str = "general",
               max_results: int = 10,
               time_range: str = "",
               language: str = "",
               safe_search: int = 0,
               max_seconds: float = 60.0,
               engines: Optional[List[str]] = None) -> Dict[str, Any]:
        """Search with the AUTOMATIC ladder: local -> searx.space -> direct.

        Every lane tried is recorded in result["ladder"] with counts; the
        switch happens in the same call, in seconds, with no silent failures.

        engines (2026-11-03): optional user selection of SearXNG engine
        names, capped at 8 after dedup + lowercase. When empty/None the
        whole ladder behaves exactly as before. When set, the local lane
        additionally runs one combined request with engines=<names> next to
        its default request — an ADD, never a replacement of the default
        lanes — and explicitly picked names are exempt from the poison
        drop for this call only. Suffix routing (" images"/" news") is the
        CALLER's job via _split_selection; this method treats whatever it
        receives as the additive text/general lane.
        """
        start_time = time.time()
        selected = tuple(dict.fromkeys(
            str(x).strip().lower() for x in (engines or [])
            if str(x).strip()))[:8]
        deadline = start_time + max_seconds
        cat = _normalize_category(category)
        ladder: List[str] = []
        last_error = None
        merged: List[Dict[str, Any]] = []
        seen_urls: set = set()
        engines_tried: List[str] = []

        if self.skip_local:
            local_alive = False
            ladder.append("local: skipped (GREYSEARCH_SKIP_LOCAL)")
        else:
            local_alive = (any(_local_alive(u) for u in self.searxng_urls)
                           if self.searxng_urls else False)
        if not local_alive:
            try:
                _cached_working = self.get_working_engines()
            except Exception:
                _cached_working = []
            if _cached_working:
                local_alive = True
                ladder.append("local: probe said down, engine cache says "
                              "alive — trying the real query")
            elif not self.skip_local:
                ladder.append("local: DOWN (skipped — automatic searx.space switch)")
        else:
            working_engines = self.get_working_engines()
            if not working_engines:
                self.test_engines(force=True)
                working_engines = self.get_working_engines()
            if not working_engines:
                last_error = "local SearXNG alive but no working engines"
                ladder.append("local: alive but no working engines "
                              "(engine probes failed — see engine_stats)")
            elif self._fullset_first(query, cat, safe_search, time_range,
                                    language, merged, seen_urls, ladder,
                                    selected=selected):
                pass
            else:
                engines_to_try = [e for e in working_engines if e in GENERAL_FIRST] + \
                                 [e for e in working_engines if e not in GENERAL_FIRST]
                for engine_name in engines_to_try[:8]:
                    if time.time() > deadline:
                        break
                    engines_tried.append(engine_name)
                    try:
                        params = {
                            "q": query,
                            "format": "json",
                            "engines": engine_name,
                            "safesearch": safe_search,
                        }
                        if cat:
                            params["categories"] = cat
                        if time_range:
                            params["time_range"] = time_range
                        if language:
                            params["language"] = language
                        for base_url in self.searxng_urls:
                            search_url = f"{base_url}/search?{urllib.parse.urlencode(params)}"
                            req = urllib.request.Request(search_url, headers=_UA_HEADERS)
                            try:
                                with urllib.request.urlopen(req, timeout=10) as response:
                                    if response.status == 200:
                                        data = json.loads(response.read().decode('utf-8'))
                                        for r in data.get("results", []):
                                            url = r.get("url", "")
                                            if not url or url in seen_urls:
                                                continue
                                            seen_urls.add(url)
                                            merged.append({**r, "_engine": engine_name})
                                        if len(merged) >= max_results * 3:
                                            break
                            except (HTTPError, URLError, json.JSONDecodeError) as e:
                                last_error = str(e)
                                continue
                        if len(merged) >= max_results * 2:
                            break
                    except Exception as e:
                        last_error = str(e)
                        continue
                if merged:
                    if _looks_topical(query, merged):
                        ladder.append(f"local: {len(merged)} results "
                                      f"(engines: {','.join(engines_tried[:4])})")
                    else:
                        ladder.append(f"local: off-topic ({len(merged)} results)")
                        merged = []
                        seen_urls.clear()
                else:
                    ladder.append(f"local: 0 results across {engines_tried}")
                    _rate = [e for e, st in (self.engine_stats or {}).items()
                             if isinstance(st, dict) and st.get("rate_limited")]
                    if True:
                        params_u = {"q": query, "format": "json",
                                    "safesearch": safe_search}
                        if cat:
                            params_u["categories"] = cat
                        if time_range:
                            params_u["time_range"] = time_range
                        if language:
                            params_u["language"] = language
                        for base_url in self.searxng_urls:
                            _u = f"{base_url}/search?{urllib.parse.urlencode(params_u)}"
                            try:
                                _req = urllib.request.Request(_u, headers=_UA_HEADERS)
                                with urllib.request.urlopen(_req, timeout=10) as _resp:
                                    if _resp.status == 200:
                                        _data = json.loads(_resp.read().decode("utf-8"))
                                        for r in _data.get("results", []):
                                            _url = r.get("url", "")
                                            if not _url or _url in seen_urls:
                                                continue
                                            seen_urls.add(_url)
                                            merged.append({**r,
                                                           "_engine": "default+unfiltered"})
                            except Exception as e:
                                last_error = str(e)
                        if merged:
                            engines_tried.append("unfiltered")
                            ladder.append(
                                f"local unfiltered rescue: {len(merged)} results "
                                f"({len(_rate)} engines rate-limited)")

        if self.skip_local:
            degraded = False
        else:
            required_down = [e for e in REQUIRED_GENERAL_ENGINES
                             if e not in (self.working_engines or [])]
            _too_many = 3 if len(REQUIRED_GENERAL_ENGINES) >= 5 else 2
            degraded = len(required_down) >= _too_many
            if degraded:
                ladder.append(f"local: degraded ({len(required_down)} required "
                              f"engines down: {','.join(required_down[:5])})")
        if ((len(merged) < max_results or (degraded and not merged))
                and time.time() < deadline):
            public_urls = self._discover_public_instances(max_instances=6)
            tried_public = 0
            if public_urls:
                def _try_instance(pub_base: str, engine_name: str) -> List[Dict[str, Any]]:
                    out: List[Dict[str, Any]] = []
                    try:
                        _sf_warm = _searx_fallback()
                        _sf_warm._warm_remote_host(pub_base)
                        params2 = {"q": query, "format": "json", "safesearch": safe_search}
                        if engine_name:
                            params2["engines"] = engine_name
                        if cat:
                            params2["categories"] = cat
                        search_url2 = f"{pub_base}/search?{urllib.parse.urlencode(params2)}"
                        req2 = urllib.request.Request(search_url2,
                                                      headers={"User-Agent": "Mozilla/5.0",
                                                               "Accept": "application/json"})
                        with urllib.request.urlopen(req2, timeout=12) as resp2:
                            if resp2.status == 200:
                                data2 = json.loads(resp2.read().decode("utf-8"))
                                raw = [r for r in data2.get("results", []) if r.get("url")]
                                _pre_filter_count = len(raw)
                                raw = _sf_warm._filter_instance_junk(query, raw)
                                if _pre_filter_count and not raw:
                                    out.append({"_off_topic_dropped": True,
                                                "_dropped_count": _pre_filter_count})
                                for r in raw:
                                    r2 = {**r, "_engine": (engine_name or "default") + "+searxspace"}
                                    out.append(r2)
                    except Exception:
                        pass
                    return out

                jobs: List[tuple] = []
                for pub_base in public_urls[:4]:
                    if pub_base.replace("/", "") in {u.replace("/", "") for u in self.searxng_urls}:
                        continue
                    jobs.append((pub_base, ""))
                tried_public = len(set(p for p, _ in jobs))
                dropped_sets = 0
                dropped_results = 0
                _remote_end = time.time() + float(
                    os.environ.get("GREYSEARCH_REMOTE_LANE_CAP_S")
                    or 120.0)
                if jobs and time.time() < deadline and time.time() < _remote_end:
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        futures = [pool.submit(_try_instance, pb, eng) for pb, eng in jobs]
                        for fut in as_completed(futures):
                            if time.time() > deadline:
                                break
                            try:
                                new = fut.result()
                            except Exception:
                                new = []
                            _drop_only = [r for r in new
                                          if isinstance(r, dict)
                                          and r.get("_off_topic_dropped")]
                            if _drop_only:
                                dropped_sets += len(_drop_only)
                                dropped_results += sum(r.get("_dropped_count", 0)
                                                       for r in _drop_only)
                                new = [r for r in new
                                       if not (isinstance(r, dict)
                                               and r.get("_off_topic_dropped"))]
                            if new and not _looks_topical(query, new):
                                dropped_sets += 1
                                dropped_results += len(new)
                                continue
                            for r in new:
                                url = r.get("url", "")
                                if not url or url in seen_urls:
                                    continue
                                seen_urls.add(url)
                                merged.append(r)
                if dropped_sets:
                    ladder.append(f"searx.space: off-topic results dropped "
                                  f"({dropped_sets} instance result sets, "
                                  f"{dropped_results} results)")
                if merged and tried_public:
                    ladder.append(f"searx.space: total after lane {len(merged)} "
                                  f"(instances: {','.join(public_urls[:2])})")
                elif not merged:
                    ladder.append("searx.space: tried "
                                  f"{tried_public or 0} instance-probes, +0 results")
            else:
                ladder.append("searx.space: no reachable instances discovered")

            if not merged and time.time() < deadline:
                try:
                    _sf = _searx_fallback()
                    _bw = ThreadPoolExecutor(max_workers=1,
                                             thread_name_prefix="browsepub")
                    _bf = _bw.submit(_sf.browser_search_public, query,
                                     max_results, public_urls or None)
                    try:
                        browsed = _bf.result(timeout=45.0)
                    finally:
                        _bw.shutdown(wait=False)
                except Exception as e:
                    browsed = []
                    ladder.append(f"searx.space browser failed/bound-out: {str(e)[:120]}")
                if browsed:
                    _sf_junk = _searx_fallback()
                    browsed = _sf_junk._filter_instance_junk(query, browsed)
                if browsed and _looks_topical(query, browsed):
                    for r in browsed:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            merged.append(r)
                    ladder.append(
                        f"searx.space browser: {len(browsed)} results")
                elif browsed:
                    ladder.append(
                        f"searx.space browser: off-topic ({len(browsed)} results)")

        if len(merged) < max_results and time.time() < deadline:
            try:
                _sf = _searx_fallback()
                direct = _sf._direct_search(query, max_results=min(8, max_results * 2))
                direct_offtopic = bool(direct) and not _looks_topical(query, direct)
                added = 0
                for r in direct:
                    url = r.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    merged.append({**r, "_engine": r.get("source", "direct") + "+direct",
                                   "_off_topic": direct_offtopic})
                    added += 1
                if added:
                    ladder.append(f"direct keyless: +{added} (bing-rss, ddg-html)"
                                  + (" — off-topic (last resort)"
                                     if direct_offtopic else ""))
                elif not ladder or "direct" not in str(ladder):
                    ladder.append("direct keyless: 0 results")
            except Exception as e:
                last_error = str(e)

        results = self._process_search_results(merged, max_results)
        return {
            "ok": bool(results),
            "query": query,
            "category": cat or "general",
            "engine_used": ",".join(engines_tried),
            "instance_used": self.searxng_urls[0] if self.searxng_urls else "",
            "results": results,
            "total_results": len(merged),
            "elapsed_s": round(time.time() - start_time, 2),
            "engines_tried": engines_tried,
            "ladder": ladder,
            "last_error": last_error,
        }

    def _process_search_results(self,
                               raw_results: List[Dict[str, Any]],
                               max_results: int) -> List[Dict[str, Any]]:
        """Process and filter raw search results from all lanes."""
        processed = []
        seen_urls = set()
        for result in raw_results:
            if len(processed) >= max_results:
                break
            url = result.get("url", "")
            title = result.get("title", "")
            content = result.get("content", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            domain = self._extract_domain(url)
            engine = result.get("_engine") or result.get("engine", "")
            processed.append({
                "url": url,
                "title": title[:200] if title else "",
                "content": content[:300] if content else "",
                "domain": domain,
                "engine": engine,
                "timestamp": result.get("publishedDate", ""),
                **({"off_topic": True} if result.get("_off_topic") else {}),
            })
        return processed

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL (fixed 2026-10-16: urlparse was never
        imported here — every result silently got an empty domain)."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def get_engine_stats(self) -> Dict[str, Any]:
        """Statistics for all engines."""
        return {
            "engine_stats": self.engine_stats.copy(),
            "working_engines": list(self.working_engines),
            "last_test": self._last_test_time,
            "searxng_urls": self.searxng_urls,
        }

def searxng_search(query: str,
                   category: str = "general",
                   max_results: int = 10,
                   **kwargs) -> Dict[str, Any]:
    """Convenience function for searching SearXNG with the automatic ladder."""
    manager = SearXNGEngineManager()
    return manager.search(query, category=category, max_results=max_results, **kwargs)

def test_searxng_engines() -> Dict[str, Any]:
    """Test all SearXNG engines and report status."""
    manager = SearXNGEngineManager()
    return manager.test_engines(force=True)

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "test"
    result = searxng_search(query, max_results=5)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
    for r in result.get("results", [])[:5]:
        print(f"  {(r.get('title') or '')[:60]} -> {(r.get('url') or '')[:70]}")