#!/usr/bin/env python3
"""
Patchright-based web scraper - adapter over the session's ONE slot browser.

Default path: every fetch runs through browser_session (the single CDP
connection holder) on the patchright-launched headless stealth Chromium,
headless, persistent profile, CDP port owned by this session's assigned task
slot. GREYSEARCH_ALLOW_PRIVATE_BROWSER=1 restores the legacy private-Xvfb
browser below (private display pool :90-:99) - opt-in only, never default.

Extraction is centralized in browser_session.fetch_text; the extractor JS
constants at the bottom of this module are the single definition both files
import. All media/tables/links/code come from THE SAME page object that
fetched the URL; text keeps paragraph structure; failures return with
reasons, never swallowed. No API keys are required - fetching runs keyless
on the machine's own slot browsers.
"""

from __future__ import annotations

import json
import os
import re
import subprocess as _sp
import threading as _th
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

try:
    from patchright.sync_api import sync_playwright
    _HAS_PATCHRIGHT = True
except Exception:
    sync_playwright = None
    _HAS_PATCHRIGHT = False

try:
    from . import research_injection as _rij
except Exception:
    import research_injection as _rij

import proxy_mode as _proxy_mode

try:
    from . import browser_ports as _browser_ports
    from browser_session import eval_with_timeout
except Exception:
    try:
        import browser_ports as _browser_ports
    except Exception:
        _browser_ports = None

_DISPLAY_RECLAIM_LOG = os.path.expanduser("~/.cache/greysearch/xvfb-reaper.log")

_HTML_CAP = 400_000

_BOILER_LINES = [
    re.compile(r"(?im)^.{0,140}\bcookie\s+(policy|notice|consent|banner).{0,140}$"),
    re.compile(r"(?im)^.{0,60}\ball\s+rights\s+reserved\b.{0,80}$"),
    re.compile(r"(?im)^.{0,120}(→|>>|»)\s*subscribe\s+(now|today)\b.{0,60}$"),
    re.compile(r"(?im)^\s*[-–—•»>]?\s*subscribe\s+(now|today)\b.{0,20}$"),
    re.compile(r"(?im)^.{0,80}\bsubscribe\s+(now\s+)?to\s+(our|my|the)\s+newsletter\b.{0,120}$"),
    re.compile(r"(?im)^.{0,40}\bfollow\s+us\s+on\b.{0,120}$"),
    re.compile(r"(?im)^.{0,40}\bmanage\s+(cookies|preferences|privacy)\b.{0,80}$"),
    re.compile(r"(?im)^.{0,80}\baffiliate\s+(disclosure|links?)\b.{0,120}$"),
    re.compile(r"(?im)^.{0,80}\b(we|this (site|page)) (may )?(earn|receive) (a )?commission\b.{0,120}$"),
    re.compile(r"(?im)^(\s*[-•·▪‣–*]\s*){1,3}$"),
    re.compile(r"(?im)^\s*\d{0,2}[.)]\s*$"),
    re.compile(r"(?im)^\s*\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{2,4}\s*$"),
    re.compile(r"(?im)^.{0,30}\bopen in (a new tab|new tab)\b.{0,60}$"),
    re.compile(r"(?im)^\s*(reply|replies|all\s+replies)\s*$"),
    re.compile(r"(?im)^\s*all\s+reactions\s*$"),
    re.compile(r"(?im)^\s*on\s+our\s+radar\s*$"),
    re.compile(r"(?im)^\s*(sign|log)\s?in(\s+(up|to\s+(comment|reply)))?\s*$"),
    re.compile(r"(?im)^\s*(skip to (main )?content|jump to content|back to top)\s*$"),
    re.compile(r"(?im)^\s*copy\s+link\s*$"),
    re.compile(r"(?im)^.{0,40}\badd\s.{0,30}on\s(google( discover)?|facebook|twitter|x|mastodon|linkedin)\b( discover)?\s*$"),
    re.compile(r"(?im)^.{0,60}\bshare this (story|article|page|post|guide)\b.{0,80}$"),
    re.compile(r"(?im)^\s*advertisements?\s*$"),
    re.compile(r"(?im)^.{0,20}\bhere (is|'s) (a|an) .{0,40}(summary|overview) (of|for) (the|this) (story|article|post|guide|topic|page)s?\b:? .{0,60}$"),
    re.compile(r"(?im)^\s*published\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}([,/. -]+\d{4})?[, ]*(at )?\d{0,2}:?\d{0,2}\s*(am|pm|et)?(.{0,40})?$"),
    re.compile(r"(?im)^\s*i\s+(accept|agree)\b.{0,100}\b(cookies?\b|consent\b).{0,60}$"),
    re.compile(r"(?im)^.{0,40}\bby\s+(signing\s+up|subscribing)\b.{0,160}$"),
    re.compile(r"(?im)^.{0,80}\b(find|follow)\s+(me|us)\s+on\b.{0,140}$"),
    re.compile(r"(?im)^\s*(you\s+(might|may|'ll)\s+also\s+(like|love|enjoy)|related\s+(posts|articles|recipes|stories)|recommended\s+for\s+you|more\s+like\s+this)\s*$"),
    re.compile(r"(?im)^.{0,40}\bproudly\s+powered\s+by\b.{0,80}$"),
]
_BOILER_INLINE = [
    re.compile(r"(?i)accept\s+all\s+cookies?\b.{0,60}"),
    re.compile(r"(?i)skip\s+to\s+content\b"),
    re.compile(r"(?i)please\s+enable\s+(javascript|cookies)\b.{0,60}"),
    re.compile(r"(?i)here\s+is\s+a\s+fact-based\s+summary\s+of\s+the\s+(story|article)\s+contents:?"),
]

