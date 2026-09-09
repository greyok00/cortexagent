#!/usr/bin/env python3
"""Sync facade over Patchright + Google Chrome (CDP on :9224).

Browser-agnostic at the API level — talks to whatever speaks HTTP+WS on :9224.
Public API surface (23 functions) preserved from the websocket era so the
9 direct importers don't need to change:
  * lib/browser_tools.py
  * lib/playwright_brave_mcp.py
  * scripts/coursera_*.py
  * scripts/find_captcha_host.py
  * tests/test_browser_control.py
  * tests/test_stealth_browser.py
  * bin/cortexagent-browser-health

Transport notes:
- Each public fn is sync. Patchright's sync_playwright already runs the
  asyncio loop internally — no asyncio.run() needed at this layer.
- Patchright's BrowserContext serializes per-page ops — no per-target locks.
- Isolated world: page.add_init_script(script). (Patchright injects into
  the main world by default; for the per-page stealth init the
  lib.stealth.worker already uses add_init_script on tab creation.)
- Raw CDP escape hatch: page.context.new_cdp_session(page) — used by
  callers that need Page.createIsolatedWorld or Input.dispatchMouseEvent.
- Dead-socket detection: page.is_closed() / page.context.browser.is_connected().
- Tabs TTL cache: same as before, polled via browser.contexts[*].pages.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

# Sibling modules live in lib/ — importable as top-level when lib/ is on
# sys.path (production) or as lib.X when imported as lib.browser_control
# (tests). Fall back so both styles work.
try:
    import stealth  # noqa: F401  (re-exports seed/profile/init_script)
    import injection_guard  # noqa: F401
    import browser_cdp_guard  # noqa: F401
except ImportError:
    from lib import stealth  # noqa: F401
    from lib import injection_guard  # noqa: F401
    from lib import browser_cdp_guard  # noqa: F401

try:
    import humanizer as _humanizer_mod  # noqa: F401
except Exception:
    _humanizer_mod = None

try:
    from patchright.sync_api import sync_playwright  # type: ignore
    _HAS_PATCHRIGHT = True
except Exception:
    sync_playwright = None  # type: ignore
    _HAS_PATCHRIGHT = False

try:
    import websocket as _ws_client  # websocket-client
    _HAS_WS_CLIENT = True
except Exception:
    _ws_client = None  # type: ignore
    _HAS_WS_CLIENT = False


CDP_HTTP = "http://127.0.0.1:9224"
CDP_URL = CDP_HTTP


_PROFILE_NAME = os.environ.get("STEALTH_PROFILE", "default")
_profile: Optional[Dict[str, Any]] = None
_stealth_script: Optional[str] = None
_stealth_applied: set = set()
_guard: Any = None


_playwright = None
_browser = None
_ctx = None
_playwright_lock = threading.Lock()
_patchright_wedged = False  # set once connect_over_cdp fails; skip retries


_TABS_TTL_SEC = 0.15
_tabs_cache: List[Dict[str, Any]] = []
_tabs_cache_at: float = 0.0


_metrics_lock = threading.Lock()
_metrics: Dict[str, Any] = {
    "calls": 0,
    "reconnects": 0,
    "json_fetches": 0,
    "retries": 0,
    "failures": 0,
    "last_call_ms": 0.0,
    "started_at": time.time(),
}

_atexit_registered = False


def _atexit_close() -> None:
    try:
        close()
    except Exception:
        pass


if not _atexit_registered:
    atexit.register(_atexit_close)
    _atexit_registered = True


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def _get_browser():
    """Connect (or reconnect) to the Chrome CDP instance on :9224.

    Chrome 150 rejects Patchright's connect_over_cdp session setup
    (Network.setCacheDisabled: session closed) when the browser already has
    many CDP sessions — the call hangs forever and wedges the module lock.
    Fail fast with a short timeout so callers can fall back to raw CDP.
    """
    global _playwright, _browser, _patchright_wedged
    if not _HAS_PATCHRIGHT:
        raise RuntimeError(
            "patchright not installed. Run: pip install --break-system-packages patchright"
        )
    if _patchright_wedged:
        raise RuntimeError("patchright wedged on this browser; use raw CDP")
    with _playwright_lock:
        if _browser is not None:
            try:
                if _browser.is_connected():
                    return _browser
            except Exception:
                pass
            _browser = None
        if _playwright is None:
            _playwright = sync_playwright().start()
        with _metrics_lock:
            _metrics["reconnects"] += 1
        try:
            _browser = _playwright.chromium.connect_over_cdp(CDP_URL, timeout=6000)
        except Exception:
            _patchright_wedged = True
            _browser = None
            raise
    return _browser


# ---------------------------------------------------------------------------
# Raw CDP fallback (Chrome 150 + many sessions)
# ---------------------------------------------------------------------------
# Patchright's connect_over_cdp wedges on this browser (see _get_browser).
# Raw websocket-client CDP with suppress_origin=True connects reliably, so the
# poll-loop functions (list_tabs / evaluate / read_text / page_text) fall back
# to it when the Patchright path fails or hangs.


def _raw_targets() -> List[Dict[str, Any]]:
    """List CDP targets via the HTTP /json endpoint (never wedges)."""
    with urllib.request.urlopen(CDP_HTTP + "/json", timeout=5) as r:
        return json.load(r)


def _raw_ws_url(target_id: str) -> str:
    for t in _raw_targets():
        if t.get("id") == target_id and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError(f"no raw CDP ws url for target {target_id}")


def _raw_eval(target_id: str, expression: str, timeout: float = 10.0) -> Any:
    """Evaluate JS on a target over raw CDP. Returns the by-value result."""
    if not _HAS_WS_CLIENT:
        raise RuntimeError("websocket-client not installed")
    ws = _ws_client.create_connection(
        _raw_ws_url(target_id), timeout=timeout, suppress_origin=True
    )
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                return msg["result"]["result"].get("value")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _raw_text(target_id: str, timeout: float = 10.0) -> str:
    """Read a target's body text over raw CDP."""
    val = _raw_eval(
        target_id,
        "document.body ? document.body.innerText : ''",
        timeout=timeout,
    )
    return val or ""


