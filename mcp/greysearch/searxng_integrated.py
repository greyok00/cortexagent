#!/usr/bin/env python3
"""
SearXNG-integrated search lanes, the standing contract: the local SearXNG
instance runs first (GREYSEARCH_SKIP_LOCAL parks it for a call), the
searx.space public-instance co-lane always attempts beside it on every
search, and direct keyless lanes (DDG HTML, Wikipedia/GitHub APIs) back the
pair up inside the same call. The browser rung (searx.space instance pages
and the Google rung) waits out captchas in bounded phases and records what
happened. A manual proxy mode covers search hops only; page scrapes always
run direct on the slot browser.

Every lane attempt, rescue and skip is recorded in result["ladder"] so
nothing fails silently. No API keys are required - every lane is keyless.
Result content is never truncated beyond per-field display caps.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import proxy_mode as _proxy_mode
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
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
SEARX_SPACE_DATA_URL = "https://searx.space/data/instances.json"
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
_GOOGLE_BROWSER_TAG = "https://www.google.com"

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
    empty results are not judged, so they fall through as before.
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
    it down (a cold SearXNG query costs ~5s of upstream roundtrips, so a 4s
    timeout can wrongly declare the local instance dead). Positive results
    cache 30s, negatives only 10s, so a flaky instance retries soon.

    HTTP 429 ("search in progress") means the instance is
    ALIVE and enforcing its single-search lock, so treat it as alive, not
    down.
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

_INSTANCE_PROBES_DEFAULT = 12
_ROTATION_N = {"n": 0}

def _instance_probes() -> int:
    """Per-search public-instance probe cap: the rule is to cycle through
    the discovered pool instead of bombarding one site. Env
    GREYSEARCH_INSTANCE_PROBES overrides, 12 by default, at least 1."""
    try:
        return max(1, int(str(os.environ.get("GREYSEARCH_INSTANCE_PROBES", "")
                                  or _INSTANCE_PROBES_DEFAULT)))
    except ValueError:
        return _INSTANCE_PROBES_DEFAULT

def _rotate_order(pool: List[str]) -> List[str]:
    """A probe order for one engagement: the same pool starting at a
    rotating offset. The offset advances on every call with something to
    rotate, so consecutive runs and consecutive searches start further
    into the pool and the request pressure spreads across it. A pool of
    one or zero has nothing to rotate."""
    urls = [str(u or "").rstrip("/") for u in (pool or [])]
    urls = [u for u in urls if u]
    if len(urls) <= 1:
        return urls
    off = _ROTATION_N["n"] % len(urls)
    _ROTATION_N["n"] += 1
    return urls[off:] + urls[:off]

_RELEVANT_TARGET_DEFAULT = 20
_FLOOR_HUNT_EXTENSIONS_DEFAULT = 0

def _relevant_target() -> int:
    """The relevant-result floor a search hunts to: a search should return
    at least 20 results that read as relevant, measured heuristically. Env
    GREYSEARCH_RELEVANT_TARGET overrides."""
    try:
        v = int(str(os.environ.get("GREYSEARCH_RELEVANT_TARGET", "")
                    or _RELEVANT_TARGET_DEFAULT))
    except ValueError:
        v = _RELEVANT_TARGET_DEFAULT
    return max(1, v)

def _floor_extend_s() -> float:
    """Extra seconds added to a search's deadline when the relevant floor
    is unmet (the upper rungs need the searx.space settle waits)."""
    try:
        return max(0.0, float(str(os.environ.get("GREYSEARCH_FLOOR_EXTEND_S",
                                                  "") or 240.0)))
    except ValueError:
        return 240.0

def _floor_hunt_cap() -> int:
    """How many times a relevant-floor hunt may extend the search budget
    (GREYSEARCH_FLOOR_HUNT_EXTENSIONS, default 0: the upper rungs stay
    engaged but the hunt runs within the budget it was handed; junk or
    negative values fall back to the default). The per-run allowance is the
    caller's (research_deep passes what the run has left); a caller that
    passes none rides this manager's own count."""
    try:
        v = int(str(os.environ.get("GREYSEARCH_FLOOR_HUNT_EXTENSIONS", "")
                    or _FLOOR_HUNT_EXTENSIONS_DEFAULT))
    except ValueError:
        v = _FLOOR_HUNT_EXTENSIONS_DEFAULT
    return max(_FLOOR_HUNT_EXTENSIONS_DEFAULT, v)

