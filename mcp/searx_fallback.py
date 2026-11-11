#!/usr/bin/env python3
"""searx_fallback.py — SearXNG fallback ladder:
1. local :8888 (working engines only — suspended ones excluded)
2. public instances from https://searx.space/data/instances.json (HARDCODED discovery source)
3. if all time out: direct keyless search lanes (DDG html — the Bing RSS lane is deleted)

The searx.space discovery source is HARDCODED — never bypass.
"""
import urllib.request, urllib.parse, json, time, random, re, os, ssl

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
    """page.evaluate with a hard wall + wedged-tab recovery (pass 7 armor)."""
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
    """Bot-detection settle — called after a NEW host's first page load
    (owner: 'give it 20-30 seconds when the page first loads')."""
    try:
        page.wait_for_timeout(int(_SETTLE_S * 1000))
    except Exception:
        pass

_INSTANCE_READY: dict = {}

_AUTH_SETTLE_S = 30.0

def _enable_all_engines_every_tab(page) -> dict:
    """Enable EVERY search engine on EVERY preferences tab.

    STANDING RULES (recorded in the memory dir): THE BOT CHECKS ON THE SEARX.SPACE
    SITES YOU MUST WAIT 30 SECONDS AND LET THEM AUTHENTICATE FIRST. THEN YOU
    CAN USE THEM AFTER CHANGING PREFERENCES TO ENABLE ALL SEARCH ENGINES.
    DO THAT FOR ALL, NOT JUST WEB. FOR ALL AVAILABLE TABS LIKE VIDEO/IT/SOCIAL
    MEDIA/ETC. MUST ALL BE ENABLED."

    The SearXNG preferences page groups engines into category tabs (general,
    it, images, videos, news, maps, music, …). Each tab has its own
    "Enable all engines" button, and Playwright CANNOT click a button on a
    hidden tab — so we must click each tab first to make its pane visible,
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
    a human does, ONCE per process — load its home page, WAIT 30 SECONDS for
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

def _fetch(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)

def _harvest_instances(force=False, limit=10):
    """Pull searx.space/data/instances.json (fixed source). Returns live instance URLs."""
    if os.path.exists(ROSTER_FILE) and not force:
        if time.time() - os.path.getmtime(ROSTER_FILE) < 86400 * 3:
            try:
                rost = json.load(open(ROSTER_FILE))
                if rost.get("instances"):
                    return rost["instances"]
            except Exception:
                pass
    try:
        data = json.loads(_fetch(SEARX_SPACE_DATA, 15).read().decode("utf-8"))
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
        h = _fetch(SEARX_SPACE, 15).read().decode("utf-8", "ignore")
        doms = sorted(set(re.findall(r'https://([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-z]{2,})/?["<>\\s]', h)))
        doms = [d for d in doms if not any(x in d for x in (".onion", "cryptcheck", "github", "helpdesk", "about.", "status", "uptime", "searx.space"))]
        return [f"https://{d}/" for d in doms[:limit]]
    except Exception:
        pass
    return []

def _search_via_instance(base_url, query, max_results=10, timeout=15):
    """Try one SearXNG instance via JSON API with instance-default engines.

    30s warm-up before first contact with this remote host (tarpit defense,
    once per host), then junk-filter the results; generated affiliate /
    trending-feed pages never reach a caller. A host whose entire result set
    is junk is benched for the rest of the process."""
    if _is_benched(base_url):
        return []
    _warm_remote_host(base_url)
    try:
        q = urllib.parse.quote(query, safe="")
        url = f"{base_url.rstrip('/')}/search?q={q}&format=json"
        if INSTANCE_ENGINES:
            url += f"&engines={urllib.parse.quote(INSTANCE_ENGINES, safe=',')}"
        r = _fetch(url, timeout)
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

def _gs_slot() -> dict:
    """Resolve greysearch's slot the exact way browser_session does (env
    RESEARCH_TASK first, default task-3) — one resolution point, no drift."""
    return _bs()._cfg()

def _gs_window():
    """Return the shared slot page via browser_session — the single CDP
    connection owner (per-thread cache, auto-launch when down). Everything
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
    guard lock — sleeping while holding it serialized all parallel warm-ups
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