def _get_ctx():
    """Get the first persistent context (or create one)."""
    global _ctx
    b = _get_browser()
    ctxs = b.contexts
    if ctxs:
        if _ctx is None or _ctx not in ctxs:
            _ctx = ctxs[0]
        return _ctx
    _ctx = b.new_context()
    return _ctx


def _page_id(page) -> str:
    """Patchright pages don't expose a targetId directly — synthesize one
    from the page object id so callers can keep using string identifiers."""
    try:
        # Page objects are not hashable, so use the underlying CDP target id
        # if exposed, else the URL hash as a stable id.
        cdp = page.context.new_cdp_session(page) if hasattr(page.context, "new_cdp_session") else None
        if cdp:
            try:
                info = cdp.send("Target.getTargetInfo")
                return str(info.get("targetInfo", {}).get("targetId", id(page)))
            except Exception:
                pass
    except Exception:
        pass
    return f"page-{id(page)}"


def _invalidate_tabs_cache() -> None:
    global _tabs_cache, _tabs_cache_at
    _tabs_cache = []
    _tabs_cache_at = 0.0


def _resolve_page(tab=None):
    """tab: None → first page; int → index; str URL prefix or page-id."""
    pages = _get_ctx().pages
    if not pages:
        raise RuntimeError("no pages open in browser context")
    if tab is None:
        return pages[0]
    if isinstance(tab, int):
        return pages[tab % len(pages)]
    if isinstance(tab, str):
        for p in pages:
            if tab in p.url or tab == _page_id(p):
                return p
        return pages[0]
    return pages[0]


# ---------------------------------------------------------------------------
# Metrics / health
# ---------------------------------------------------------------------------


