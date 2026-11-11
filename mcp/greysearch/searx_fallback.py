#!/usr/bin/env python3
"""searx_fallback.py: SearXNG fallback ladder.
1. local :8888 (working engines only, suspended ones excluded)
2. public instances from https://searx.space/data/instances.json (hardcoded discovery source)
3. if all time out: direct keyless search lanes (DDG html; the Bing RSS rung was removed)

The searx.space discovery source is hardcoded and must never be bypassed.
"""
import urllib.request, urllib.parse, json, time, random, re, os, ssl
import base64

import proxy_mode as _proxy_mode

try:
    import tuning as _tuning
except Exception:
    _tuning = None

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"}
SEARX_SPACE = "https://searx.space"
SEARX_SPACE_DATA = "https://searx.space/data/instances.json"
ROSTER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research", "searx-fallback-roster.json")
LOCAL = "http://127.0.0.1:8888"
USE_LOCAL = os.environ.get("GREYSEARCH_LOCAL_SEARX", "").lower() in ("1", "true", "yes")
LOCAL_ENGINES = "mojeek,wikipedia,github,stackoverflow,duckduckgo,google cse"
INSTANCE_ENGINES = ""

_CTX = ssl._create_unverified_context()

_PACE_LAST = 0.0
_SETTLE_S = 22.0

def eval_with_timeout(page, js: str, timeout_s: float = 20.0):
    """page.evaluate with a hard wall and wedged-tab recovery."""
    try:
        from browser_session import eval_with_timeout as _ewt
        return _ewt(page, js, timeout_s)
    except Exception:
        return None

def pace_wait(min_gap: float = 8.0):
    """Global search pacing: no two search requests land closer than
    min_gap apart, process-wide. Returns immediately when already spaced."""
    global _PACE_LAST
    import time as _t
    gap = _PACE_LAST + min_gap - _t.time()
    if gap > 0:
        _t.sleep(min(gap, 40.0))
    _PACE_LAST = _t.time()

def settle_first_contact(page):
    """Bot-detection settle, called after a NEW host's first page load:
    first contact with an unfamiliar host needs roughly 20 to 30 seconds
    so any bot detection finishes before the page is used."""
    try:
        page.wait_for_timeout(int(_SETTLE_S * 1000))
    except Exception:
        pass

def _auth_settle(page):
    """WAIT 30 SECONDS TO 1 MINUTE EVERY TIME THE SITE LOADS: the
    instance's bot check (Anubis) starts authenticating on every load and
    the page must settle before the search runs. Default 30 s,
    GREYSEARCH_AUTH_SETTLE_S overrides, hard cap 60 s."""
    try:
        s = float(str(os.environ.get("GREYSEARCH_AUTH_SETTLE_S", "") or 30.0))
    except ValueError:
        s = 30.0
    s = max(0.0, min(60.0, s))
    try:
        page.wait_for_timeout(int(s * 1000))
    except Exception:
        pass

_INSTANCE_READY: dict = {}

_AUTH_SETTLE_S = 30.0

def _enable_all_engines_every_tab(page) -> dict:
    """Enable EVERY search engine on EVERY preferences tab.

    Standing rule for the searx.space sites: the bot checks require waiting
    30 seconds and letting them authenticate first. The sites can then be
    used after changing preferences to enable all search engines. Do that
    for ALL, not just web: every available tab (video, IT, social media,
    etc.) must have all its engines enabled."

    The SearXNG preferences page groups engines into category tabs (general,
    it, images, videos, news, maps, music, …). Each tab has its own
    "Enable all engines" button, and Playwright CANNOT click a button on a
    hidden tab, so we must click each tab first to make its pane visible,
    then click that pane's enable-all. As a belt-and-braces fallback we also
    tick every engine checkbox directly via JS (works regardless of tab).
    Returns a per-tab report for debugging.
    """
    report = {}
    try:
        origin = page.evaluate("() => window.location.origin")
        if "/preferences" not in (page.url or ""):
            page.goto(origin + "/preferences", timeout=45000,
                      wait_until="domcontentloaded")
    except Exception:
        try:
            page.goto(origin + "/preferences", timeout=45000,
                      wait_until="domcontentloaded")
        except Exception:
            pass
    page.wait_for_timeout(3000)

    try:
        tabs = page.locator("[role='tab'][id^='tab-label-category_'], "
                            "[role='tab']#tab-label-engines")
        n_tabs = tabs.count()
        report["tabs_found"] = n_tabs
        for i in range(n_tabs):
            try:
                t = tabs.nth(i)
                label = (t.inner_text(timeout=800) or t.get_attribute("id") or f"tab{i}").strip()
                t.click(timeout=2000, force=True)
                page.wait_for_timeout(700)
                clicked = page.evaluate(
                    """() => {
                        const btns = [...document.querySelectorAll(
                            'button.enable-all-engines')];
                        let n = 0;
                        btns.forEach(b => {
                            const panel = b.closest('[role="tabpanel"], .tab-pane, div[id^="tab-content"]');
                            // click all enable-all buttons whose panel is
                            // currently shown (not display:none)
                            if (panel && panel.offsetParent !== null) { b.click(); n++; }
                            else if (!panel) { b.click(); n++; }
                        });
                        return n;
                    }"""
                )
                report[label[:30]] = f"enable-all x{clicked}"
            except Exception as e:
                report[f"tab{i}"] = f"err {str(e)[:40]}"
    except Exception:
        pass

    try:
        n_checked = page.evaluate(
            """() => {
                let n = 0, total = 0;
                // engine checkboxes: name starts with "engine_"
                document.querySelectorAll(
                    'input[type="checkbox"][name^="engine_"]'
                ).forEach(cb => {
                    total++;
                    if (!cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles:true}));
                        n++;
                    }
                });
                // any other engine-ish checkbox (name contains 'engine')
                document.querySelectorAll(
                    'input[type="checkbox"][name*="engine"]'
                ).forEach(cb => {
                    if (!cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles:true}));
                        n++;
                    }
                });
                // category checkboxes so whole categories aren't disabled
                document.querySelectorAll(
                    'input[type="checkbox"][name^="category"], '
                  + 'input[type="checkbox"][name*="category"]'
                ).forEach(cb => {
                    if (!cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles:true}));
                        n++;
                    }
                });
                return {checked: n, engineTotal: total};
            }"""
        )
        report["js_checkboxes"] = n_checked
    except Exception as e:
        report["js_checkboxes"] = f"err {str(e)[:60]}"

    try:
        save = page.locator("input[type=submit], button[type=submit], "
                            "button:has-text('Save')").last
        save.click(timeout=4000)
        report["saved"] = "clicked"
    except Exception:
        try:
            page.evaluate(
                """() => {
                    const f = document.querySelector('form');
                    if (f) { f.requestSubmit ? f.requestSubmit() : f.submit(); }
                }"""
            )
            report["saved"] = "js-submit"
        except Exception as e:
            report["saved"] = f"err {str(e)[:60]}"
    page.wait_for_timeout(4000)
    return report