def _poison_active() -> bool:
    """The engine-name poison drop (results deleted because the instance
    attributed them to google/bing/yahoo/brave/qwant) is OPT-IN and
    DEFAULT OFF: search engines are never disabled on their name alone.
    Set GREYSEARCH_POISON_FILTER=1/true/yes to restore the old drop."""
    return str(os.environ.get("GREYSEARCH_POISON_FILTER", "") or "").strip().lower() \
        in ("1", "true", "yes")

_OWNER_INSTANCES = ("https://search.hbubli.cc", "https://searx.ononoki.org")

def _registry_instance_urls(data: Any, limit: int) -> List[str]:
    """Working clearnet https instance base URLs from the searx.space registry
    data file (SEARX_SPACE_DATA_URL), fittest first in registry order: an
    instance enters the pool only when it is a normal-network host with an
    HTTP 200 homepage and a working multi-engine search timing, exactly the
    fitness filter the searx_fallback harvest applies. Anything smaller or
    malformed yields an empty pool."""
    out: List[str] = []
    if not isinstance(data, dict):
        return out
    instances = data.get("instances")
    if not isinstance(instances, dict):
        return out
    for url, info in instances.items():
        if not isinstance(url, str) or not isinstance(info, dict):
            continue
        if info.get("network_type") != "normal":
            continue
        http_info = info.get("http")
        if not isinstance(http_info, dict) or http_info.get("status_code") != 200:
            continue
        timing = info.get("timing")
        search_timing = timing.get("search") if isinstance(timing, dict) else None
        if not isinstance(search_timing, dict):
            continue
        if search_timing.get("error") is not None:
            continue
        if search_timing.get("working_engines", 0) < 1:
            continue
        base = url.rstrip("/")
        if base.startswith("https://"):
            out.append(base)
        if len(out) >= max(1, limit):
            break
    return out

def _owner_first(urls) -> List[str]:
    """The preferred public instances pinned by default ALWAYS lead the
    browser-lane base order; any discovered searx.space instances follow,
    deduped."""
    out: List[str] = []
    seen: set = set()
    for u in list(_OWNER_INSTANCES) + list(urls or []):
        u = str(u or "").rstrip("/")
        if u and u not in seen and u.startswith("https://"):
            seen.add(u)
            out.append(u)
    return out

def _row_topical(query: str, r: Dict[str, Any]) -> bool:
    """Per-row version of _looks_topical (the 'heuristically measured'
    relevant count the floor counts): the row's own title + content + URL
    must carry the query's content tokens (one when the query has a single
    content token, two when it has more). Rows flagged off-topic never
    count. A query with no content tokens counts every row."""
    if not isinstance(r, dict) or r.get("_off_topic"):
        return False
    tokens = _topic_tokens(query)
    if not tokens:
        return True
    hay = (f"{(r.get('title') or '')} {(r.get('content') or '')} "
           f"{(r.get('url') or '')}").lower()
    hay_tokens = set(_re2.split(r"[^a-z0-9]+", hay))
    hits = sum(1 for t in tokens
               if any(ht == t or ht.startswith(t) for ht in hay_tokens))
    return hits >= (1 if len(tokens) == 1 else min(2, len(tokens)))