def health() -> Dict[str, Any]:
    """Sync health snapshot. Mirrors the old websocket-era shape so
    downstream consumers (tests/run_smoke.py, bin/cortexagent-browser-health)
    don't have to learn new keys."""
    with _metrics_lock:
        _metrics["calls"] += 1
    out: Dict[str, Any] = {
        "calls": _metrics["calls"],
        "reconnects": _metrics["reconnects"],
        "json_fetches": _metrics["json_fetches"],
        "retries": _metrics["retries"],
        "failures": _metrics["failures"],
        "last_call_ms": _metrics["last_call_ms"],
        "uptime_sec": time.time() - _metrics["started_at"],
        "cdp_reachable": False,
        "browser": "unknown",
        "cached_sockets": 0,
        "cached_tab_list_age_ms": int((time.time() - _tabs_cache_at) * 1000) if _tabs_cache_at else 0,
    }
    try:
        b = _get_browser()
        out["cdp_reachable"] = bool(b.is_connected())
        out["browser"] = f"Chrome (Patchright) {len(b.contexts)} ctx"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def close() -> None:
    """Idempotent teardown of the Patchright connection."""
    global _playwright, _browser, _ctx
    with _playwright_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright is not None:
            try:
                _playwright.stop()
            except Exception:
                pass
            _playwright = None
        _ctx = None
        _invalidate_tabs_cache()


# ---------------------------------------------------------------------------
# Guard (stealth / injection)
# ---------------------------------------------------------------------------


def _real_ua() -> str:
    """Best-effort UA for stealth profile generation. Reads from the
    currently-open Chrome via CDP if available, else falls back to env."""
    try:
        page = _get_ctx().pages[0]
        return page.evaluate("() => navigator.userAgent") or ""
    except Exception:
        return os.environ.get("STEALTH_UA", "Mozilla/5.0 (X11; Linux x86_64) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/150.0.0.0 Safari/537.36")


def _ensure_profile() -> None:
    global _profile, _stealth_script
    if _profile is None:
        try:
            from stealth.profiles import derive_profile  # noqa: WPS433
        except ImportError:
            from lib.stealth.profiles import derive_profile  # noqa: WPS433
        seed = int(os.environ.get("STEALTH_SEED", "0"))
        _profile = derive_profile(seed=seed, real_ua=_real_ua())
    if _stealth_script is None:
        try:
            from stealth.init_script import build_init_script  # noqa: WPS433
        except ImportError:
            from lib.stealth.init_script import build_init_script  # noqa: WPS433
        _stealth_script = build_init_script(_profile)


def _ensure_stealth(target_id: str) -> None:
    """Mark a target as having received the stealth init script.
    Actual injection happens in start_chrome() / lib.stealth.worker — this
    function is kept for back-compat with callers that probe per-target."""
    _ensure_profile()
    if target_id not in _stealth_applied:
        _stealth_applied.add(target_id)


def _create_isolated_world(target_id: str) -> None:
    """No-op under Patchright — Patchright's add_init_script() injects into
    the page's main world by default; for isolated execution, callers should
    open a cdp_session and call Page.addScriptToEvaluateOnNewDocument with
    worldName='ISOLATED'. Kept for back-compat."""
    return None