def ensure_instance_ready(browser, base: str, page=None) -> bool:
    """A NEW searx.space instance gets the same setup
    a human does, ONCE per process: load its home page, WAIT 30 SECONDS for
    the bot check (Anubis) to authenticate, open /preferences, ENABLE ALL
    SEARCH ENGINES ON ALL CATEGORY TABS (general/it/images/videos/news/maps/
    music/social/…), save. Cookies then live in this browser session for the
    searches after. When `page` is supplied, use that one shared tab; never
    open/close a tab."""
    base = (base or "").rstrip("/")
    if not base or _INSTANCE_READY.get(base):
        return True
    try:
        created = page is None
        if page is None:
            ctx = browser.contexts[0] if getattr(browser, "contexts", None) else browser.new_context()
            page = ctx.new_page()
        try:
            page.goto(base + "/", timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(int(_AUTH_SETTLE_S * 1000))
            page.goto(base + "/preferences", timeout=45000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            _LAST_INSTANCE_REPORT[base] = _enable_all_engines_every_tab(page)
        except Exception as e:
            _LAST_INSTANCE_REPORT[base] = f"err {str(e)[:80]}"
        if created:
            try:
                page.close()
            except Exception:
                pass
        _INSTANCE_READY[base] = time.time()
        return True
    except Exception:
        return False

_LAST_INSTANCE_REPORT: dict = {}

def _fetch(url, timeout=15, mode=None):
    """One search-transport hop. The loopback SearXNG lane keeps the plain
    default transport whatever the mode says; every external fetch builds a
    per-call opener from the mode (direct when off, credentialed when
    proxy) and raises ProxyModeError when an on-mode request cannot be
    served, never falling back to direct silently."""
    return _proxy_mode.open_search(url, timeout=timeout, mode=mode, headers=UA)

def _harvest_instances(force=False, limit=10, mode=None):
    """Pull searx.space/data/instances.json (fixed source). Returns live instance URLs.
    This harvest is a SEARCH transport: it honours the mode per call."""
    if os.path.exists(ROSTER_FILE) and not force:
        if time.time() - os.path.getmtime(ROSTER_FILE) < 86400 * 3:
            try:
                rost = json.load(open(ROSTER_FILE))
                if rost.get("instances"):
                    return rost["instances"]
            except Exception:
                pass
    try:
        data = json.loads(_fetch(SEARX_SPACE_DATA, 15, mode=mode).read().decode("utf-8"))
        instances = data.get("instances", {})
        good = []
        for url, info in instances.items():
            if info.get("network_type") != "normal":
                continue
            if info.get("http", {}).get("status_code") != 200:
                continue
            timing = info.get("timing", {}).get("search", {})
            if timing.get("error") is not None:
                continue
            if timing.get("working_engines", 0) < 1:
                continue
            good.append(url)
            if len(good) >= limit:
                break
        if good:
            json.dump({"harvested": time.strftime("%Y-%m-%d"), "instances": good},
                      open(ROSTER_FILE, "w"), indent=1)
            return good
    except Exception:
        pass
    try:
        h = _fetch(SEARX_SPACE, 15, mode=mode).read().decode("utf-8", "ignore")
        doms = sorted(set(re.findall(r'https://([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-z]{2,})/?["<>\\s]', h)))
        doms = [d for d in doms if not any(x in d for x in (".onion", "cryptcheck", "github", "helpdesk", "about.", "status", "uptime", "searx.space"))]
        return [f"https://{d}/" for d in doms[:limit]]
    except Exception:
        pass
    return []

def _search_via_instance(base_url, query, max_results=10, timeout=15, mode=None):
    """Try one SearXNG instance via JSON API with instance-default engines.

    30s warm-up before first contact with this remote host (tarpit defense,
    once per host), then junk-filter the results; generated affiliate /
    trending-feed pages never reach a caller. A host whose entire result set
    is junk is benched for the rest of the process. The instance search is a
    SEARCH transport: the opener resolves per call from the mode."""
    if _is_benched(base_url):
        return []
    _warm_remote_host(base_url)
    try:
        q = urllib.parse.quote(query, safe="")
        url = f"{base_url.rstrip('/')}/search?q={q}&format=json"
        if INSTANCE_ENGINES:
            url += f"&engines={urllib.parse.quote(INSTANCE_ENGINES, safe=',')}"
        r = _fetch(url, timeout, mode=mode)
        d = json.loads(r.read().decode("utf-8"))
        results = d.get("results", [])[:max_results]
        results = [x for x in results if x.get("url")]
        if not results:
            return []
        kept = _filter_instance_junk(query, results)
        if results and not kept:
            _bench_host(base_url, "entire result set was junk")
        return kept
    except Exception:
        pass
    return []

_LAST_BROWSER_SEARCH = 0.0
_HUMAN_GAP_S = 15.0
_LAST_BROWSER_DEBUG = {}

_GS_WINDOW: dict = {"proc": None, "cdp": None, "ctx": None, "page": None}
_GS_WINDOW_LOCK = __import__("threading").Lock()

def _bs():
    try:
        from . import browser_session as _bs
    except ImportError:
        import browser_session as _bs
    return _bs

_CAPTCHA_HOLDS = []

def _captcha_holds():
    """Captcha marks recorded during the LAST browser_search_public call: one
    honest mark per engaged page ("captcha: solver waited <N>s (solved)" or
    "captcha: persisted (solver wait + retry exhausted)"). Cleared at every
    call's entry and only populated by calls that ran, so the ladder surfaces
    marks only for the attempt the caller actually made."""
    return list(_CAPTCHA_HOLDS)

_PACE_RECORDS: list = []

def pace_wait_records() -> list:
    """Pace records authored during the LAST browser_search_public call: one
    honest line per instance base whose search request waited for the
    browser-lane pace guard (GREYSEARCH_BROWSER_PACE_S spacing, the waited
    seconds and the base it applied to). Cleared at every call's entry and
    only populated by calls that ran, so a lane's digest names only the
    attempt's own waits; the google and bing rungs record inside their own
    record families instead."""
    return list(_PACE_RECORDS)

def _captcha_cycle(page):
    """One WAIT-and-retry cycle through browser_session's singletons for one
    page; when the cycle engaged the record lands in _CAPTCHA_HOLDS as its
    mark. Returns (record, mark): solved means proceed normally, engaged
    yet unsolved means the attempt is held with the honest mark. Never
    loops; the waits are bounded by the knob contract in browser_session.
    The local solver rides the same single step it rides in the scrape
    lane (browser_session.captcha_solver_step): only when the bounded wait
    left the page engaged but unsolved and the kill switch allows, and its
    answer carries only when the bounded re-wait sees the challenge
    lifted - the re-wait's result governs, not the solver's word. When it
    resolves, the lane goes on with the re-wait's own record; the first
    cycle's persisted mark stays in the holds list and the solver's honest
    note ("captcha_solved" or, when it did not resolve, "captcha_skip")
    rides alongside as its own line there, mirror of the scrape lane's
    record keys."""
    cyc = {"engaged": False, "solved": False, "waited_s": 0.0}
    mark = ""
    try:
        cyc = _bs().captcha_wait_cycle(page)
        mark = _bs().captcha_mark(cyc) or ""
    except Exception:
        cyc, mark = dict(cyc), ""
    if not isinstance(cyc, dict):
        cyc = {"engaged": False, "solved": False, "waited_s": 0.0}
    if cyc.get("engaged") and mark:
        _CAPTCHA_HOLDS.append(mark)
    if cyc.get("engaged") and not cyc.get("solved"):
        try:
            rec, notes = _bs().captcha_solver_step(page, cyc)
        except Exception:
            rec, notes = cyc, {}
        for key in ("captcha_solved", "captcha_skip"):
            if isinstance(notes, dict) and notes.get(key):
                _CAPTCHA_HOLDS.append(f"{key}: {notes[key]}")
        if rec is not cyc and notes.get("captcha_solved"):
            cyc = rec
            mark = _bs().captcha_mark(rec) or ""
    return cyc, mark

def _pace_guard(engine_tag: str) -> float:
    """One browser-lane search request's spacing hop (this module's single
    way onto browser_session's pace guard): waits the spacing due to THIS
    engine since its last browser-lane search request in the process and
    returns the waited seconds (0.0 for the engine's first request of the
    process, when the last one is already old enough, and always when the
    guard is inert). The caller records a nonzero return in its lane's
    digest; page fetches never come through here."""
    try:
        return float(_bs().browser_pace_wait(engine_tag) or 0.0)
    except Exception:
        return 0.0

def _gs_slot() -> dict:
    """Resolve greysearch's slot the exact way browser_session does (env
    RESEARCH_TASK first, default task-3): one resolution point, no drift."""
    return _bs()._cfg()

def _gs_window():
    """Return the shared slot page via browser_session, the single CDP
    connection holder (per-thread cache, auto-launch when down). Everything
    here attaches; nothing closes; thread switches are handled by the
    browser_session cache, never by this module's memo."""
    conn = _bs()._connection()
    _GS_WINDOW["page"] = conn["page"]
    _GS_WINDOW["ctx"] = conn["ctx"]
    _GS_WINDOW["cdp"] = conn["pw"]
    return conn["page"]

_REMOTE_WARMUP_S = float(os.environ.get("GREYSEARCH_WARMUP_S", "0") or 0.0)
_REMOTE_WARMED: set = set()
_REMOTE_WARM_LOCK = __import__("threading").Lock()

_MAX_OPEN_TABS_PER_HOST = 3

_BENCHED_HOSTS: set = {"anonsearch.win"}

def _bench_host(base_url: str, why: str) -> None:
    try:
        host = urllib.parse.urlparse(base_url).netloc
        if host:
            _BENCHED_HOSTS.add(host)
    except Exception:
        pass
    import logging
    logging.getLogger("searx_fallback").info("benched host %s: %s",
                                             base_url[:60], why[:80])

def _is_benched(base_url: str) -> bool:
    try:
        host = urllib.parse.urlparse(base_url).netloc
        return host in _BENCHED_HOSTS
    except Exception:
        return False

def _warm_remote_host(base_url: str):
    """Block up to _REMOTE_WARMUP_S before first contact with a remote
    searx instance host. Once per host per process; subsequent calls are
    instant. Localhost is never delayed. The 30s wait happens OUTSIDE the
    guard lock because sleeping while holding it serialized all parallel
    warm-ups
    (4 hosts × 30s = 120s for what is one 30s settle done concurrently)."""
    host = urllib.parse.urlparse(base_url).netloc
    if not host or host.startswith("127.") or host == "localhost":
        return
    with _REMOTE_WARM_LOCK:
        if host in _REMOTE_WARMED:
            return
        if host in _REMOTE_WARMING:
            ev = _REMOTE_WARMING[host]
            own = False
        else:
            ev = __import__("threading").Event()
            _REMOTE_WARMING[host] = ev
            own = True
    if own:
        try:
            _wj = _tuning.get("warmup_jitter_s", 15.0) if (_tuning and _REMOTE_WARMUP_S > 0) else 0.0
            time.sleep(_REMOTE_WARMUP_S + random.uniform(0.0, _wj))
        finally:
            with _REMOTE_WARM_LOCK:
                _REMOTE_WARMED.add(host)
                _REMOTE_WARMING.pop(host, None)
            ev.set()
    else:
        ev.wait(_REMOTE_WARMUP_S + 20)

_REMOTE_WARMING: dict = {}

_JUNK_DOMAINS = (
    "mycoffeeexplorer.com", "booking.com", "hyatt.com", "facebook.com",
    "lenskart.com", "amazon.", "ebay.", "aliexpress.", "wish.com",
    "yellowpages.", "yelp.", "tripadvisor.", "healthline.com",
    "webmd.com", "mayoclinic.org", "drugs.com",
)

def _result_is_junk(query: str, r: dict) -> bool:
    """True if an instance-lane result is tarpit/affiliate junk."""
    url = (r.get("url") or "").lower()
    title = (r.get("title") or "").lower()
    if not url.startswith(("http://", "https://")):
        return True
    if any(d in url for d in _JUNK_DOMAINS):
        return True
    toks = {t for t in re.split(r"[^a-z0-9]+", query.lower())
            if len(t) > 3 and t not in _QUERY_STOPWORDS}
    if toks:
        blob = f"{title} {url}"
        if not any(t in blob for t in toks):
            return True
    return False

def _filter_instance_junk(query: str, results: list) -> list:
    kept = [r for r in results if not _result_is_junk(query, r)]
    dropped = len(results) - len(kept)
    if dropped:
        import logging
        logging.getLogger("searx_fallback").info(
            "junk-filter: dropped %d/%d instance results for %r",
            dropped, len(results), query[:80])
    return kept

_QUERY_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "into", "onto", "over", "under", "about", "after", "before", "how",
    "what", "when", "where", "why", "which", "who", "will", "your", "their",
    "its", "was", "were", "has", "have", "had", "does", "did", "use", "used",
    "using", "via", "per", "guide", "tutorial", "pdf", "free", "online",
    "download", "downloads", "install", "installation", "installing",
    "version", "versions", "history", "support", "latest", "news", "best",
    "2024", "2025", "2026",
}

def _relevant(query, results):
    """Cheap topicality gate: at least half of the query's content words must
    appear in the result titles/URLs. Off-topic pages never feed a course."""
    toks = {t for t in re.split(r"[^a-z0-9]+", query.lower())
            if len(t) > 3 and t not in _QUERY_STOPWORDS}
    if not toks or not results:
        return False
    text = " ".join(
        (r.get("title", "") + " " + r.get("url", "")).lower() for r in results)
    hits = sum(1 for t in toks if t in text)
    need = 1 if len(toks) == 1 else min(2, len(toks))
    platform = {"macos", "linux", "windows", "android", "ios", "unix", "bsd"} & toks
    if platform and not any(p in text for p in platform):
        return False
    return hits >= need

def _result_relevant(query, r):
    """Per-result gate. A result must itself contain the query's core terms;
    one relevant title in a mixed page is not enough."""
    toks = {t for t in re.split(r"[^a-z0-9]+", (query or "").lower())
            if len(t) > 3 and t not in _QUERY_STOPWORDS}
    if not toks:
        return True
    text = " ".join([
        (r.get("title") or ""), (r.get("url") or ""),
        (r.get("content") or ""),
    ]).lower()
    hits = sum(1 for t in toks if t in text)
    need = 1 if len(toks) == 1 else min(2, len(toks))
    platform = {"macos", "linux", "windows", "android", "ios", "unix", "bsd"} & toks
    if platform and not any(p in text for p in platform):
        return False
    return hits >= need

def _enable_all_engines(page, base_url):
    """Turn on every engine checkbox in the instance preferences and save."""
    try:
        page.goto(base_url.rstrip("/") + "/preferences",
                  timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        n = eval_with_timeout(
            page,
            '() => document.querySelectorAll(\'input[type="checkbox"]\').length') or 0
        eval_with_timeout(page, """() => {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', {bubbles: true}));
            });
        }""")
        saved = eval_with_timeout(page, """() => {
            const form = document.querySelector('form');
            if (!form) return false;
            if (form.requestSubmit) { form.requestSubmit(); return true; }
            form.submit();
            return true;
        }""")
        page.wait_for_timeout(3000)
        return n, bool(saved)
    except Exception:
        return 0, False

_OWNER_BROWSER_BASES = ("https://search.hbubli.cc", "https://searx.ononoki.org")

def _owner_first_urls(urls):
    """The two priority instances ALWAYS lead the browser-lane base order; the
    harvested searx.space instances follow, deduped, in the given order."""
    out, seen = [], set()
    for u in list(_OWNER_BROWSER_BASES) + list(urls or []):
        u = str(u or "").rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

def browser_search_public(query, max_results=10, instances=None, timeout=45,
                          need=None):
    """Search the two priority public SearXNG instances in a real browser.

    Human-pace rules:
    - the two priority instances (search.hbubli.cc, searx.ononoki.org) are
      ALWAYS visited first, then any harvested searx.space instances;
    - auth cookies are NEVER cleared between hopping bases and the bot
      check settles 30-60 s (GREYSEARCH_AUTH_SETTLE_S) on every page load;
    - enable all engines in preferences once per process;
    - one search at a time at a human pace;
    - rows are never discarded between bases: every relevant row a base
      yields is kept (take the results we can), the next base still runs
      until the relevant floor is met, and the google and bing browser
      rungs engage when the floor is still unmet.

    need (floor callers): the relevant-row target the ladder hunts to.
    None keeps the legacy shape (stop at the first relevant base).
    """
    _LAST_BROWSER_DEBUG.clear()
    del _CAPTCHA_HOLDS[:]
    del _PACE_RECORDS[:]
    del _GOOGLE_LANE_RECORDS[:]
    del _BING_LANE_RECORDS[:]
    _floor = _tuning.scaled("pace_floor_s") if _tuning else 8.0
    _lane_end = time.time() + float(
        os.environ.get("GREYSEARCH_BROWSER_LANE_CAP_S") or 480.0)
    _skipped_cap = 0
    pace_wait(_floor)
    global _LAST_BROWSER_SEARCH
    _since = time.time() - _LAST_BROWSER_SEARCH
    _gap = _tuning.scaled("human_gap_s") if _tuning else _HUMAN_GAP_S
    _jit = _tuning.get("human_gap_jitter_s", 5.0) if _tuning else 5.0
    _need = _gap + random.uniform(0.0, _jit)
    if _since < _need:
        time.sleep(_need - _since)

    if instances:
        urls = _owner_first_urls(instances)
    else:
        urls = list(_OWNER_BROWSER_BASES)
    _need = int(need) if need else max_results
    out = []
    try:
        page = _gs_window()
        ctx = _GS_WINDOW["ctx"]
        browser = ctx.browser
        for base in urls:
            if _is_benched(base):
                _LAST_BROWSER_DEBUG.setdefault(base, {})["benched"] = True
                continue
            if time.time() > _lane_end:
                _skipped_cap += 1
                continue
            try:
                _warm_remote_host(base)
                ensure_instance_ready(browser, base, page=page)
                page.goto(base + "/", timeout=60000,
                          wait_until="domcontentloaded")
                _auth_settle(page)
                page.wait_for_timeout(2000)
                _pw = _pace_guard(base)
                if _pw > 0:
                    _LAST_BROWSER_DEBUG.setdefault(
                        base, {})["pace_waited_s"] = _pw
                    _PACE_RECORDS.append(
                        f"searx.space browser: pace wait "
                        f"{int(round(_pw))}s before {base}")
                try:
                    page.locator(
                        "input[name='q'], input[type='search'], #q"
                    ).first.fill(query, timeout=8000)
                    page.locator(
                        "button[type='submit'], input[type='submit']"
                    ).first.click(timeout=8000)
                except Exception:
                    page.goto(
                        f"{base}/search?q={urllib.parse.quote(query)}",
                        timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(8000)
                _cyc, _cap_mark = _captcha_cycle(page)
                if _cap_mark:
                    _LAST_BROWSER_DEBUG.setdefault(
                        base, {})["captcha"] = _cap_mark
                if _cyc.get("engaged") and not _cyc.get("solved"):
                    continue
                try:
                    page.wait_for_selector(
                        "#main_results article, article.result, "
                        "div.result", timeout=30000)
                except Exception:
                    _LAST_BROWSER_DEBUG.setdefault(base, {})[
                        "after"] = page.title()[:120]
                    _LAST_BROWSER_DEBUG[base]["body"] = (
                        page.locator("body").inner_text()[:300])
                    raise
                items = page.locator("#main_results article")
                if items.count() == 0:
                    items = page.locator("article.result, div.result")
                n = min(items.count(), max_results)
                for i in range(n):
                    it = items.nth(i)
                    try:
                        a = it.locator("h3 a").first
                        title = (a.inner_text(timeout=1500) or "").strip()
                        href = a.get_attribute("href") or ""
                    except Exception:
                        try:
                            a = it.locator("a[href]").first
                            title = (a.inner_text(timeout=1000) or "").strip()
                            href = a.get_attribute("href") or ""
                        except Exception:
                            continue
                    if not href:
                        continue
                    url = urllib.parse.urljoin(base + "/", href)
                    if "/redirect" in url and "url=" in url:
                        qs = urllib.parse.parse_qs(
                            urllib.parse.urlparse(url).query)
                        url = (qs.get("url") or [url])[0]
                    if not url.startswith("http"):
                        continue
                    try:
                        snippet = (it.locator("p.content").first
                                   .inner_text(timeout=1000) or "").strip()
                    except Exception:
                        snippet = ""
                    cand = {"title": title, "url": url,
                            "content": snippet, "engine": base}
                    if _result_is_junk(query, cand):
                        continue
                    if _result_relevant(query, cand):
                        out.append(cand)
                _LAST_BROWSER_DEBUG.setdefault(base, {}).update({
                    "results": len(out),
                    "relevant": _relevant(query, out),
                })
                if need:
                    if len(out) >= _need:
                        break
                elif out and _relevant(query, out):
                    break
            except Exception as e:
                _LAST_BROWSER_DEBUG.setdefault(base, {})[
                    "error"] = str(e)[:220]
                continue
        _google_rung(query, max_results, page, ctx, out, _lane_end, need=need)
        _bing_rung(query, max_results, page, ctx, out, _lane_end, need=need)
    except Exception as e:
        _LAST_BROWSER_DEBUG["error"] = str(e)[:300]
        return out
    finally:
        _LAST_BROWSER_SEARCH = time.time()

    seen = set()
    dedup = []
    for r in out:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        dedup.append(r)
    return dedup

_GOOGLE_BROWSER_TAG = "https://www.google.com"

_GOOGLE_AD_URL_RE = re.compile(r'(google\.com/aclk|googleadservices\.com)',
                               re.IGNORECASE)

_GOOGLE_LINKS_JS = """() => Array.from(document.querySelectorAll('a h3'))
    .slice(0, 40).map(h => {
        const a = h.closest('a');
        return {href: a ? a.href : '', text: (h.innerText || '').trim()};
    }).filter(x => x.href && x.href.startsWith('http'))"""

_GOOGLE_LANE_RECORDS: list = []

def google_lane_records() -> list:
    """Rung honesty records authored during the LAST browser_search_public
    call: the google browser rung's barren, not-engaged, captcha-held and
    failed lines, in the searx.space record wording family. Cleared at every
    call's entry so only the attempt the caller actually made is relayed."""
    return list(_GOOGLE_LANE_RECORDS)

_ARCHIVE_LANE_RECORDS: list = []

def archive_lane_records() -> list:
    """Rung honesty records authored during the LAST _direct_search call:
    the archive-org rung's barren, not-engaged and failed lines, in the
    searx.space record wording family. Cleared at every call's entry."""
    return list(_ARCHIVE_LANE_RECORDS)

def _google_rung(query, max_results, page, ctx, out, lane_end,
                 need=None) -> bool:
    """The FINAL browser-ladder base: google.com/search attempted
    through the SAME slot-browser machinery only, after every instance base
    and only when the bases delivered nothing relevant. Google via urllib is
    never attempted (over plain HTTP that path serves poisoned results). One
    google attempt per search call max; it rides the captcha WAIT-and-retry
    machinery already wired (no new marking), the browser-lane gate and the
    lane cap seconds; interstitial pages wait-and-proceed like any other
    browser base. Returns True only when the rung delivered rows.

    need (floor callers): the relevant-row floor this rung hunts to; when
    set, the rung refuses only when `out` already reaches it, so a partial
    but non-empty pool still hunts google. When None the legacy shape
    holds: any delivered rows mean the rung does not engage.
    """
    if need:
        if len(out) >= int(need):
            _GOOGLE_LANE_RECORDS.append(
                "google browser: not engaged (earlier bases delivered)")
            return False
    elif out:
        _GOOGLE_LANE_RECORDS.append(
            "google browser: not engaged (earlier bases delivered)")
        return False
    if any(str(h).startswith("captcha: persisted") for h in _CAPTCHA_HOLDS):
        _GOOGLE_LANE_RECORDS.append(
            "google browser: not engaged (captcha persisted on the "
            "earlier bases)")
        return False
    _gg = os.environ.get("GREYSEARCH_BROWSER_LANE", "1").strip().lower()
    if _gg not in ("1", "true", "yes", ""):
        _GOOGLE_LANE_RECORDS.append(
            "google browser: not engaged (browser lane off)")
        return False
    if time.time() > lane_end:
        _GOOGLE_LANE_RECORDS.append(
            "google browser: not engaged (lane cap reached)")
        return False
    _grows: list = []
    _gdedup: set = set()
    _held = False
    _failed = False
    _pw = _pace_guard(_GOOGLE_BROWSER_TAG)
    if _pw > 0:
        _GOOGLE_LANE_RECORDS.append(
            f"google browser: pace wait {int(round(_pw))}s "
            "before the search request")
    try:
        page.goto(_GOOGLE_BROWSER_TAG + "/search?q="
                  + urllib.parse.quote(query) + f"&num={max_results}",
                  timeout=60000, wait_until="domcontentloaded")
        settle_first_contact(page)
        _gcyc, _gmark = _captcha_cycle(page)
        if _gmark:
            _LAST_BROWSER_DEBUG.setdefault(
                _GOOGLE_BROWSER_TAG, {})["captcha"] = _gmark
        if _gcyc.get("engaged") and not _gcyc.get("solved"):
            _held = True
        else:
            _glinks = eval_with_timeout(page, _GOOGLE_LINKS_JS, 20.0) or []
            for link in (_glinks if isinstance(_glinks, list)
                         else [])[:max_results]:
                if not isinstance(link, dict):
                    continue
                url = (link.get("href") or "").strip()
                title = (link.get("text") or "").strip()
                if not url or _GOOGLE_AD_URL_RE.search(url):
                    continue
                cand = {"title": title, "url": url, "content": "",
                        "engine": _GOOGLE_BROWSER_TAG}
                if _result_is_junk(query, cand):
                    continue
                if url in _gdedup or not _result_relevant(query, cand):
                    continue
                _gdedup.add(url)
                _grows.append(cand)
    except Exception as e:
        _failed = True
        _LAST_BROWSER_DEBUG.setdefault(
            _GOOGLE_BROWSER_TAG, {})["error"] = str(e)[:220]
        _GOOGLE_LANE_RECORDS.append(
            "google browser: failed/bound-out "
            f"({type(e).__name__}: {str(e)[:80]})")
    _LAST_BROWSER_DEBUG.setdefault(_GOOGLE_BROWSER_TAG, {}).update(
        {"results": len(_grows)})
    if _grows:
        out.extend(_grows)
    elif _held:
        _GOOGLE_LANE_RECORDS.append(
            "google browser: 0 results (captcha held)")
    elif not _failed:
        _GOOGLE_LANE_RECORDS.append("google browser: 0 results")
    return bool(_grows)

_BING_BROWSER_TAG = "https://www.bing.com"

_BING_AD_URL_RE = re.compile(r'(bing\.com/aclk|bingadservices|ad_domain=)',
                             re.IGNORECASE)

_BING_LINKS_JS = """() => Array.from(document.querySelectorAll('li.b_algo h2 a, .b_algo h2 a'))
    .slice(0, 40).map(a => ({href: a.href || '', text: (a.innerText || '').trim()}))
    .filter(x => x.href && x.href.startsWith('http'))"""

_BING_LANE_RECORDS: list = []

def bing_lane_records() -> list:
    """Rung honesty records authored during the LAST browser_search_public
    call: the bing browser rung's barren, not-engaged, captcha-held and
    failed lines, in the same record wording family as the google rung.
    Cleared at every call's entry."""
    return list(_BING_LANE_RECORDS)

def _bing_decode_url(href: str) -> str:
    """Decode a Bing /ck/a tracking link back to its real target URL: the
    `u` parameter is 'a1' + base64url of the destination."""
    try:
        u = (urllib.parse.parse_qs(
            urllib.parse.urlparse(href).query).get("u") or [""])[0]
        if not u:
            return ""
        if u.startswith("a1"):
            u = u[2:]
        u += "=" * (-len(u) % 4)
        d = base64.urlsafe_b64decode(u.encode()).decode("utf-8", "ignore")
        return d if d.startswith("http") else ""
    except Exception:
        return ""

def _bing_rung(query, max_results, page, ctx, out, lane_end,
               need=None) -> bool:
    """The bing.com/search browser rung, mirroring the google rung exactly:
    same slot-browser machinery, same settle + captcha WAIT-and-retry, same
    not-engaged/failed record family, one attempt per search call, engaged
    after the instances and the google rung when the relevant floor is
    still unmet. /ck/a tracking links decode to their real targets; ads
    filter out. Returns True only when the rung delivered rows."""
    if need:
        if len(out) >= int(need):
            _BING_LANE_RECORDS.append(
                "bing browser: not engaged (earlier bases delivered)")
            return False
    elif out:
        _BING_LANE_RECORDS.append(
            "bing browser: not engaged (earlier bases delivered)")
        return False
    if any(str(h).startswith("captcha: persisted") for h in _CAPTCHA_HOLDS):
        _BING_LANE_RECORDS.append(
            "bing browser: not engaged (captcha persisted on the "
            "earlier bases)")
        return False
    _gg = os.environ.get("GREYSEARCH_BROWSER_LANE", "1").strip().lower()
    if _gg not in ("1", "true", "yes", ""):
        _BING_LANE_RECORDS.append(
            "bing browser: not engaged (browser lane off)")
        return False
    if time.time() > lane_end:
        _BING_LANE_RECORDS.append(
            "bing browser: not engaged (lane cap reached)")
        return False
    _brows: list = []
    _bdedup: set = set()
    _held = False
    _failed = False
    _pw = _pace_guard(_BING_BROWSER_TAG)
    if _pw > 0:
        _BING_LANE_RECORDS.append(
            f"bing browser: pace wait {int(round(_pw))}s "
            "before the search request")
    try:
        page.goto(_BING_BROWSER_TAG + "/search?q="
                  + urllib.parse.quote(query) + f"&count={max_results}",
                  timeout=60000, wait_until="domcontentloaded")
        settle_first_contact(page)
        _bcyc, _bmark = _captcha_cycle(page)
        if _bmark:
            _LAST_BROWSER_DEBUG.setdefault(
                _BING_BROWSER_TAG, {})["captcha"] = _bmark
        if _bcyc.get("engaged") and not _bcyc.get("solved"):
            _held = True
        else:
            _plinks = eval_with_timeout(page, _BING_LINKS_JS, 20.0) or []
            for link in (_plinks if isinstance(_plinks, list)
                         else [])[:max_results]:
                if not isinstance(link, dict):
                    continue
                url = _bing_decode_url((link.get("href") or "").strip()) or (
                    link.get("href") or "").strip()
                title = (link.get("text") or "").strip()
                if not url or _BING_AD_URL_RE.search(url):
                    continue
                if "bing.com" in url:
                    continue
                cand = {"title": title, "url": url, "content": "",
                        "engine": _BING_BROWSER_TAG}
                if _result_is_junk(query, cand):
                    continue
                if url in _bdedup or not _result_relevant(query, cand):
                    continue
                _bdedup.add(url)
                _brows.append(cand)
    except Exception as e:
        _failed = True
        _LAST_BROWSER_DEBUG.setdefault(
            _BING_BROWSER_TAG, {})["error"] = str(e)[:220]
        _BING_LANE_RECORDS.append(
            "bing browser: failed/bound-out "
            f"({type(e).__name__}: {str(e)[:80]})")
    _LAST_BROWSER_DEBUG.setdefault(_BING_BROWSER_TAG, {}).update(
        {"results": len(_brows)})
    if _brows:
        out.extend(_brows)
    elif _held:
        _BING_LANE_RECORDS.append(
            "bing browser: 0 results (captcha held)")
    elif not _failed:
        _BING_LANE_RECORDS.append("bing browser: 0 results")
    return bool(_brows)

_DDG_AD_URL_RE = re.compile(
    r'(duckduckgo\.com/y\.js|/aclick\?|ad_domain=|ad_provider=|\.ad\.)',
    re.IGNORECASE,
)

def _add_result(out, seen, url, title, source, query, max_results):
    if not url or not url.startswith("http") or url in seen:
        return False
    if _result_is_junk(query, {"url": url, "title": title}):
        return False
    seen.add(url)
    out.append({"url": url, "title": title, "source": source})
    return len(out) >= max_results

def _archive_not_engaged(out, max_results):
    """When an earlier direct lane already filled the row budget, the
    archive-org rung never attempts: one honest not-engaged record line."""
    if len(out) >= max_results:
        _ARCHIVE_LANE_RECORDS.append(
            "archive-org: not engaged (rows already filled by earlier lanes)")
        return True
    return False

def _direct_search(query, max_results=10, mode=None):
    """Final keyless direct lanes (no SearXNG at all).

    Order: DuckDuckGo HTML, Wikipedia API, GitHub API, then the Internet
    Archive catalog rung (appended after the existing order): one
    advancedsearch.php attempt per search call, bounded by max_results,
    riding the same per-call opener contract (direct when off, credentialed
    when a proxy mode is on), with details URLs built from the hit identifiers and
    titles from the hit fields. Each lane is independent: a walled or failed
    lane is skipped, never fatal, and the archive rung states its own honest
    record lines (readable via archive_lane_records, produced-rows still
    surface through the direct keyless +N record). Results pass the same
    topical-overlap and ad-URL filters as the instance lanes.
    """
    out, seen = [], set()
    q = urllib.parse.quote(query)
    del _ARCHIVE_LANE_RECORDS[:]

    try:
        t = _proxy_mode.open_search(
            f"https://html.duckduckgo.com/html/?q={q}", timeout=12,
            mode=mode, headers=UA).read().decode("utf-8", "ignore")
        for m in re.finditer(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', t, re.DOTALL):
            url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            if "uddg=" in url:
                url = urllib.parse.unquote(re.sub(r"^.*uddg=", "", url))
            url = url.replace("&amp;", "&").split("&rut=")[0]
            if _DDG_AD_URL_RE.search(url) or "duckduckgo.com" in url:
                continue
            if _add_result(out, seen, url, title, "ddg-html", query, max_results):
                _archive_not_engaged(out, max_results)
                return out
    except Exception:
        pass

    try:
        api = ("https://en.wikipedia.org/w/api.php?action=query&list=search"
               f"&srsearch={q}&format=json&srlimit={max_results}")
        d = json.loads(_proxy_mode.open_search(
            api, timeout=12, mode=mode, headers=UA).read().decode("utf-8"))
        for hit in (d.get("query", {}).get("search") or []):
            title = hit.get("title") or ""
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
                title.replace(" ", "_"))
            if _add_result(out, seen, url, title, "wikipedia-api", query, max_results):
                _archive_not_engaged(out, max_results)
                return out
    except Exception:
        pass

    try:
        api = ("https://api.github.com/search/repositories?q="
               f"{q}&per_page={max_results}")
        d = json.loads(_proxy_mode.open_search(
            api, timeout=12, mode=mode, headers=UA).read().decode("utf-8"))
        for item in (d.get("items") or []):
            url = item.get("html_url") or ""
            title = item.get("full_name") or ""
            if _add_result(out, seen, url, title, "github-api", query, max_results):
                _archive_not_engaged(out, max_results)
                return out
    except Exception:
        pass

    try:
        api = ("https://archive.org/advancedsearch.php?q="
               f"{q}&output=json&rows={max_results}")
        d = json.loads(_proxy_mode.open_search(
            api, timeout=12, mode=mode, headers=UA).read().decode("utf-8"))
        hits = (d.get("response") or {}).get("docs") or []
        if not hits:
            _ARCHIVE_LANE_RECORDS.append("archive-org: 0 candidates")
        for hit in hits:
            ident = str(hit.get("identifier") or "").strip()
            raw_title = hit.get("title") or ""
            if isinstance(raw_title, (list, tuple)):
                raw_title = " ".join(str(t) for t in raw_title)
            title = str(raw_title).strip()
            if not ident or not title:
                continue
            url = ("https://archive.org/details/"
                   + urllib.parse.quote(ident, safe=""))
            if _add_result(out, seen, url, title, "archive-org", query,
                           max_results):
                return out
    except Exception as e:
        _ARCHIVE_LANE_RECORDS.append(
            "archive-org: tried 1 catalog attempt, failed "
            f"({type(e).__name__}: {str(e)[:80]})")

    return out

def search(query, max_results=12, timeout=15, engines=None, search_proxy=None):
    """The ladder: optional local :8888 → searx.space instances → direct keyless lanes.

    The searx.space instance lane is not dead: the JSON API is bot-walled
    (Anubis "not a bot" HTML) on most public instances, but the BROWSER lane
    (one task-3 window) passes the check. So lane 2 tries the JSON API as a
    fast pre-check on every harvested instance, and if none answer JSON, it
    falls through to a single browser search across instances instead of
    giving up. Never pretend to search.

    engines: optional user selection merged ADDITIVELY into the
    local lane's engines= list (LOCAL_ENGINES ∪ selection, dedup, stable
    order); empty/None keeps that URL byte-for-byte as before. The remaining
    lanes cannot carry it: public instances are form-driven (see
    browser_search_public) and the direct lanes are engineless by nature.

    The local lane is ALWAYS attempted (loopback never changes transport);
    the old GREYSEARCH_LOCAL_SEARX gate that silently skipped it is deleted.

    search_proxy (manual proxy mode): "off" (default) or "on"
    ("on" alias); unset means GREYSEARCH_SEARCH_PROXY decides. Every
    external SEARCH hop here (instances.json harvest, instance probes,
    direct keyless lanes) builds a per-call opener from the mode; the local
    :8888 lane never changes transport. A mode that cannot be honoured
    holds the external lanes back instead of sending them direct silently,
    and the ladder names the mode and the state once.
    """
    t0 = time.time()
    proxy_res = _proxy_mode.prepared(search_proxy)
    ladder = [_proxy_mode.ladder_note(proxy_res)]
    external_ok = bool(proxy_res.get("ok"))
    try:
        q = urllib.parse.quote(query)
        if engines:
            merged_engs = ",".join(dict.fromkeys(
                (LOCAL_ENGINES + "," + ",".join(
                    str(x).strip().lower() for x in engines
                    if str(x).strip())).split(",")))
        else:
            merged_engs = LOCAL_ENGINES
        engines_q = urllib.parse.quote(merged_engs, safe=",")
        url = f"{LOCAL}/search?q={q}&format=json&engines={engines_q}"
        d = json.loads(_fetch(url, timeout).read().decode("utf-8"))
        rs = d.get("results", [])
        if rs and not (len(rs) == 0 and d.get("unresponsive_engines")):
            return {"ok": True, "source": "local:8888", "results": rs,
                    "ladder": ladder + ["local"]}
    except Exception:
        pass

    insts = _harvest_instances(mode=proxy_res) if external_ok else []
    budget = float(os.environ.get("GREYSEARCH_INSTANCE_BUDGET_S", "15") or 15)
    per_instance = float(os.environ.get("GREYSEARCH_INSTANCE_TIMEOUT_S", "5") or 6)
    deadline = time.time() + budget
    for inst in insts[:10]:
        if time.time() > deadline:
            break
        rs = _search_via_instance(inst, query, max_results, timeout=per_instance,
                                  mode=proxy_res)
        if rs:
            return {"ok": True, "source": f"searx.space: {inst}", "results": rs,
                    "ladder": ladder + ["local", inst]}

    browser_urls = list(insts)
    for owner_inst in ("https://search.hbubli.cc", "https://searx.ononoki.org"):
        if owner_inst not in browser_urls:
            browser_urls.append(owner_inst)
    _bl = os.environ.get("GREYSEARCH_BROWSER_LANE", "1").lower()
    use_browser_lane = _bl in ("1", "true", "yes", "")
    _holds = []
    _pace = []
    try:
        if external_ok and use_browser_lane and time.time() < deadline + 20:
            brs = browser_search_public(query, max_results=max_results,
                                        instances=browser_urls[:4], timeout=20)
            _holds = _captcha_holds()
            _pace = pace_wait_records()
        else:
            brs = []
        if brs:
            return {"ok": True, "source": "searx.space browser",
                    "results": brs,
                    "ladder": ladder + _pace + _holds
                    + ["local", "searx.space-json",
                       "searx.space-browser"]}
    except Exception:
        pass

    rs = _direct_search(query, max_results, mode=proxy_res) if external_ok else []
    if rs:
        return {"ok": True, "source": "direct", "results": rs,
                "ladder": ladder + _pace + _holds
                + ["local", "searx.space", "direct"]}

    return {"ok": False, "source": "none", "results": [],
            "ladder": ladder + _pace + _holds + ["local", "searx.space",
                                                 "direct"],
            **({"error": str(proxy_res.get("error"))}
               if not external_ok else {}),
            "elapsed": time.time() - t0}

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "test"
    r = search(q)
    print(f"source: {r['source']} | results: {len(r['results'])} | ladder: {r['ladder']}")
    for x in r["results"][:5]:
        print(f"  {(x.get('title') or '')[:60]} -> {(x.get('url') or '')[:70]}")
