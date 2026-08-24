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

import websocket





import stealth
import injection_guard
import browser_cdp_guard
try:
    import humanizer as _humanizer_mod
except Exception:
    _humanizer_mod = None

CDP_HTTP = "http://127.0.0.1:9222"
CDP_URL = CDP_HTTP


_PROFILE_NAME = os.environ.get("STEALTH_PROFILE", "default")
_profile: Optional[Dict[str, Any]] = None
_stealth_script: Optional[str] = None
_isolated_ctx: Dict[str, int] = {}
_stealth_applied: set = set()
_guard: Any = None



_lock = threading.RLock()
_target_locks: Dict[str, threading.RLock] = {}
_target_locks_guard = threading.Lock()
_ws_cache: Dict[str, Any] = {}
_id_counter: Dict[str, int] = {}




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


def _http_json(path: str) -> Any:
    with _metrics_lock:
        _metrics["json_fetches"] += 1
    return json.load(urllib.request.urlopen(CDP_HTTP + path, timeout=5))


def _lock_for(target_id: str) -> threading.RLock:

    with _target_locks_guard:
        lk = _target_locks.get(target_id)
        if lk is None:
            lk = threading.RLock()
            _target_locks[target_id] = lk
        return lk


def _next_id(target_id: str) -> int:
    _id_counter[target_id] = _id_counter.get(target_id, 0) + 1
    return _id_counter[target_id]


def _get_ws(target_id: str) -> Any:

    ws = _ws_cache.get(target_id)
    if ws is not None:

        try:
            tabs = _http_json("/json")
        except Exception:

            try: ws.close()
            except Exception: pass
            _ws_cache.pop(target_id, None)
            ws = None
            _invalidate_tabs_cache()
        else:
            still_alive = any(t.get("id") == target_id for t in tabs)
            if not still_alive:
                try: ws.close()
                except Exception: pass
                _ws_cache.pop(target_id, None)
                ws = None
                _invalidate_tabs_cache()
    if ws is not None:
        return ws
    tabs = _http_json("/json")
    ws_url = next((t.get("webSocketDebuggerUrl") for t in tabs if t.get("id") == target_id), None)
    if not ws_url:
        raise RuntimeError(f"tab {target_id} not found")
    ws = websocket.create_connection(ws_url, timeout=2, suppress_origin=True)
    ws.settimeout(2.0)
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Page.enable"}))
    _ws_cache[target_id] = ws


    try:
        _ensure_stealth(target_id)
    except Exception:
        pass



    if os.environ.get("STEALTH_CDP_GUARD", "1") not in ("0", "false", "False"):
        try:
            start_guard()
        except Exception:
            pass
    _invalidate_tabs_cache()
    with _metrics_lock:
        _metrics["reconnects"] += 1
    return ws


def _eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:

    t0 = time.time()
    with _metrics_lock:
        _metrics["calls"] += 1
    last = None
    for attempt in (1, 2):
        with _lock_for(target_id):
            try:
                ws = _get_ws(target_id)
            except RuntimeError:
                last = None
                break
            try:
                ws.settimeout(max(0.5, timeout))
                msg_id = _next_id(target_id)
                ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
                                    "params": {"expression": expression, "returnByValue": True}}))
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        msg = json.loads(ws.recv())
                    except (websocket.WebSocketTimeoutException, TimeoutError, OSError, ValueError):
                        break
                    except Exception:
                        break
                    if msg.get("id") == msg_id:
                        r = msg.get("result", {})
                        if "exceptionDetails" in r:
                            last = None
                            break
                        last = r.get("result", {}).get("value")
                        break
            except Exception:
                pass
            _ws_cache.pop(target_id, None)
            if attempt == 1:
                with _metrics_lock:
                    _metrics["retries"] += 1
                continue
            break

    dt_ms = (time.time() - t0) * 1000.0
    with _metrics_lock:
        _metrics["last_call_ms"] = dt_ms
        if last is None:
            _metrics["failures"] += 1
    return last