def _isolated_eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:
    """Back-compat shim: evaluate via the page's main world. Returns a
    structured dict like the old API did."""
    try:
        page = _resolve_page(target_id)
        return {"ok": True, "value": page.evaluate(expression, timeout=timeout * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def start_guard(kill: bool = False) -> Any:
    global _guard
    if _guard is None:
        _guard = browser_cdp_guard.CDPGuard(port=9223, on_alert=None)
    _guard.start()
    return _guard


def stop_guard() -> None:
    global _guard
    if _guard is not None:
        try:
            _guard.stop()
        except Exception:
            pass
        _guard = None


def stealth_status() -> Dict[str, Any]:
    """Return stealth profile + injection status. Shape preserved from
    the old API."""
    _ensure_profile()
    return {
        "profile": _profile,
        "applied_targets": sorted(_stealth_applied),
        "cdp_reachable": health().get("cdp_reachable", False),
    }


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


def list_tabs() -> List[Dict[str, Any]]:
    global _tabs_cache, _tabs_cache_at
    now = time.time()
    if _tabs_cache and (now - _tabs_cache_at) < _TABS_TTL_SEC:
        return list(_tabs_cache)
    try:
        pages = _get_ctx().pages
    except Exception:
        pages = None
    if pages is None:
        # Patchright wedged — fall back to raw CDP target list.
        try:
            tabs = [{
                "id": t["id"],
                "url": t.get("url", ""),
                "title": t.get("title", ""),
                "type": t.get("type", "page"),
                "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl"),
            } for t in _raw_targets() if t.get("type") == "page"]
            _tabs_cache = tabs
            _tabs_cache_at = now
            return list(tabs)
        except Exception:
            return []
    tabs: List[Dict[str, Any]] = []
    for p in pages:
        try:
            url = p.url
        except Exception:
            url = ""
        try:
            title = p.title()
        except Exception:
            title = ""
        pid = _page_id(p)
        tabs.append({
            "id": pid,
            "url": url,
            "title": title,
            "type": "page",
            "webSocketDebuggerUrl": None,  # Patchright handles WS internally
        })
    _tabs_cache = tabs
    _tabs_cache_at = now
    return list(tabs)


def find_tab(url_prefix: str) -> Optional[str]:
    for t in list_tabs():
        if url_prefix.lower() in t["url"].lower():
            return t["id"]
    return None


def resolve_tab(tab: Any = None) -> str:
    """Returns the page-id of the resolved tab. Mirrors the old API."""
    page = _resolve_page(tab)
    return _page_id(page)


def new_tab(url: str = "") -> str:
    page = _get_ctx().new_page()
    _ensure_stealth(_page_id(page))
    if url:
        page.goto(url, wait_until="domcontentloaded")
    _invalidate_tabs_cache()
    return _page_id(page)


def close_tab(target_id: str) -> bool:
    try:
        page = _resolve_page(target_id)
        page.close()
        _invalidate_tabs_cache()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Navigation / fetch
# ---------------------------------------------------------------------------


def navigate(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded") -> Dict[str, Any]:
    page = _resolve_page(tab)
    page.goto(url, wait_until=wait_until)
    _invalidate_tabs_cache()
    return {"url": page.url, "title": page.title(), "ok": True}


def navigate_raw(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded") -> Any:
    """Navigate without invalidating the tab cache (kept for back-compat
    with the old websocket-era callers that used this for raw control)."""
    return navigate(tab=tab, url=url, wait_until=wait_until)


def fetch(tab: Any = None, url: str = "", selector: str = "body") -> Dict[str, Any]:
    page = _resolve_page(tab)
    if url:
        page.goto(url, wait_until="domcontentloaded")
    text = page.locator(selector).first.inner_text(timeout=10_000)
    return {"url": page.url, "title": page.title(), "text": text, "ok": True}


# ---------------------------------------------------------------------------
# Interaction (click / type / fill)
# ---------------------------------------------------------------------------


def _click_js(selector: str, by_text: bool) -> str:
    """Back-compat JS snippet. Kept so callers that import it still get
    something useful, but the actual click() below uses Patchright."""
    if by_text:
        sel = json.dumps(selector)
        return (
            f"(function(){{var els=Array.from(document.querySelectorAll('a,button,*'))"
            f".filter(e=>(e.innerText||'').trim()=== {sel});"
            "if(els.length){els[0].click();return 'clicked: '+els.length;}return 'no match';}})()"
        )
    sel = json.dumps(selector)
    return (
        f"(function(){{var el=document.querySelector({sel});"
        "if(el){el.click();return 'clicked';}return 'no match';}})()"
    )


def click(tab: Any = None, selector: str = "", by_text: bool = False,
          timeout: int = 15) -> str:
    page = _resolve_page(tab)
    loc = page.get_by_text(selector).first if by_text else page.locator(selector).first
    loc.click(timeout=timeout * 1000)
    return "clicked"


def _type_js(selector: str, text: str, by_text: bool, submit: bool) -> str:
    sel = json.dumps(selector)
    val = json.dumps(text)
    if by_text:
        return (
            f"(function(){{var els=Array.from(document.querySelectorAll('input,textarea'))"
            f".filter(e=>(e.placeholder||'').includes({sel}));"
            f"if(els.length){{els[0].focus();els[0].value={val};els[0].dispatchEvent(new Event('input',{{bubbles:true}}));"
            f"if({json.dumps(submit)})els[0].form&&els[0].form.submit();return 'typed';}}return 'no match';}})()"
        )
    return (
        f"(function(){{var el=document.querySelector({sel});"
        f"if(el){{el.focus();el.value={val};el.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"if({json.dumps(submit)})el.form&&el.form.submit();return 'typed';}}return 'no match';}})()"
    )