class SearXNGEngineManager:
    """
    Manages SearXNG engines with automatic testing, validation, and the
    automatic fallback ladder (local -> searx.space -> direct keyless).
    """

    def __init__(self,
                 searxng_urls: Optional[List[str]] = None,
                 config_path: Optional[str] = None,
                 search_proxy: Optional[str] = None):
        _skip_local = (
            searxng_urls is None
            and os.environ.get("GREYSEARCH_SKIP_LOCAL", "0").strip().lower()
            in ("1", "true", "yes")
        )
        self.skip_local = _skip_local
        self._search_proxy_arg = search_proxy
        self._proxy_arg_last = search_proxy
        self._proxy_res = self._resolve_search_proxy()
        self.searxng_urls = (
            [] if _skip_local else (searxng_urls or ["http://127.0.0.1:8888"])
        )
        self._public_fallback_urls: List[str] = []
        self._run_pool_order: List[str] = []
        self.config_path = config_path or self._find_searxng_config()
        self.engines_config = self._load_engines_config()
        self.working_engines: List[str] = []
        self.engine_stats: Dict[str, Dict[str, Any]] = {}
        self._last_test_time: Optional[float] = None
        self._test_interval = _ENGINE_TEST_INTERVAL
        self._floor_hunt_used = 0

    def set_run_pool_order(self, alive: List[str]) -> None:
        """Pin a run's public-instance pool ordering (the pre-flight's alive
        instances, in the order they answered). A later searx.space probe on
        this manager starts from that ordering instead of re-deriving one;
        an empty list clears the pin and the ladder falls back to the
        discovered pool."""
        self._run_pool_order = [u.strip().rstrip("/") for u in (alive or [])
                                if isinstance(u, str) and u.strip()]

    def _resolve_search_proxy(self) -> Dict[str, Any]:
        """The search-proxy mode this manager serves SEARCH requests with:
        mode "off" builds per-call direct openers (ambient HTTP(S)_PROXY is
        explicitly bypassed), "on" builds per-call credentialed openers
        from the configured environment file. Unknown explicit values
        surface as BAD_MODE records instead of raising."""
        return _proxy_mode.prepared(self._search_proxy_arg)

    def _proxy_resolution(self) -> Dict[str, Any]:
        """Re-check a mode that cannot be honored right now: the env
        file may have appeared since, and no process restart happens here.
        The re-check resolves the arg the current record came from (a
        per-call arg wins over the init arg); a working resolution stays
        put until a caller passes a new arg."""
        if self._proxy_res is None or not self._proxy_res.get("ok"):
            self._proxy_res = _proxy_mode.prepared(self._proxy_arg_last)
        return self._proxy_res

    def _discover_public_instances(self, max_instances: int = 6,
                                   mode: Optional[Dict[str, Any]] = None
                                   ) -> List[str]:
        """Public SearXNG instance URLs, best chain first. Primary: the
        registry data file (SEARX_SPACE_DATA_URL, the moved location of
        searx.space's instance list). Fallback on any registry failure: the
        searx_fallback harvest (the static trio chain, as before). Last:
        an HTML scrape of https://searx.space/ itself. Cached 1h. Each
        fetch is a SEARCH transport: per-call opener from the mode, or the
        plain default transport when no mode was resolved."""
        global _public_searx_cache, _public_searx_cache_at
        now = time.time()
        if _public_searx_cache is not None and _public_searx_cache_at is not None:
            if (now - _public_searx_cache_at) < PUBLIC_SEARX_CACHE_TTL:
                return list(_public_searx_cache)
        urls: List[str] = []
        try:
            with _proxy_mode.open_search(SEARX_SPACE_DATA_URL, timeout=12,
                                         mode=mode,
                                         headers={"User-Agent": "Mozilla/5.0",
                                                  "Accept": "application/json"}) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            urls = _registry_instance_urls(json.loads(raw), max_instances)
        except Exception:
            urls = []
        if not urls:
            try:
                _sf = _searx_fallback()
                urls = [i.rstrip("/") for i in _sf._harvest_instances(
                    limit=max_instances, mode=mode)]
                urls = [u for u in urls if u.startswith("https://")]
            except Exception:
                urls = []
        if not urls:
            try:
                with _proxy_mode.open_search(SEARX_SPACE_URL, timeout=12,
                                             mode=mode,
                                             headers={"User-Agent": "Mozilla/5.0",
                                                      "Accept": "text/html"}) as resp:
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
        if _poison_active():
            return [n for n in engine_names if n not in _POISONED_ENGINES]
        return engine_names

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
                except Exception:
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

    def _local_working_truth(self) -> List[str]:
        """TRUTH LAW (owner 11-10): engine state must be verified against
        reality, never against a probe sweep that the instance's own
        single-search limiter can starve. Order: cached process state →
        disk engine-status cache → ONE REAL unfiltered /search against the
        LOCAL instance. The real query is the verdict: returning results
        means the local lane works, whatever any probe said."""
        if self.working_engines:
            return list(self.working_engines)
        try:
            stats = self.get_engine_stats()
        except Exception:
            stats = {}
        if stats.get("working_engines"):
            return list(stats["working_engines"])
        try:
            if _load_engine_cache(_engine_cache_path()):
                cached = _ENGINE_CACHE.get("engines") or {}
                working = [e for e, st in cached.items()
                           if isinstance(st, dict) and st.get("working")]
                if working:
                    self.working_engines = working
                    return list(working)
        except Exception:
            pass
        try:
            for base_url in self.searxng_urls:
                params = {"q": "test", "format": "json",
                          "safesearch": 0}
                _u = f"{base_url}/search?{urllib.parse.urlencode(params)}"
                _req = urllib.request.Request(_u, headers=_UA_HEADERS)
                with urllib.request.urlopen(_req, timeout=25.0) as _resp:
                    if _resp.status == 200:
                        _data = json.loads(_resp.read().decode("utf-8"))
                        n = len(_data.get("results") or [])
                        if n > 0:
                            self.working_engines = ["default+fullset"]
                            self.engine_stats = {
                                "default+fullset": {
                                    "working": True,
                                    "response_time": 0,
                                    "error": None,
                                    "rate_limited": False,
                                    "last_tested": time.time(),
                                    "verified_by": "real unfiltered query",
                                }}
                            _save_engine_cache(self.engine_stats)
                            return list(self.working_engines)
        except Exception:
            pass
        return []

    def _fullset_first(self, query: str, cat: str, safe_search: int,
                       time_range: str, language: str,
                       merged: List[Dict[str, Any]],
                       seen_urls: set, ladder: List[str],
                       selected: tuple = (),
                       engines_tried: Optional[List[str]] = None) -> bool:
        """Lane-1 primary = one unfiltered query against the instance's own
        default engine set.

        Why this beats the per-engine sweep: single-engine selections
        under-deliver on niche topics (wikipedia is a one-result summary
        engine, github repo-search misses prose topics), the sweep burns
        the instance's one-search-per-5s wall up to 8 times, and its 429s
        manufactured "engines down" alarms. The full set returned ~300
        junk-filtered results for queries the sweep read as empty.

        Additive user selection: an empty "selected" leaves this lane
        byte-for-byte as it was, one request, the default set. A non-empty
        selection adds ONE second request with engines=<names> alongside
        the default one (never instead of it), so the instance's
        single-search limiter still sees one request per lane. Results the
        instance attributes to a poison-banned engine are dropped at merge,
        EXCEPT when that exact name is in this call's selection, so an
        explicitly picked engine merges like any other, but only here, only
        for this call. The ladder records the user lane separately so the
        curation record shows what the selection added.

        Returns True only when the merged results are topical AND at least
        max_results; the caller (search) then skips the per-engine sweep,
        while thin-but-topical results stay merged and the sweep still runs
        as the backstop."""
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
                    # 30s: the local instance answers a full-set query in
                    # ~15s under upstream stalls (measured 3x, 11-10) —
                    # the old 12s cut off the STRONGEST lane while slower
                    # rescue lanes still got through.
                    with urllib.request.urlopen(_req, timeout=30.0) as _resp:
                        if _resp.status == 200:
                            _data = json.loads(_resp.read().decode("utf-8"))
                            for _r in _data.get("results", []):
                                _url = _r.get("url", "")
                                if not _url or _url in seen_urls:
                                    continue
                                if (_poison_active()
                                        and any(e in _POISONED_ENGINES
                                                and e not in selected
                                                for e in (_r.get("engines")
                                                          or []))):
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
        if _variant_added.get("default+fullset") and engines_tried is not None:
            engines_tried.append("default+fullset")
        if selected and _variant_added.get("user"):
            if engines_tried is not None:
                engines_tried.append("user")
            ladder.append(f"user engines: {','.join(selected)} "
                          f"(+{_variant_added['user']} results)")
            _picked = [r for r in merged if r.get("_engine") == "user"]
            _rest = [r for r in merged if r.get("_engine") != "user"]
            merged[:] = _picked + _rest
        if merged and _looks_topical(query, merged) and len(merged) >= 4:
            ladder.append(f"local: {len(merged)} results (full engine set)")
            return True
        if merged and not _looks_topical(query, merged):
            ladder.append(f"local: full set off-topic ({len(merged)} results, "
                          "kept and flagged)")
            for _r in merged:
                _r["_off_topic"] = True
        return False

    def search(self,
               query: str,
               category: str = "general",
               max_results: int = 10,
               time_range: str = "",
               language: str = "",
               safe_search: int = 0,
               max_seconds: float = 60.0,
               engines: Optional[List[str]] = None,
               search_proxy: Optional[str] = None,
               floor_hunt_left: Optional[int] = None) -> Dict[str, Any]:
        """Search with the AUTOMATIC ladder: local -> searx.space -> direct.

        Every lane tried is recorded in result["ladder"] with counts; the
        switch happens in the same call, in seconds, with no silent failures.

        searx.space (must-run): the JSON instance lane is attempted on
        every search regardless of local health, one attempt per search
        call as before; the only skips are an exhausted time budget before
        its turn and a total attempt failure, and each of those, like each
        hold, keeps an honest ladder line.

        engines: optional user selection of SearXNG engine
        names, capped at 8 after dedup + lowercase. When empty/None the
        whole ladder behaves exactly as before. When set, the local lane
        additionally runs one combined request with engines=<names> next to
        its default request (an ADD, never a replacement of the default
        lanes), and explicitly picked names are exempt from the poison
        drop for this call only. Suffix routing (" images"/" news") is the
        CALLER's job via _split_selection; this method treats whatever it
        receives as the additive text/general lane.

        search_proxy (manual proxy mode): "off" (default) or "on"
        ("on" alias). The local lane never changes transport; external
        search lanes resolve their opener per call from this mode, and a
        requested mode that cannot be honoured holds them back instead of
        falling back to direct silently. The first ladder line of every
        search names the mode; external search lanes ride the proxy only
        while this mode is on.

        floor_hunt_left: the budget extensions the relevant
        floor may still take from THIS run; the upper rungs engage either
        way. None (the default) means this call rides the manager's own
        count against GREYSEARCH_FLOOR_HUNT_EXTENSIONS (default 0, so a
        caller that says nothing gets a hunt that never extends the
        budget). The digest line states the cap either way, and a granted
        extension rides the result as floor_hunt_extension_used so the
        caller's run tally stays exact."""
        start_time = time.time()
        if search_proxy is not None:
            self._proxy_arg_last = search_proxy
            self._proxy_res = _proxy_mode.prepared(search_proxy)
        proxy_res = self._proxy_resolution()
        selected = tuple(dict.fromkeys(
            str(x).strip().lower() for x in (engines or [])
            if str(x).strip()))[:8]
        deadline = start_time + max_seconds
        cat = _normalize_category(category)
        ladder: List[str] = []
        ladder.append(_proxy_mode.ladder_note(proxy_res))
        last_error = None
        merged: List[Dict[str, Any]] = []
        seen_urls: set = set()
        engines_tried: List[str] = []

        def _rel_count() -> int:
            """The heuristically measured relevant-row count the floor hunts
            with: rows flagged off-topic and rows that do not carry the
            query's content tokens never count (_row_topical)."""
            return sum(1 for _r in merged if _row_topical(query, _r))
        target = _relevant_target()

        if self.skip_local:
            local_alive = False
            ladder.append("local: skipped (GREYSEARCH_SKIP_LOCAL)")
        else:
            local_alive = (any(_local_alive(u) for u in self.searxng_urls)
                           if self.searxng_urls else False)
        if not local_alive:
            if not self.skip_local:
                try:
                    _cached_working = self.get_working_engines()
                except Exception:
                    _cached_working = []
                if _cached_working:
                    local_alive = True
                    ladder.append("local: probe said down, engine cache says "
                                  "alive; trying the real query")
                else:
                    ladder.append("local: DOWN (skipped, automatic searx.space switch)")
        else:
            working_engines = self._local_working_truth()
            if not working_engines:
                last_error = "local SearXNG alive but no working engines"
                ladder.append("local: alive but no working engines "
                              "(truth query and probes found none, see engine_stats)")
            elif self._fullset_first(query, cat, safe_search, time_range,
                                    language, merged, seen_urls, ladder,
                                    selected=selected,
                                    engines_tried=engines_tried):
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
                                with urllib.request.urlopen(req, timeout=30.0) as response:
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
                        ladder.append(f"local: off-topic ({len(merged)} "
                                      "results, kept and flagged)")
                        for _r in merged:
                            _r["_off_topic"] = True
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
                                with urllib.request.urlopen(_req, timeout=30.0) as _resp:
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
        _floor_ext_flag = False
        if _rel_count() < target:
            _hunt_cap = _floor_hunt_cap()
            _left = floor_hunt_left if isinstance(floor_hunt_left, int) \
                and not isinstance(floor_hunt_left, bool) else None
            _allow = (_left > 0) if (_left is not None) \
                else (self._floor_hunt_used < _hunt_cap)
            if _allow:
                deadline = max(deadline, time.time() + _floor_extend_s())
                if _left is None:
                    self._floor_hunt_used += 1
                _floor_ext_flag = True
                ladder.append(f"relevant floor: {_rel_count()}/{target} "
                              "relevant so far; upper rungs engaged (budget "
                              f"extended for the hunt, cap {_hunt_cap})")
            else:
                ladder.append(f"relevant floor: {_rel_count()}/{target} "
                              "relevant so far; upper rungs engaged (floor "
                              f"hunt: budget not extended (cap {_hunt_cap}))")
        if time.time() < deadline:
            _probe_cap = _instance_probes()
            _run_pool = list(self._run_pool_order or [])
            public_urls = []
            if proxy_res.get("ok"):
                if _run_pool:
                    public_urls = _rotate_order(_run_pool)
                else:
                    public_urls = _rotate_order(
                        self._discover_public_instances(
                            max_instances=_probe_cap, mode=proxy_res))
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
                        with _proxy_mode.open_search(
                                search_url2, timeout=12, mode=proxy_res,
                                headers={"User-Agent": "Mozilla/5.0",
                                         "Accept": "application/json"}) as resp2:
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
                    except Exception as _pe:
                        out.append({"_probe_error":
                                    f"{type(_pe).__name__}: {str(_pe)[:60]}"})
                    return out

                jobs: List[tuple] = []
                for pub_base in public_urls[:_probe_cap]:
                    if pub_base.replace("/", "") in {u.replace("/", "") for u in self.searxng_urls}:
                        continue
                    jobs.append((pub_base, ""))
                tried_public = len(set(p for p, _ in jobs))
                dropped_sets = 0
                dropped_results = 0
                space_added = 0
                probe_errs: List[str] = []
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
                            _fail_rows = [r for r in new
                                          if isinstance(r, dict)
                                          and r.get("_probe_error")]
                            if _fail_rows:
                                probe_errs.extend(str(r["_probe_error"])
                                                  for r in _fail_rows)
                                new = [r for r in new
                                       if not (isinstance(r, dict)
                                               and r.get("_probe_error"))]
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
                                space_added += 1
                if dropped_sets:
                    ladder.append(f"searx.space: off-topic results dropped "
                                  f"({dropped_sets} instance result sets, "
                                  f"{dropped_results} results)")
                if space_added and tried_public:
                    ladder.append(f"searx.space: total after lane {len(merged)} "
                                  f"(instances: {','.join(public_urls[:2])})")
                elif tried_public:
                    if probe_errs:
                        ladder.append("searx.space: tried "
                                      f"{tried_public or 0} instance-probes, "
                                      f"failed ({probe_errs[0]})")
                    else:
                        ladder.append("searx.space: tried "
                                      f"{tried_public or 0} instance-probes, "
                                      "+0 results")
            else:
                ladder.append("searx.space: no reachable instances discovered"
                              if proxy_res.get("ok")
                              else "searx.space: held back (search proxy "
                                   "not honoured)")

            _browse_ran = False
            if _rel_count() < target and time.time() < deadline:
                if not proxy_res.get("ok"):
                    ladder.append("searx.space browser: held back (search "
                                  "proxy not honoured)")
                    browsed = []
                else:
                    try:
                        _sf = _searx_fallback()
                        _bw = ThreadPoolExecutor(max_workers=1,
                                                 thread_name_prefix="browsepub")
                        _bf = _bw.submit(_sf.browser_search_public, query,
                                         max_results, _owner_first(public_urls),
                                         need=target)
                        _browse_ran = True
                        try:
                            browsed = _bf.result(timeout=float(
                                os.environ.get("GREYSEARCH_BROWSER_JOIN_S")
                                or 150.0))
                        finally:
                            _bw.shutdown(wait=False)
                    except Exception as e:
                        browsed = []
                        ladder.append(
                            "searx.space browser: failed/bound-out ("
                            f"{type(e).__name__}: {str(e)[:80]})")
                    try:
                        for rec in _searx_fallback()._captcha_holds():
                            ladder.append(rec)
                    except Exception:
                        pass
                    try:
                        _pw_fn = getattr(_searx_fallback(),
                                         "pace_wait_records", None)
                        if callable(_pw_fn):
                            ladder.extend(_pw_fn())
                    except Exception:
                        pass
                if browsed:
                    _sf_junk = _searx_fallback()
                    browsed = _sf_junk._filter_instance_junk(query, browsed)
                _g_rows: List[Dict[str, Any]] = []
                _bing_rows: List[Dict[str, Any]] = []
                _b_now: List[Dict[str, Any]] = []
                for r in browsed:
                    _eng = str(r.get("engine") or "") if isinstance(r, dict) else ""
                    if _eng.startswith(_GOOGLE_BROWSER_TAG):
                        _g_rows.append(r)
                    elif _eng.startswith("https://www.bing.com"):
                        _bing_rows.append(r)
                    else:
                        _b_now.append(r)
                browsed = _b_now
                if browsed:
                    _bof = not _looks_topical(query, browsed)
                    _b_added = 0
                    for r in browsed:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            merged.append({**r, **({"_off_topic": True}
                                                   if _bof else {})})
                            _b_added += 1
                    ladder.append(
                        f"searx.space browser: {_b_added} results"
                        + (" off-topic (flagged)" if _bof else ""))
                if _g_rows:
                    _gof = not _looks_topical(query, _g_rows)
                    _g_added = 0
                    for r in _g_rows:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            merged.append({**r, **({"_off_topic": True}
                                                   if _gof else {})})
                            _g_added += 1
                    if _g_added:
                        ladder.append(f"google browser: {_g_added} results"
                                      + (" off-topic (flagged)" if _gof else ""))
                    else:
                        ladder.append(
                            f"google browser: 0 of {len(_g_rows)} added")
                if _bing_rows:
                    _bof2 = not _looks_topical(query, _bing_rows)
                    _bi_added = 0
                    for r in _bing_rows:
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            merged.append({**r, **({"_off_topic": True}
                                                   if _bof2 else {})})
                            _bi_added += 1
                    if _bi_added:
                        ladder.append(f"bing browser: {_bi_added} results"
                                      + (" off-topic (flagged)" if _bof2 else ""))
                    else:
                        ladder.append(
                            f"bing browser: 0 of {len(_bing_rows)} added")
                if _browse_ran:
                    try:
                        _gr_fn = getattr(_searx_fallback(),
                                         "google_lane_records", None)
                        if callable(_gr_fn):
                            ladder.extend(_gr_fn())
                    except Exception:
                        pass
                    try:
                        _br_fn = getattr(_searx_fallback(),
                                         "bing_lane_records", None)
                        if callable(_br_fn):
                            ladder.extend(_br_fn())
                    except Exception:
                        pass
        else:
            ladder.append("searx.space: not engaged (time budget reached)")

        _direct_ran = False
        if _rel_count() < target and time.time() < deadline:
            if not proxy_res.get("ok"):
                ladder.append("direct keyless: held back (search proxy "
                              "not honoured)")
            else:
                try:
                    _sf = _searx_fallback()
                    direct = _sf._direct_search(query,
                                                max_results=max(8, min(target, 24)),
                                                mode=proxy_res)
                    _direct_ran = True
                    direct_offtopic = bool(direct) and not _looks_topical(query, direct)
                    added = 0
                    sub_lanes: List[str] = []
                    for r in direct:
                        url = r.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        merged.append({**r, "_engine": r.get("source", "direct") + "+direct",
                                       "_off_topic": direct_offtopic})
                        added += 1
                        sub_lanes.append(str(r.get("source") or "direct"))
                    if added:
                        ladder.append(
                            "direct keyless: +" + str(added) + " ("
                            + ", ".join(dict.fromkeys(sub_lanes)) + ")"
                            + (" off-topic (last resort)"
                               if direct_offtopic else ""))
                    elif not ladder or "direct keyless" not in str(ladder):
                        ladder.append("direct keyless: 0 results")
                except Exception as e:
                    last_error = str(e)
                if _direct_ran:
                    try:
                        _ar_fn = getattr(_searx_fallback(),
                                         "archive_lane_records", None)
                        if callable(_ar_fn):
                            ladder.extend(_ar_fn())
                    except Exception:
                        pass
        elif time.time() >= deadline:
            ladder.append("direct keyless: not engaged (time budget reached)")
        else:
            ladder.append("direct keyless: not engaged (enough results)")

        _rel_final = _rel_count()
        if _rel_final < target:
            ladder.append(
                f"relevant floor unmet ({_rel_final}/{target} relevant): "
                "re-run with search_proxy=on to widen the upstream "
                "lanes; WebSearch stays off")
        results = self._process_search_results(
            sorted(merged, key=lambda _r: 0 if _row_topical(query, _r) else 1),
            max_results)
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
            "relevant_count": _rel_final,
            "relevant_target": target,
            "search_proxy": proxy_res.get("mode") or "",
            **({"floor_hunt_extension_used": True} if _floor_ext_flag else {}),
            **({"search_proxy_error": proxy_res.get("error")}
               if proxy_res.get("error") else {}),
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
        """Extract domain from URL. The gotcha to keep: urlparse must be
        imported in any module using this pattern (without the import every
        result silently got an empty domain)."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    def get_engine_stats(self) -> Dict[str, Any]:
        """Statistics for all engines. TRUTH LAW (owner, 11-10): a health
        call that comes before any engine test must not report a working
        server as engineless — measure the instance for real, right here,
        instead of echoing empty process state."""
        if not self.engine_stats:
            try:
                self.test_engines()
            except Exception:
                pass
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