def _cmd(target_id: str, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Any:

    t0 = time.time()
    with _metrics_lock:
        _metrics["calls"] += 1
    last = None
    for attempt in (1, 2):
        with _lock_for(target_id):
            try:
                ws = _get_ws(target_id)
            except RuntimeError:
                last = None
                break
            try:
                ws.settimeout(max(0.5, timeout))
                msg_id = _next_id(target_id)
                ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        msg = json.loads(ws.recv())
                    except (websocket.WebSocketTimeoutException, TimeoutError, OSError, ValueError):
                        break
                    except Exception:
                        break
                    if msg.get("id") == msg_id:
                        last = msg.get("result", {})
                        break
            except Exception:
                pass
            _ws_cache.pop(target_id, None)
            if attempt == 1:
                with _metrics_lock:
                    _metrics["retries"] += 1
                continue
            break
    dt_ms = (time.time() - t0) * 1000.0
    with _metrics_lock:
        _metrics["last_call_ms"] = dt_ms
        if last is None:
            _metrics["failures"] += 1
    return last


def health() -> Dict[str, Any]:

    snap: Dict[str, Any] = {}
    with _metrics_lock:
        snap.update(_metrics)
    snap["uptime_sec"] = time.time() - snap.get("started_at", time.time())
    snap.pop("started_at", None)
    snap["cached_sockets"] = len(_ws_cache)
    snap["cached_tab_list_age_ms"] = int((time.time() - _tabs_cache_at) * 1000) if _tabs_cache else -1

    try:
        with urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=2) as r:
            info = json.load(r)
        snap["cdp_reachable"] = True
        snap["browser"] = info.get("Browser", "")
    except Exception as e:
        snap["cdp_reachable"] = False
        snap["cdp_error"] = str(e)[:200]
    return snap


def close() -> None:

    with _lock:
        for ws in _ws_cache.values():
            try:
                ws.close()
            except Exception:
                pass
        _ws_cache.clear()
        _id_counter.clear()
        _tabs_cache.clear()
        _tabs_cache_at = 0.0
    with _target_locks_guard:
        _target_locks.clear()






def _real_ua() -> str:

    try:
        with urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=3) as r:
            return json.load(r).get("User-Agent", "")
    except Exception:
        return ""


def _ensure_profile() -> None:

    global _profile, _stealth_script
    if _profile is not None:
        return
    seed = stealth.profile_seed(_PROFILE_NAME)
    _profile = stealth.derive_profile(seed, _real_ua())
    _stealth_script = stealth.build_init_script(_profile)


def _ensure_stealth(target_id: str) -> None:

    if target_id in _stealth_applied:
        return
    _ensure_profile()
    if not _stealth_script:
        return
    with _lock_for(target_id):

        _cmd(target_id, "Page.addScriptToEvaluateOnNewDocument",
             {"source": _stealth_script, "runImmediately": True, "worldName": ""})




        _eval(target_id, _stealth_script, timeout=20.0)


    _stealth_applied.add(target_id)


def _create_isolated_world(target_id: str) -> None:

    if target_id in _isolated_ctx:
        return
    try:
        frame = _cmd(target_id, "Page.getFrameTree", {}, timeout=10.0)
        fid = frame.get("frameTree", {}).get("frame", {}).get("id")
        if fid:
            res = _cmd(target_id, "Page.createIsolatedWorld",
                       {"frameId": fid, "worldName": "cortexagent-agent",
                        "grantUniveralAccess": True}, timeout=10.0)
            _isolated_ctx[target_id] = int(res.get("executionContextId"))
    except Exception:
        pass


