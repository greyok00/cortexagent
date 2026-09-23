#!/usr/bin/env python3

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

try:
    import stealth
    import injection_guard
    import browser_cdp_guard
except ImportError:
    from lib import stealth
    from lib import injection_guard
    from lib import browser_cdp_guard

try:
    import humanizer as _humanizer_mod
except Exception:
    _humanizer_mod = None

try:
    from patchright.sync_api import sync_playwright
    _HAS_PATCHRIGHT = True
except Exception:
    sync_playwright = None
    _HAS_PATCHRIGHT = False

try:
    import websocket as _ws_client
    _HAS_WS_CLIENT = True
except Exception:
    _ws_client = None
    _HAS_WS_CLIENT = False

CDP_HTTP = "http://127.0.0.1:9224"
CDP_URL = CDP_HTTP

_profile: Optional[Dict[str, Any]] = None
_stealth_script: Optional[str] = None
_stealth_applied: set = set()
_guard: Any = None

_playwright = None
_browser = None
_ctx = None
_playwright_lock = threading.Lock()
_patchright_wedged = False

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

def _get_browser():
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

def _raw_targets() -> List[Dict[str, Any]]:
    with urllib.request.urlopen(CDP_HTTP + "/json", timeout=5) as r:
        return json.load(r)

def _raw_ws_url(target_id: str) -> str:
    for t in _raw_targets():
        if t.get("id") == target_id and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError(f"no raw CDP ws url for target {target_id}")

def _raw_eval(target_id: str, expression: str, timeout: float = 10.0) -> Any:
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
    val = _raw_eval(
        target_id,
        "document.body ? document.body.innerText : ''",
        timeout=timeout,
    )
    return val or ""

def _get_ctx():
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
    try:
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

def health() -> Dict[str, Any]:
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

def _real_ua() -> str:
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
            from stealth.profiles import derive_profile
        except ImportError:
            from lib.stealth.profiles import derive_profile
        seed = int(os.environ.get("STEALTH_SEED", "0"))
        _profile = derive_profile(seed=seed, real_ua=_real_ua())
    if _stealth_script is None:
        try:
            from stealth.init_script import build_init_script
        except ImportError:
            from lib.stealth.init_script import build_init_script
        _stealth_script = build_init_script(_profile)

def _ensure_stealth(target_id: str) -> None:
    _ensure_profile()
    if target_id not in _stealth_applied:
        _stealth_applied.add(target_id)

def _isolated_eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:
    try:
        page = _resolve_page(target_id)
        return {"ok": True, "value": page.evaluate(expression, timeout=timeout * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}

def start_guard(kill: bool = False) -> Any:
    global _guard
    if _guard is None:
        _guard = browser_cdp_guard.CDPGuard(port=9224, on_alert=None)
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
    _ensure_profile()
    return {
        "profile": _profile,
        "applied_targets": sorted(_stealth_applied),
        "cdp_reachable": health().get("cdp_reachable", False),
    }

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
            "webSocketDebuggerUrl": None,
        })
    _tabs_cache = tabs
    _tabs_cache_at = now
    return list(tabs)

def resolve_tab(tab: Any = None) -> str:
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

def navigate(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded") -> Dict[str, Any]:
    page = _resolve_page(tab)
    page.goto(url, wait_until=wait_until)
    _invalidate_tabs_cache()
    return {"url": page.url, "title": page.title(), "ok": True}

def navigate_raw(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded") -> Any:
    return navigate(tab=tab, url=url, wait_until=wait_until)

def fetch(tab: Any = None, url: str = "", selector: str = "body") -> Dict[str, Any]:
    page = _resolve_page(tab)
    if url:
        page.goto(url, wait_until="domcontentloaded")
    text = page.locator(selector).first.inner_text(timeout=10_000)
    return {"url": page.url, "title": page.title(), "text": text, "ok": True}

def _click_js(selector: str, by_text: bool) -> str:
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

def _smoke() -> int:
    print("== browser_control smoke (Patchright) ==")
    print(json.dumps(health(), indent=2))
    print("tabs:", len(list_tabs()))
    return 0

def main() -> None:
    sys.exit(_smoke())

if __name__ == "__main__":
    main()