def type_text(tab: Any = None, selector: str = "", text: str = "",
             by_text: bool = False, submit: bool = False, timeout: int = 15) -> str:
    page = _resolve_page(tab)
    loc = page.get_by_text(selector).first if by_text else page.locator(selector).first
    loc.fill(text, timeout=timeout * 1000)
    if submit:
        loc.press("Enter")
    return "typed"


def evaluate(tab: Any = None, expression: str = "", timeout: int = 10) -> Any:
    try:
        page = _resolve_page(tab)
        return page.evaluate(expression)
    except Exception:
        # Patchright wedged — fall back to raw CDP. Resolve the tab id.
        tid = tab if isinstance(tab, str) else None
        if tid is None:
            for t in list_tabs():
                if t["type"] == "page":
                    tid = t["id"]
                    break
        if tid is None:
            raise
        return _raw_eval(tid, expression, timeout=timeout)


def snapshot(tab: Any = None, depth: int = 10) -> Any:
    page = _resolve_page(tab)
    try:
        # Patchright's accessibility tree (preferred — structured)
        if hasattr(page, "accessibility"):
            return page.accessibility.snapshot()
    except Exception:
        pass
    return page.content()


def read_text(tab: Any = None, selector: str = "body") -> str:
    try:
        page = _resolve_page(tab)
        return page.locator(selector).first.inner_text(timeout=10_000)
    except Exception:
        tid = tab if isinstance(tab, str) else None
        if tid is None:
            for t in list_tabs():
                if t["type"] == "page":
                    tid = t["id"]
                    break
        if tid is None:
            raise
        return _raw_text(tid)


def _find_js(iframe_marker: str) -> str:
    """Back-compat: kept so callers that import it don't break."""
    return (
        f"Array.from(document.querySelectorAll('iframe'))"
        f".filter(f => (f.src||'').includes({json.dumps(iframe_marker)}))[0] || null"
    )


def fill_and_send(tab: Any = None, text: str = "", *, iframe_marker: str = "",
                  submit: bool = True, selector: str = "body") -> str:
    page = _resolve_page(tab)
    if iframe_marker:
        frames = page.frames
        target = next((f for f in frames if iframe_marker in (f.url or "")), page.main_frame)
        target.locator(selector).first.fill(text)
        if submit:
            target.locator(selector).first.press("Enter")
    else:
        page.locator(selector).first.fill(text)
        if submit:
            page.keyboard.press("Enter")
    return "filled_and_sent"


def element_value(tab: Any = None, *, iframe_marker: str = "",
                  selector: str = "body") -> str:
    page = _resolve_page(tab)
    if iframe_marker:
        frames = page.frames
        target = next((f for f in frames if iframe_marker in (f.url or "")), page.main_frame)
        return target.locator(selector).first.input_value()
    return page.locator(selector).first.input_value()


def clear_element(tab: Any = None, *, iframe_marker: str = "",
                  selector: str = "body") -> str:
    page = _resolve_page(tab)
    if iframe_marker:
        frames = page.frames
        target = next((f for f in frames if iframe_marker in (f.url or "")), page.main_frame)
        target.locator(selector).first.clear()
    else:
        page.locator(selector).first.clear()
    return "cleared"


def page_text(tab: Any = None, iframe_marker: str = "") -> str:
    try:
        page = _resolve_page(tab)
        if iframe_marker:
            frames = page.frames
            target = next((f for f in frames if iframe_marker in (f.url or "")), page.main_frame)
            return target.locator("body").first.inner_text()
        return page.locator("body").first.inner_text()
    except Exception:
        tid = tab if isinstance(tab, str) else None
        if tid is None:
            for t in list_tabs():
                if t["type"] == "page":
                    tid = t["id"]
                    break
        if tid is None:
            raise
        return _raw_text(tid)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _smoke() -> int:
    print("== browser_control smoke (Patchright) ==")
    print(json.dumps(health(), indent=2))
    print("tabs:", len(list_tabs()))
    return 0


def main() -> None:
    sys.exit(_smoke())


if __name__ == "__main__":
    main()