def _isolated_eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:

    ctx = _isolated_ctx.get(target_id)
    if ctx is None:
        _create_isolated_world(target_id)
        ctx = _isolated_ctx.get(target_id)
    if ctx is None:
        return _eval(target_id, expression, timeout=timeout)
    for attempt in (1, 2):
        try:
            ws = _get_ws(target_id)
            ws.settimeout(max(0.5, timeout))
            msg_id = _next_id(target_id)
            ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
                                "params": {"expression": expression, "returnByValue": True,
                                           "contextId": ctx}}))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    msg = json.loads(ws.recv())
                except Exception:
                    break
                if msg.get("id") == msg_id:
                    r = msg.get("result", {})
                    if "exceptionDetails" in r:

                        if attempt == 1:
                            _isolated_ctx.pop(target_id, None)
                            _create_isolated_world(target_id)
                            ctx = _isolated_ctx.get(target_id)
                            break
                        return None
                    return r.get("result", {}).get("value")
        except Exception:
            pass
        if attempt == 2:
            break
    return _eval(target_id, expression, timeout=timeout)


def navigate_raw(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded",
                 timeout: int = 30) -> Dict[str, str]:

    target_id = resolve_tab(tab)
    _cmd(target_id, "Page.navigate", {"url": url}, timeout=timeout)
    time.sleep(0.5)
    title = _eval(target_id, "document.title || ''", timeout=timeout)
    href = _eval(target_id, "location.href || ''", timeout=timeout)
    return {"title": title or "", "url": href or url}






def start_guard(kill: bool = False) -> Any:

    global _guard
    if _guard is not None:
        return _guard
    if not browser_cdp_guard.assert_localhost(int(CDP_HTTP.rsplit(":", 1)[1])):
        browser_cdp_guard.alert("GUARD_REFUSED_EXPOSED", {"endpoint": CDP_HTTP})
        return None
    _guard = browser_cdp_guard.CDPGuard(sys.modules[__name__], kill=kill)
    _guard.start()
    return _guard


def stop_guard() -> None:
    global _guard
    if _guard is not None:
        _guard.stop()
        _guard = None


def stealth_status() -> Dict[str, Any]:

    return {
        "profile": _profile.get("osFamily") if _profile else None,
        "seed": _profile.get("seed") if _profile else None,
        "stealth_applied_targets": list(_stealth_applied),
        "isolated_contexts": dict(_isolated_ctx),
        "humanizer_enabled": (_humanizer_mod._enabled() if _humanizer_mod else False),
        "guard_running": bool(_guard),
    }






def list_tabs() -> List[Dict[str, Any]]:

    global _tabs_cache, _tabs_cache_at
    now = time.time()
    if _tabs_cache and (now - _tabs_cache_at) < _TABS_TTL_SEC:
        return _tabs_cache
    raw = _http_json("/json")
    _tabs_cache = [{"index": i, "id": t.get("id"), "title": t.get("title", ""),
                    "url": t.get("url", "")}
                   for i, t in enumerate(raw) if t.get("type") == "page"]
    _tabs_cache_at = now
    return _tabs_cache


def _invalidate_tabs_cache() -> None:

    global _tabs_cache_at
    _tabs_cache_at = 0.0


def find_tab(url_prefix: str) -> Optional[str]:

    for t in list_tabs():
        if t["url"].startswith(url_prefix):
            return t["id"]
    return None


def resolve_tab(tab: Any = None) -> str:

    tabs = list_tabs()
    if not tabs:
        raise RuntimeError("no tabs open")
    if tab is None:
        return tabs[0]["id"]
    if isinstance(tab, int):
        return tabs[tab]["id"] if 0 <= tab < len(tabs) else tabs[0]["id"]
    if isinstance(tab, str):
        for t in tabs:
            if t["url"].startswith(tab):
                return t["id"]
        if any(t["id"] == tab for t in tabs):
            return tab
        return tabs[0]["id"]
    return tab