def browser_search_public(query, max_results=10, instances=None, timeout=45):
    """Search the owner's two public SearXNG instances in a real browser.

    Human-pace rules:
    - use search.hbubli.cc and searx.ononoki.org only;
    - 20-30 second first-contact settle for bot detection;
    - enable all engines in preferences once per process;
    - one search at a time at a human pace;
    - reject off-topic result sets instead of feeding them to a course.
    """
    _LAST_BROWSER_DEBUG.clear()
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
        urls = [u.rstrip("/") for u in instances]
    else:
        urls = ["https://search.hbubli.cc", "https://searx.ononoki.org"]
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
                try:
                    ctx.clear_cookies()
                except Exception:
                    pass
                _warm_remote_host(base)
                ensure_instance_ready(browser, base, page=page)
                page.goto(base + "/", timeout=60000,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
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
                if out and _relevant(query, out):
                    break
                out = []
            except Exception as e:
                _LAST_BROWSER_DEBUG.setdefault(base, {})[
                    "error"] = str(e)[:220]
                continue
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

def _direct_search(query, max_results=10):
    """Final keyless direct lanes (no SearXNG at all).

    Order: DuckDuckGo HTML, Wikipedia API, GitHub API. Each lane
    is independent: a walled or failed lane is skipped, never fatal. Results
    pass the same topical-overlap and ad-URL filters as the instance lanes.
    """
    out, seen = [], set()
    q = urllib.parse.quote(query)

    try:
        t = urllib.request.urlopen(urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={q}", headers=UA),
            timeout=12).read().decode("utf-8", "ignore")
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
                return out
    except Exception:
        pass

    try:
        api = ("https://en.wikipedia.org/w/api.php?action=query&list=search"
               f"&srsearch={q}&format=json&srlimit={max_results}")
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(api, headers=UA), timeout=12).read().decode("utf-8"))
        for hit in (d.get("query", {}).get("search") or []):
            title = hit.get("title") or ""
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(
                title.replace(" ", "_"))
            if _add_result(out, seen, url, title, "wikipedia-api", query, max_results):
                return out
    except Exception:
        pass

    try:
        api = ("https://api.github.com/search/repositories?q="
               f"{q}&per_page={max_results}")
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(api, headers=UA), timeout=12).read().decode("utf-8"))
        for item in (d.get("items") or []):
            url = item.get("html_url") or ""
            title = item.get("full_name") or ""
            if _add_result(out, seen, url, title, "github-api", query, max_results):
                return out
    except Exception:
        pass

    return out

def search(query, max_results=12, timeout=15, engines=None):
    """The ladder: optional local :8888 → searx.space instances → direct keyless lanes.

    AUDIT FIX: the searx.space instance lane is NOT dead —
    the JSON API is bot-walled (Anubis "not a bot" HTML) on most public
    instances, but the BROWSER lane (one task-3 window) passes the check.
    So lane 2 tries the JSON API as a fast pre-check on every harvested
    instance, and if none answer JSON, it falls through to a single browser
    search across instances instead of giving up. Never pretend to search.

    engines (2026-11-03): optional user selection merged ADDITIVELY into the
    local lane's engines= list (LOCAL_ENGINES ∪ selection, dedup, stable
    order); empty/None keeps that URL byte-for-byte as before. The remaining
    lanes cannot carry it: public instances are form-driven (see
    browser_search_public) and the direct lanes are engineless by nature.
    """
    t0 = time.time()
    try:
        if not USE_LOCAL:
            raise RuntimeError("local SearXNG lane disabled (set GREYSEARCH_LOCAL_SEARX=1 to enable)")
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
            return {"ok": True, "source": "local:8888", "results": rs, "ladder": ["local"]}
    except Exception:
        pass

    insts = _harvest_instances()
    budget = float(os.environ.get("GREYSEARCH_INSTANCE_BUDGET_S", "15") or 15)
    per_instance = float(os.environ.get("GREYSEARCH_INSTANCE_TIMEOUT_S", "5") or 6)
    deadline = time.time() + budget
    for inst in insts[:10]:
        if time.time() > deadline:
            break
        rs = _search_via_instance(inst, query, max_results, timeout=per_instance)
        if rs:
            return {"ok": True, "source": f"searx.space: {inst}", "results": rs, "ladder": ["local", inst]}

    browser_urls = list(insts)
    for owner_inst in ("https://search.hbubli.cc", "https://searx.ononoki.org"):
        if owner_inst not in browser_urls:
            browser_urls.append(owner_inst)
    _bl = os.environ.get("GREYSEARCH_BROWSER_LANE", "1").lower()
    use_browser_lane = _bl in ("1", "true", "yes", "")
    try:
        if use_browser_lane and time.time() < deadline + 20:
            brs = browser_search_public(query, max_results=max_results,
                                        instances=browser_urls[:4], timeout=20)
        else:
            brs = []
        if brs:
            return {"ok": True, "source": "searx.space browser",
                    "results": brs, "ladder": ["local", "searx.space-json", "searx.space-browser"]}
    except Exception:
        pass

    rs = _direct_search(query, max_results)
    if rs:
        return {"ok": True, "source": "direct", "results": rs, "ladder": ["local", "searx.space", "direct"]}

    return {"ok": False, "source": "none", "results": [], "ladder": ["local", "searx.space", "direct"], "elapsed": time.time() - t0}

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "test"
    r = search(q)
    print(f"source: {r['source']} | results: {len(r['results'])} | ladder: {r['ladder']}")
    for x in r["results"][:5]:
        print(f"  {(x.get('title') or '')[:60]} -> {(x.get('url') or '')[:70]}")