_SCROLL_JS = """() => new Promise(res => {
    let h = document.documentElement.scrollHeight, y = 0, n = 0;
    const step = () => {
        window.scrollTo(0, y); y += 900; n++;
        h = document.documentElement.scrollHeight;
        if (y < h && n < 30) { setTimeout(step, 120); }
        else { window.scrollTo(0, 0); res(n); }
    };
    if (document.readyState !== 'complete') {
        window.addEventListener('load', () => {
            h = document.documentElement.scrollHeight; step();
        }, { once: true });
    } else { step(); }
})"""

_LINKS_JS = """() => Array.from(document.querySelectorAll('a[href]')).slice(0, 800).map(a => ({
    href: a.href, text: (a.innerText || a.textContent || '').trim().slice(0, 200)
})).filter(x => x.href.startsWith('http'))"""

_IMAGES_JS = """() => Array.from(document.querySelectorAll('img[data-src], img[src]')).slice(0, 400).map(i => ({
    src: i.currentSrc || i.src || i.dataset.src || '', alt: (i.alt || '').slice(0, 200),
    w: i.naturalWidth || 0, h: i.naturalHeight || 0
})).filter(i => i.src.startsWith('http'))"""

_VIDEO_TAG_JS = """() => Array.from(document.querySelectorAll('video')).map(v => ({
    src: (v.currentSrc || v.src || ''), title: (v.title || '').slice(0, 200)
})).filter(v => v.src)"""

_IFRAME_VIDEO_JS = """() => Array.from(document.querySelectorAll('iframe')).map(f => ({
    src: f.src, title: (f.title || '').slice(0, 200)
})).filter(f => f.src && /youtube\\.com|youtu\\.be|vimeo\\.com|player\\./.test(f.src))"""

_TABLES_JS = """() => Array.from(document.querySelectorAll('table')).slice(0, 60).map(t => {
    const rows = Array.from(t.querySelectorAll('tr')).slice(0, 250).map(tr =>
        Array.from(tr.querySelectorAll('th,td')).slice(0, 30).map(c => (c.innerText || '').trim().slice(0, 400)));
    const cap = t.querySelector('caption');
    return {rows, caption: cap ? (cap.innerText || '').trim().slice(0, 300) : ''};
}).filter(t => t.rows && t.rows.length)"""

_HEADINGS_JS = """() => Array.from(document.querySelectorAll('h1,h2,h3,h4')).slice(0, 120).map(h => ({
    level: h.tagName, text: (h.innerText || '').trim().slice(0, 400), id: h.id || ''
})).filter(h => h.text)"""

_CODE_JS = """() => Array.from(document.querySelectorAll('pre code, pre')).slice(0, 40)
    .map(c => (c.innerText || '').slice(0, 8000)).filter(s => s.trim().length > 20)"""

_META_JS = """() => {
    const meta = {};
    document.querySelectorAll('meta[name], meta[property]').forEach(t => {
        const k = t.name || t.property || '';
        if (k && t.content) meta[k] = t.content.slice(0, 400);
    });
    return meta;
}"""

_AUDIO_JS = """() => Array.from(document.querySelectorAll('audio')).map(a => ({
    src: a.currentSrc || a.src || '',
    title: a.title || ''
})).filter(a => a.src)"""

_PDF_JS = """() => {
    const pdfs = [];
    // PDF links
    document.querySelectorAll('a[href]').forEach(a => {
        const href = a.href;
        if (href.toLowerCase().endsWith('.pdf')) {
            pdfs.push({src: href, title: a.title || a.textContent || ''});
        }
    });
    // PDF embed/object
    document.querySelectorAll('embed[type="application/pdf"], object[type="application/pdf"]').forEach(el => {
        const src = el.src || el.data || '';
        if (src) pdfs.push({src: src, title: el.title || ''});
    });
    return pdfs;
}"""