def new_tab(url: str = "") -> str:

    req = urllib.request.Request(
        CDP_HTTP + "/json/new?" + urllib.parse.quote(url or "about:blank"), method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        info = json.load(r)
    _invalidate_tabs_cache()
    return info.get("id")


def close_tab(target_id: str) -> bool:

    ws = _ws_cache.pop(target_id, None)
    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass
    _invalidate_tabs_cache()
    try:
        with urllib.request.urlopen(
            CDP_HTTP + "/json/close/" + urllib.parse.quote(target_id), timeout=5
        ) as r:
            return r.status == 200
    except Exception:
        return False






def navigate(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded",
             timeout: int = 30) -> Dict[str, str]:

    if _humanizer_mod:
        try:
            return _humanizer_mod.get_humanizer(sys.modules[__name__]).navigate(
                tab, url, wait_until=wait_until, timeout=timeout)
        except Exception:
            pass
    return navigate_raw(tab, url, wait_until=wait_until, timeout=timeout)


def fetch(tab: Any = None, url: str = "", selector: str = "body",
          wait_for_text: str = "", timeout: int = 30) -> str:

    target_id = resolve_tab(tab)
    _cmd(target_id, "Page.navigate", {"url": url}, timeout=timeout)
    if wait_for_text:
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = read_text(target_id, "body")
            if wait_for_text.lower() in text.lower():
                break
            time.sleep(0.5)
    return read_text(target_id, selector)


def _click_js(selector: str, by_text: bool) -> str:
    if by_text:
        return f"""
        (() => {{
          const els = [...document.querySelectorAll('*')];
          const el = els.find(e => e.textContent && e.textContent.trim() === {json.dumps(selector)});
          if (!el) return {{ok:false}};
          el.click();
          return {{ok:true}};
        }})()
        """
    return f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return {{ok:false}};
      el.click();
      return {{ok:true}};
    }})()
    """


def click(tab: Any = None, selector: str = "", by_text: bool = False,
          timeout: int = 10) -> bool:

    if _humanizer_mod:
        try:
            return _humanizer_mod.get_humanizer(sys.modules[__name__]).click(
                tab, selector, by_text=by_text, timeout=timeout)
        except Exception:
            pass
    target_id = resolve_tab(tab)
    _eval(target_id, _click_js(selector, by_text), timeout=timeout)
    return True


def _type_js(selector: str, text: str, by_text: bool, submit: bool) -> str:
    finder = (
        f"[...document.querySelectorAll('*')].find(e => e.textContent && e.textContent.trim() === {json.dumps(selector)})"
        if by_text else f"document.querySelector({json.dumps(selector)})"
    )
    enter = ""
    if submit:
        enter = (
            "el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));\n"
            "el.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));\n"
        )
    return f"""
    (() => {{
      const el = {finder};
      if (!el) return {{ok:false}};
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, {json.dumps(text)});
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.focus();
      {enter}
      return {{ok:true}};
    }})()
    """


def type_text(tab: Any = None, selector: str = "", text: str = "",
              by_text: bool = False, submit: bool = False, timeout: int = 10) -> bool:

    if _humanizer_mod:
        try:
            return _humanizer_mod.get_humanizer(sys.modules[__name__]).type_text(
                tab, selector, text, by_text=by_text, submit=submit, timeout=timeout)
        except Exception:
            pass
    target_id = resolve_tab(tab)
    _eval(target_id, _type_js(selector, text, by_text, submit), timeout=timeout)
    return True


def evaluate(tab: Any = None, expression: str = "", timeout: int = 10) -> Any:

    target_id = resolve_tab(tab)
    return _eval(target_id, expression, timeout=timeout)


def snapshot(tab: Any = None, depth: int = 10) -> Any:

    target_id = resolve_tab(tab)
    tree = _cmd(target_id, "Accessibility.getFullAXTree", {}, timeout=10)
    nodes = tree.get("nodes") if isinstance(tree, dict) else tree
    if isinstance(nodes, list):
        return injection_guard.sanitize_dom_nodes(nodes)
    return tree


def read_text(tab: Any = None, selector: str = "body") -> str:

    target_id = resolve_tab(tab)
    js = f"(document.querySelector({json.dumps(selector)}) || document.body).innerText || ''"
    val = _eval(target_id, js)
    if not isinstance(val, str):
        return ""
    return injection_guard.sanitize(val.strip())






def _find_js(iframe_marker: str) -> str:

    marker = json.dumps(iframe_marker)
    return f"""
      const iframe = {marker} ? [...document.querySelectorAll('iframe')].find(f => (f.src||'').includes({marker})) : null;
      const doc = iframe ? iframe.contentDocument : (document.body ? document : null);
      function findEl(root, tag, cls) {{
        if (!root) return null;
        const els = root.querySelectorAll('*');
        for (const el of els) {{
          if (el.tagName === tag && (el.className||'').includes(cls)) return el;
          if (el.shadowRoot) {{ const r = findEl(el.shadowRoot, tag, cls); if (r) return r; }}
        }}
        return null;
      }}
    """


def fill_and_send(tab: Any = None, text: str = "", *, iframe_marker: str = "",
                  tag: str = "TEXTAREA", class_fragment: str = "",
                  submit: bool = True) -> bool:

    enter = ""
    if submit:
        enter = (
            "el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));\n"
            "el.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13, bubbles:true}));\n"
        )
    js = f"""
    (() => {{
      {_find_js(iframe_marker)}
      const el = findEl(doc, {json.dumps(tag)}, {json.dumps(class_fragment)});
      if (!el) return {{ok:false, err:'element not found'}};
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, {json.dumps(text)});
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.focus();
      {enter}
      return {{ok:true, val: el.value}};
    }})()
    """
    target_id = resolve_tab(tab)
    val = _eval(target_id, js)
    return bool(val and val.get("ok"))


def element_value(tab: Any = None, *, iframe_marker: str = "",
                  tag: str = "TEXTAREA", class_fragment: str = "") -> Optional[str]:

    js = f"""
    (() => {{
      {_find_js(iframe_marker)}
      const el = findEl(doc, {json.dumps(tag)}, {json.dumps(class_fragment)});
      return el ? el.value : null;
    }})()
    """
    target_id = resolve_tab(tab)
    return _eval(target_id, js)


def clear_element(tab: Any = None, *, iframe_marker: str = "",
                  tag: str = "TEXTAREA", class_fragment: str = "") -> bool:

    js = f"""
    (() => {{
      {_find_js(iframe_marker)}
      const el = findEl(doc, {json.dumps(tag)}, {json.dumps(class_fragment)});
      if (!el) return {{ok:false}};
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, '');
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      return {{ok:true}};
    }})()
    """
    target_id = resolve_tab(tab)
    val = _eval(target_id, js)
    return bool(val and val.get("ok"))


def page_text(tab: Any = None, iframe_marker: str = "") -> str:

    marker = json.dumps(iframe_marker)
    js = f"""
    (() => {{
      const iframe = {marker} ? [...document.querySelectorAll('iframe')].find(f => (f.src||'').includes({marker})) : null;
      const root = iframe ? iframe.contentDocument : document;
      if (!root) return '';
      function textOf(r) {{
        let parts = [];
        const els = r.querySelectorAll('*');
        for (const el of els) {{
          if (el.shadowRoot) parts.push(textOf(el.shadowRoot));
        }}
        const t = (r.body ? r.body.innerText : r.innerText) || '';
        if (t.trim()) parts.push(t.trim());
        return parts.join('\\n');
      }}
      return textOf(root);
    }})()
    """
    target_id = resolve_tab(tab)
    val = _eval(target_id, js)
    return injection_guard.sanitize(val) if isinstance(val, str) else ""






def _smoke() -> int:
    try:
        tabs = list_tabs()
        print(f"CDP {CDP_HTTP} reachable — {len(tabs)} tab(s):")
        for t in tabs[:15]:
            print(f"  [{t['index']}] {t['title'][:60]} — {t['url'][:80]}")
        if len(tabs) > 15:
            print(f"  ... and {len(tabs) - 15} more")
        close()
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 1


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        sys.exit(_smoke())
    print(__doc__)


if __name__ == "__main__":
    main()