_CANVAS_JS = """() => Array.from(document.querySelectorAll('canvas')).map(c => ({
    width: c.width,
    height: c.height
}))"""

_IFRAME_JS = """() => Array.from(document.querySelectorAll('iframe')).map(f => ({
    src: f.src,
    title: f.title || ''
})).filter(f => f.src)"""

_WAYBACK_AVAIL_BASE = "https://archive.org/wayback/available?url="

_WAYBACK_GATE_STATUSES = (404, 410, 500, 502, 503, 504)

_WAYBACK_DEAD_LINK_RE = re.compile(
    r"(name resolution|nxdomain|connection[ _]refused|connection[ _]reset|"
    r"connection[ _]timed[ _]out|err_empty_response|"
    r"err_internet_disconnected|err_name_not_resolved)",
    re.IGNORECASE)

_WAYBACK_TRIED: Dict[str, bool] = {}

_WAYBACK_LOCK = _th.Lock()

_WAYBACK_UA = {"User-Agent":
               "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "Chrome/151 Safari/537.36"}

def _wayback_once(url: str) -> bool:
    """ONE availability consult + one archived fetch per dead URL per
    process: process-wide memo, order-preserving, capped at 4096 hosts."""
    with _WAYBACK_LOCK:
        fresh = url not in _WAYBACK_TRIED
        _WAYBACK_TRIED.setdefault(url, True)
        excess = len(_WAYBACK_TRIED) - 4096
        if excess > 0:
            for k in list(_WAYBACK_TRIED)[:excess]:
                del _WAYBACK_TRIED[k]
        return fresh

def _wayback_knob_on() -> bool:
    """GREYSEARCH_WAYBACK kill switch (default on): off/0/false/no never
    consults the machine and states its own skipped line."""
    _on = os.environ.get("GREYSEARCH_WAYBACK", "1").strip().lower()
    return _on in ("1", "true", "yes", "")

def _wayback_knob_float() -> float:
    """GREYSEARCH_WAYBACK_MAX_S bounds the availability hop (default 45s);
    0 also means the machine is walled out for the run."""
    try:
        v = float(os.environ.get("GREYSEARCH_WAYBACK_MAX_S") or 45.0)
    except ValueError:
        v = 45.0
    return max(0.0, v)

def wayback_dead_status(status: int) -> bool:
    """True only for statuses that mean the page is GONE (404/410 and the
    gateway 5xx fetch_text can see): access walls (401/403/407/429/408) are
    not dead and never consult the machine."""
    return int(status or 0) in _WAYBACK_GATE_STATUSES

def wayback_available(url: str, mode: Any = None) -> Optional[dict]:
    """Ask archive.org's availability API for the closest archived copy of
    url. The availability hop is a SEARCH-class request: it rides the same
    per-call opener contract as every other search transport (direct when
    off, credentialed when the mode is on), never a scrape transport. Transport
    and parse failures ESCAPE so the caller can carry the exception class;
    a plain absence (no closest snapshot) returns None."""
    api = _WAYBACK_AVAIL_BASE + urllib.parse.quote(url, safe="")
    body = _proxy_mode.open_search(api, timeout=min(12.0, _wayback_knob_float()),
                                   mode=mode, headers=_WAYBACK_UA).read()
    snap = ((json.loads(body.decode("utf-8"))
             .get("archived_snapshots") or {}).get("closest") or {})
    if str((snap or {}).get("available") or "").strip().lower() == "true":
        return snap
    return None

def _url_domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.split("@")[-1].split(":")[0]
    return re.sub(r"^www\.", "", host).strip().lower()

def wayback_rescue(url: str, dead_status: int = 0, dead_error: str = "",
                   mode: Any = None) -> Tuple[Optional[dict], str]:
    """Before a dead URL's scrape is declared failed, consult the wayback
    machine via the availability API (the shared search opener contract,
    mode honored),
    and when a snapshot exists scrape the ARCHIVED copy with provenance:
    the record's url stays the ORIGINAL, final_url names the archived copy,
    via_wayback notes 'via wayback', metadata carries the timestamp, and
    domain is the original host minus www. The archived hop is a scrape
    (CDP slot browser, direct, never proxied) and an already-archived URL
    never consults, so there is no recursion. One availability consult and
    one archived fetch per dead URL per process. A miss returns (None,
    honest-note) without mutating the original error text; a not-applicable
    gate returns (None, '') so the plain failure stands as authored."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None, ""
    if "web.archive.org" in url:
        return None, "skipped (already an archived copy)"
    if dead_status:
        if not wayback_dead_status(dead_status):
            return None, ""
    elif not dead_error or not _WAYBACK_DEAD_LINK_RE.search(dead_error):
        return None, ""
    if not _wayback_knob_on():
        return None, "skipped (wayback engine off)"
    if _wayback_knob_float() <= 0.0:
        return None, "skipped (wayback wall cap)"
    if not _wayback_once(url):
        return None, "skipped (already tried this run)"
    try:
        snap = wayback_available(url, mode=mode)
    except Exception as e:
        return None, f"unavailable ({type(e).__name__}: {str(e)[:80]})"
    if snap is None:
        return None, "miss (no archived copy)"
    ts = str((snap or {}).get("timestamp") or "").strip()
    archived = str((snap or {}).get("url") or "").strip()
    if not archived:
        return None, "miss (empty snapshot url)"
    try:
        try:
            from . import browser_session as _bs
        except ImportError:
            import browser_session as _bs
        r = _bs.fetch_text(archived)
    except Exception as e:
        return None, f"failed ({type(e).__name__}: {str(e)[:80]})"
    if not isinstance(r, dict):
        return None, "failed (archived copy returned no record)"
    if not r.get("ok"):
        rerr = str(r.get("error") or "empty result")[:80]
        return None, f"failed (archived copy: {rerr})"
    resc = dict(r)
    resc["url"] = url
    resc["via_wayback"] = f"via wayback: {archived} (timestamp {ts})"
    resc["lane"] = "cdp-slot+wayback"
    resc["domain"] = _url_domain(url)
    resc.setdefault("scrape_transport", _proxy_mode.scrape_guard_note())
    meta = resc.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    meta["via_wayback"] = archived
    meta["wayback_timestamp"] = ts
    resc["metadata"] = meta
    return resc, ""


def chrome_exe() -> str:
    """Scrape-browser executable ladder: patchright bundled build ->
    system chromium -> ms-playwright cache. The bundled path vanishes when
    version dirs get cleaned, which previously crashed every private
    spawn."""
    if _HAS_PATCHRIGHT:
        try:
            with sync_playwright() as p:
                cand = p.chromium.executable_path
            if cand and os.path.exists(cand):
                return cand
        except Exception:
            pass
    for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser",
                 "/usr/bin/google-chrome-stable"):
        if os.path.exists(cand):
            return cand
    import glob as _glob
    for d in sorted(_glob.glob(
            os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")),
            reverse=True):
        if os.path.exists(d):
            return d
    raise FileNotFoundError("no chromium executable found for scraper")

def _shutdown() -> None:
    """Close context/browser + playwright, kill our Xvfb, clear lockfiles."""
    if PatchrightScraper._shutdown_done:
        return
    PatchrightScraper._shutdown_done = True
    try:
        if PatchrightScraper._ctx is not None:
            PatchrightScraper._ctx.close()
    except Exception:
        pass
    try:
        if PatchrightScraper._pw is not None:
            PatchrightScraper._pw.stop()
    except Exception:
        pass
    PatchrightScraper._ctx = None
    PatchrightScraper._browser = None
    PatchrightScraper._pw = None
    try:
        if PatchrightScraper._xvfb is not None:
            PatchrightScraper._xvfb.terminate()
            time.sleep(0.4)
            PatchrightScraper._xvfb.kill()
    except Exception:
        pass
    if PatchrightScraper._display_lockfile:
        try:
            os.unlink(PatchrightScraper._display_lockfile)
        except Exception:
            pass

class PatchrightScraper:
    """Private stealth Chromium scraper: one browser per PROCESS (class-shared),
    one reused page per instance, every extraction from the fetching page."""

    _CLS_LOCK = _th.RLock()
    _pw: Any = None
    _browser: Any = None
    _ctx: Any = None
    _xvfb: Any = None
    _display: str = ""
    _display_lockfile: str = ""
    _profile_dir: str = ""
    _pages_fetched: int = 0
    _shutdown_done: bool = False
    _display_reclaims: List[Dict[str, Any]] = []

    def __init__(self,
                 stealth_level: str = "high",
                 timeout: int = 25,
                 user_agent_pool: Optional[List[str]] = None):
        """stealth_level/timeout/user_agent_pool kept for API compat; real
        stealth comes from patchright itself. timeout = per-navigation seconds."""
        self.stealth_level = stealth_level
        self.timeout = timeout
        self.user_agent_pool = user_agent_pool or ["patchright-managed"]
        self._page: Any = None
        self._consecutive_failures = 0

    def _ensure_xvfb(self) -> str:
        """Claim a private Xvfb display :90-:99 (lockfile-claimed, race-safe;
        never :0, never a task slot, never the comms browser)."""
        if PatchrightScraper._xvfb is not None and PatchrightScraper._display:
            return PatchrightScraper._display

        env_display = os.environ.get("DISPLAY", "").strip()
        if env_display and env_display != ":0":
            n = env_display.lstrip(":")
            try:
                n_int = int(n)
            except ValueError:
                n_int = None
            if (n_int is None or 60 <= n_int <= 199) and \
                    os.path.exists(f"/tmp/.X11-unix/X{n}"):
                PatchrightScraper._display = env_display
                PatchrightScraper._display_lockfile = ""
                PatchrightScraper._xvfb = None
                return PatchrightScraper._display

        def _display_serves(n: int) -> bool:
            try:
                r = _sp.run(["pgrep", "-f", f"Xvfb :{n} "], stdout=_sp.PIPE)
            except Exception:
                return True
            for tok in r.stdout.decode().split():
                try:
                    if open(f"/proc/{tok}/comm").read().strip() == "Xvfb":
                        return True
                except Exception:
                    continue
            return False

        for n in range(90, 100):
            xsocket = f"/tmp/.X11-unix/X{n}"
            lockfile = f"/tmp/greysearch-xvfb-{n}.lock"
            if _browser_ports is not None:
                try:
                    reclaim = _browser_ports.reap_orphan_display(n)
                except Exception as exc:
                    reclaim = {"display": n, "reclaimed": False,
                               "reason": f"reaper error: {exc}"}
                if reclaim.get("reclaimed"):
                    PatchrightScraper._display_reclaims.append(reclaim)
                    try:
                        os.makedirs(os.path.dirname(_DISPLAY_RECLAIM_LOG),
                                    exist_ok=True)
                        with open(_DISPLAY_RECLAIM_LOG, "a") as f:
                            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                                    f"reclaimed orphan Xvfb :{n} "
                                    f"pids={reclaim.get('killed')}\n")
                    except Exception:
                        pass
            if os.path.exists(xsocket) and not os.path.exists(lockfile):
                if _display_serves(n):
                    continue
                for stale in (xsocket, f"/tmp/.X{n}-lock"):
                    try:
                        os.unlink(stale)
                    except Exception:
                        pass
            try:
                if os.path.exists(lockfile):
                    try:
                        owner = int(open(lockfile, "r").read().strip() or "0")
                        os.kill(owner, 0)
                    except Exception:
                        owner_dead = True
                    else:
                        owner_dead = False
                    if owner_dead:
                        for stale in (lockfile, xsocket, f"/tmp/.X{n}-lock"):
                            try:
                                os.unlink(stale)
                            except Exception:
                                pass
                if os.path.exists(lockfile) and not os.path.exists(xsocket):
                    os.unlink(lockfile)
                fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
            except FileExistsError:
                continue
            except Exception:
                continue
            try:
                proc = _sp.Popen(["Xvfb", f":{n}", "-screen", "0", "1400x1000x24",
                                  "-nolisten", "tcp"],
                                 stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            except Exception:
                try:
                    os.unlink(lockfile)
                except Exception:
                    pass
                continue
            time.sleep(0.8)
            if os.path.exists(xsocket):
                PatchrightScraper._xvfb = proc
                PatchrightScraper._display = f":{n}"
                PatchrightScraper._display_lockfile = lockfile
                return PatchrightScraper._display
            try:
                os.unlink(lockfile)
            except Exception:
                pass
            continue

        allow_main = os.environ.get("GREYSEARCH_ALLOW_MAIN_DISPLAY", "").lower() in ("1", "true", "yes")
        if allow_main:
            n = 0
            xsocket = f"/tmp/.X11-unix/X{n}"
            lockfile = f"/tmp/greysearch-xvfb-{n}.lock"
            if os.path.exists(xsocket) and not os.path.exists(lockfile):
                try:
                    if os.path.exists(lockfile) and not os.path.exists(xsocket):
                        os.unlink(lockfile)
                    fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                except FileExistsError:
                    pass
                except Exception:
                    pass
                else:
                    try:
                        proc = _sp.Popen(["Xvfb", f":{n}", "-screen", "0", "1400x1000x24",
                                          "-nolisten", "tcp"],
                                         stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    except Exception:
                        try:
                            os.unlink(lockfile)
                        except Exception:
                            pass
                    else:
                        time.sleep(0.8)
                        if os.path.exists(xsocket):
                            PatchrightScraper._xvfb = proc
                            PatchrightScraper._display = f":{n}"
                            PatchrightScraper._display_lockfile = lockfile
                            return PatchrightScraper._display
                    try:
                        os.unlink(lockfile)
                    except Exception:
                        pass

        raise RuntimeError("no display could be claimed (checked :90-:99 and :0 if allowed)")

    def _get_browser(self) -> Any:
        """Legacy opt-in path. Launch-or-return the private headful Xvfb stealth
        browser (patchright launch, NOT connect_over_cdp, because external
        spawns bypass patchright's stealth). ONLY reachable behind
        GREYSEARCH_ALLOW_PRIVATE_BROWSER=1; the default fetch path is
        browser_session.fetch_text on the session's ONE headless slot browser."""
        with PatchrightScraper._CLS_LOCK:
            if not _HAS_PATCHRIGHT:
                raise RuntimeError("patchright not installed (pip install patchright)")
            if PatchrightScraper._browser is not None:
                try:
                    if PatchrightScraper._browser.is_connected():
                        return PatchrightScraper._browser
                except Exception:
                    pass
                PatchrightScraper._browser = None
            if PatchrightScraper._pw is None:
                PatchrightScraper._pw = sync_playwright().start()
            disp = self._ensure_xvfb()
            if not PatchrightScraper._profile_dir:
                PatchrightScraper._profile_dir = f"/tmp/greysearch-profile-{os.getpid()}"
            env = dict(os.environ)
            env["DISPLAY"] = disp
            _exec = chrome_exe()
            ctx = PatchrightScraper._pw.chromium.launch_persistent_context(
                user_data_dir=PatchrightScraper._profile_dir,
                executable_path=_exec,
                headless=False,
                args=["--no-first-run", "--disable-gpu", "--lang=en-US",
                      "--window-size=1400,1000", "--disable-dev-shm-usage"],
                env=env,
            )
            PatchrightScraper._ctx = ctx
            PatchrightScraper._browser = ctx.browser
            return ctx

    def _get_page(self) -> Any:
        """Reuse this instance's page; recreate exactly one tab on demand."""
        with PatchrightScraper._CLS_LOCK:
            if self._page is not None:
                try:
                    if not self._page.is_closed():
                        return self._page
                except Exception:
                    pass
                self._page = None
            ctx = self._get_browser()
            page = ctx.new_page()
            try:
                page.set_default_timeout(20000)
                page.on("dialog", lambda d: d.dismiss())
                page.on("download", lambda d: d.cancel())
            except Exception:
                pass
            self._page = page
            return page

    def _reset_page(self) -> None:
        try:
            if self._page is not None and not self._page.is_closed():
                self._page.close()
        except Exception:
            pass
        self._page = None

    def fetch_url(self,
                  url: str,
                  selector: str = "body",
                  custom_headers: Optional[Dict[str, str]] = None,
                  mode: Any = None) -> Dict[str, Any]:
        """Fetch a URL on the session's ONE slot browser (patchright headless,
        CDP-shared via browser_session). One retry with a fresh CDP client on
        failure; mode rides along to browser_session.fetch_text only for its
        SEARCH-class hops (the scrape itself stays direct, no transport). The
        per-URL wayback consult lives inside fetch_text; on the way from here
        the rung's honest note is carried on this wrapper's failure record
        without mutating the original error text.
        GREYSEARCH_ALLOW_PRIVATE_BROWSER=1 opts into the legacy private-Xvfb
        browser instead (never the default path)."""
        del custom_headers
        if os.environ.get("GREYSEARCH_ALLOW_PRIVATE_BROWSER", "").strip().lower() \
                in ("1", "true", "yes"):
            return self._fetch_url_private(url, selector, mode=mode)
        start_time = time.time()
        last_error = ""
        wbnote = ""
        for attempt in (1, 2):
            if attempt == 2 and any(w in last_error for w in
                                    ("closed", "wedge", "timeout wall")):
                break
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                r = _bs.fetch_text(url, mode=mode)
                if r.get("ok"):
                    r.setdefault("scrape_transport",
                                 _proxy_mode.scrape_guard_note())
                    r.setdefault("attempt", attempt)
                    r["display_reclaims"] = list(
                        PatchrightScraper._display_reclaims)
                    PatchrightScraper._pages_fetched += 1
                    self._consecutive_failures = 0
                    return r
                last_error = str(r.get("error") or "empty result")[:300]
                wbnote = str(r.get("wayback") or "") or wbnote
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"[:300]
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                _bs.drop_connection()
            except Exception:
                pass
        fail: Dict[str, Any] = {
            "ok": False, "url": url, "error": last_error or "fetch failed",
            "elapsed_s": round(time.time() - start_time, 2)}
        if wbnote:
            fail["wayback"] = wbnote
        return fail

    def _fetch_url_private(self,
                           url: str,
                           selector: str = "body",
                           mode: Any = None) -> Dict[str, Any]:
        """Legacy opt-in: private-Xvfb stealth browser, kept only behind
        GREYSEARCH_ALLOW_PRIVATE_BROWSER=1. Same contract as the default
        fetch path."""
        start_time = time.time()
        last_error = ""

        for attempt in (1, 2):
            try:
                page = self._get_page()
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=self.timeout * 1000)
                try:
                    page.wait_for_load_state("load", timeout=8000)
                except Exception:
                    pass
                time.sleep(0.6)

                body_text = page.locator(selector).first.inner_text(timeout=10_000)
                if not (body_text or "").strip():
                    raise RuntimeError("empty body text (bot-wall, blank page, or JS-only)")
                title = page.title() or ""
                status = resp.status if resp is not None else 200
                final_url = page.url or url
                html_content = page.content() or ""
                html_capped = False
                if len(html_content) > _HTML_CAP:
                    html_content = html_content[:_HTML_CAP]
                    html_capped = True

                scroll_steps = 0
                try:
                    scroll_steps = eval_with_timeout(page, _SCROLL_JS)
                except Exception:
                    scroll_steps = 0

                media = self.extract_media(page)
                try:
                    metadata = eval_with_timeout(page, _META_JS) or {}
                except Exception:
                    metadata = {}
                metadata["extraction_method"] = "patchright_private_stealth"
                metadata["scroll_steps"] = scroll_steps

                cleaned, inj_flags = _rij.sanitize_text(body_text)
                self._consecutive_failures = 0
                PatchrightScraper._pages_fetched += 1
                return {
                    "ok": True,
                    "url": url,
                    "final_url": final_url,
                    "title": title,
                    "status_code": status,
                    "text": cleaned,
                    "raw_text": body_text,
                    "html": html_content,
                    "html_capped": html_capped,
                    "metadata": metadata,
                    "links": media.get("links", []),
                    "images": media.get("images", []),
                    "videos": media.get("videos", []),
                    "tables": media.get("tables", []),
                    "headings": media.get("headings", []),
                    "code_blocks": media.get("code_blocks", []),
                    "audios": media.get("audios", []),
                    "pdfs": media.get("pdfs", []),
                    "canvases": media.get("canvases", []),
                    "iframes": media.get("iframes", []),
                    "injection_flags": inj_flags,
                    "injection_scanned": True,
                    "scrape_transport": _proxy_mode.scrape_guard_note(),
                    "display_reclaims": list(
                        PatchrightScraper._display_reclaims),
                    "attempt": attempt,
                    "elapsed_s": round(time.time() - start_time, 2),
                }
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"[:300]
                self._consecutive_failures += 1
                self._reset_page()
                if self._consecutive_failures >= 2 and attempt == 1:
                    with PatchrightScraper._CLS_LOCK:
                        try:
                            if PatchrightScraper._browser is not None:
                                PatchrightScraper._browser.close()
                        except Exception:
                            pass
                        PatchrightScraper._browser = None

        fail: Dict[str, Any] = {
            "ok": False, "url": url, "error": last_error or "fetch failed",
            "elapsed_s": round(time.time() - start_time, 2)}
        try:
            resc, wbnote = wayback_rescue(url, dead_error=last_error)
        except Exception as e:
            resc, wbnote = None, f"unavailable ({type(e).__name__}: {str(e)[:80]})"
        if resc is not None:
            return resc
        if wbnote:
            fail["wayback"] = wbnote
        return fail

    def extract_media(self, page: Any) -> Dict[str, Any]:
        """Exhaustive media + structure extraction FROM THE PAGE OBJECT that
        fetched the URL. Never probes another browser; tables never collapsed."""
        links: List[Dict[str, str]] = []
        images: List[Dict[str, str]] = []
        videos: List[Dict[str, str]] = []
        tables: List[Any] = []
        headings: List[Dict[str, str]] = []
        code_blocks: List[str] = []
        audios: List[Dict[str, str]] = []
        pdfs: List[Dict[str, str]] = []
        canvases: List[Dict[str, int]] = []
        iframes: List[Dict[str, str]] = []

        jobs = [
            ("links", _LINKS_JS), ("images", _IMAGES_JS),
            ("videos", _VIDEO_TAG_JS), ("videos", _IFRAME_VIDEO_JS),
            ("tables", _TABLES_JS), ("headings", _HEADINGS_JS),
            ("code", _CODE_JS),
            ("audios", _AUDIO_JS),
            ("pdfs", _PDF_JS),
            ("canvases", _CANVAS_JS),
            ("iframes", _IFRAME_JS),
        ]
        for label, js in jobs:
            try:
                raw = eval_with_timeout(page, js)
            except Exception:
                continue
            if not isinstance(raw, list):
                continue
            if label == "links":
                for r in raw:
                    if isinstance(r, dict) and r.get("href", "").startswith("http"):
                        links.append({"href": r["href"], "text": r.get("text", "")})
            elif label == "images":
                for r in raw:
                    if isinstance(r, dict) and r.get("src", "").startswith("http"):
                        w = r.get("w", 0) or 0
                        h = r.get("h", 0) or 0
                        if w and h and w < 32 and h < 32:
                            continue
                        images.append({"src": r["src"], "alt": r.get("alt", ""),
                                       "w": w, "h": h})
            elif label == "videos":
                for r in raw:
                    if isinstance(r, dict) and r.get("src") and r not in videos:
                        videos.append({"src": r["src"], "title": r.get("title", "")})
            elif label == "tables":
                for t in raw:
                    if isinstance(t, dict) and t.get("rows"):
                        tables.append(t)
            elif label == "headings":
                for r in raw:
                    if isinstance(r, dict) and r.get("text"):
                        headings.append({"level": r.get("level", ""),
                                         "text": r.get("text", "")})
            elif label == "code":
                for s in raw:
                    if isinstance(s, str) and s.strip():
                        code_blocks.append(s)
            elif label == "audios":
                for r in raw:
                    if isinstance(r, dict) and r.get("src"):
                        audios.append({"src": r["src"], "title": r.get("title", "")})
            elif label == "pdfs":
                for r in raw:
                    if isinstance(r, dict) and r.get("src"):
                        pdfs.append({"src": r["src"], "title": r.get("title", "")})
            elif label == "canvases":
                for r in raw:
                    if isinstance(r, dict):
                        canvases.append({"width": r.get("width", 0),
                                         "height": r.get("height", 0)})
            elif label == "iframes":
                for r in raw:
                    if isinstance(r, dict) and r.get("src"):
                        iframes.append({"src": r["src"], "title": r.get("title", "")})
        return {"links": links, "images": images, "videos": videos, "tables": tables,
                "headings": headings, "code_blocks": code_blocks,
                "audios": audios, "pdfs": pdfs, "canvases": canvases,
                "iframes": iframes}

    def extract_links(self, url: str,
                      selector: str = "a",
                      attribute: str = "href") -> List[Dict[str, str]]:
        """Fetch the URL and return its links (was a stub that returned
        'Link extraction requires page context')."""
        del selector, attribute
        result = self.fetch_url(url)
        if not result.get("ok"):
            return [{"url": url, "error": result.get("error", "fetch failed")}]
        return result.get("links", [])

    def _clean_text(self, text: str) -> str:
        """Paragraph-preserving normalization (the old code collapsed every
        page into a single line, destroying all structure)."""
        if not text:
            return ""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        for pat in _BOILER_LINES:
            text = re.sub(pat, "", text)
        for pat in _BOILER_INLINE:
            text = re.sub(pat, "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_metadata(self, fetch_result: Dict[str, Any]) -> Dict[str, Any]:
        """Metadata from a fetch result (API-compat; real extraction happens
        in fetch_url via the page object)."""
        metadata = {}
        if "title" in fetch_result:
            metadata["title"] = fetch_result["title"]
        metadata["extraction_method"] = "patchright_private_stealth"
        return metadata

    def health_check(self) -> Dict[str, Any]:
        """Health WITHOUT spawning anything (reporting is cheap, launching is not)."""
        running = False
        display = ""
        with PatchrightScraper._CLS_LOCK:
            display = PatchrightScraper._display
            if PatchrightScraper._ctx is not None:
                try:
                    brow = PatchrightScraper._ctx.browser
                    running = bool(brow.is_connected()) if brow else False
                except Exception:
                    running = False
        slot_alive = False
        lane = "cdp-slot-browser (patchright headless via connect_over_cdp)"
        if os.environ.get("GREYSEARCH_ALLOW_PRIVATE_BROWSER", "").strip().lower() \
                in ("1", "true", "yes"):
            lane = "private stealth browser (opt-in)"
            slot_alive = running
        else:
            try:
                try:
                    from . import browser_session as _bs
                except ImportError:
                    import browser_session as _bs
                slot_alive = _bs.cdp_alive()
            except Exception:
                slot_alive = False
        return {
            "scraper_stealth_level": self.stealth_level,
            "scraper_timeout": self.timeout,
            "lane": lane,
            "slot_browser_alive": slot_alive,
            "private_browser_running": running,
            "private_display": display or "not-started",
            "pages_fetched_this_process": PatchrightScraper._pages_fetched,
            "display_reclaims": list(PatchrightScraper._display_reclaims),
            "patchright_installed": _HAS_PATCHRIGHT,
        }

    def health(self) -> Dict[str, Any]:
        return self.health_check()

def scrape_url(url: str,
               selector: str = "body",
               timeout: int = 25) -> Dict[str, Any]:
    """Convenience: scrape one URL with default private-stealth settings."""
    scraper = PatchrightScraper(timeout=timeout)
    return scraper.fetch_url(url, selector=selector)

def quick_scrape(url: str) -> Optional[str]:
    """Quick scrape returning just cleaned text, or None on failure."""
    result = scrape_url(url)
    if result.get("ok"):
        return result.get("text")
    return None

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = scrape_url(sys.argv[1])
        slim = {k: v for k, v in result.items() if k not in ("raw_text", "html")}
        if "text" in slim and isinstance(slim["text"], str):
            slim["text"] = slim["text"][:2000]
        print(json.dumps(slim, indent=2)[:4000])
    else:
        print("Usage: python patchright_scraper.py <url>")