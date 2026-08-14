#!/usr/bin/env python3
"""browser_control — general-purpose browser control for CortexAgent.

Controls the user's real Brave profile over Chrome DevTools Protocol
(127.0.0.1:9222). NOT task-specific: the ASU live-chat watcher is one
consumer; add more use-cases on top of this module.

Transport: page-level CDP websockets (/devtools/page/<id>), NOT Playwright's
connect_over_cdp. Why: the browser-level endpoint wedges under concurrent
client churn — observed here as Playwright connect_over_cdp connecting the
websocket but timing out on its handshake (118 tabs + stale @playwright/mcp
servers). Page-level websockets are independent per tab and never saturate.
Each tab gets ONE persistent websocket, cached and reused; reconnect on
failure.

The API is Playwright-style (list_tabs, find_tab, navigate, click, type,
evaluate, snapshot, read_text) so it is drop-in extensible. If the
browser-level endpoint recovers after a Brave restart, a Playwright-backed
transport can be swapped in behind the same API.

Usage:
    python3 lib/browser_control.py --smoke   # verify CDP + list tabs
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import websocket  # websocket-client

CDP_HTTP = "http://127.0.0.1:9222"
CDP_URL = CDP_HTTP  # alias kept for the MCP server import

_lock = threading.RLock()
_ws_cache: Dict[str, Any] = {}    # targetId -> websocket
_id_counter: Dict[str, int] = {}  # targetId -> next message id


def _http_json(path: str) -> Any:
    return json.load(urllib.request.urlopen(CDP_HTTP + path, timeout=5))


def _next_id(target_id: str) -> int:
    _id_counter[target_id] = _id_counter.get(target_id, 0) + 1
    return _id_counter[target_id]


def _get_ws(target_id: str) -> Any:
    """Return a live page-level websocket for target_id, reconnecting if dead."""
    ws = _ws_cache.get(target_id)
    if ws is not None:
        return ws
    tabs = _http_json("/json")
    ws_url = next((t.get("webSocketDebuggerUrl") for t in tabs if t.get("id") == target_id), None)
    if not ws_url:
        raise RuntimeError(f"tab {target_id} not found")
    ws = websocket.create_connection(ws_url, timeout=2, suppress_origin=True)
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Page.enable"}))
    _ws_cache[target_id] = ws
    return ws


def _eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:
    """Evaluate JS in a tab, returning the result value (or None)."""
    with _lock:
        ws = _get_ws(target_id)
        msg_id = _next_id(target_id)
        ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                _ws_cache.pop(target_id, None)  # socket died — reconnect next call
                return None
            if msg.get("id") == msg_id:
                r = msg.get("result", {})
                if "exceptionDetails" in r:
                    return None
                return r.get("result", {}).get("value")
        return None


def _cmd(target_id: str, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Any:
    """Send a CDP command (non-evaluate) and return the result dict (or None)."""
    with _lock:
        ws = _get_ws(target_id)
        msg_id = _next_id(target_id)
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                _ws_cache.pop(target_id, None)
                return None
            if msg.get("id") == msg_id:
                return msg.get("result", {})
        return None


def close() -> None:
    """Close all cached page websockets (idempotent)."""
    with _lock:
        for ws in _ws_cache.values():
            try:
                ws.close()
            except Exception:
                pass
        _ws_cache.clear()
        _id_counter.clear()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def list_tabs() -> List[Dict[str, Any]]:
    """Return [{index, id, title, url}] for every open page tab."""
    tabs = _http_json("/json")
    return [{"index": i, "id": t.get("id"), "title": t.get("title", ""), "url": t.get("url", "")}
            for i, t in enumerate(tabs) if t.get("type") == "page"]


def find_tab(url_prefix: str) -> Optional[str]:
    """Return the target id of the first tab whose URL starts with url_prefix."""
    for t in list_tabs():
        if t["url"].startswith(url_prefix):
            return t["id"]
    return None


def resolve_tab(tab: Any = None) -> str:
    """Resolve a tab reference to a target id.

    tab may be: None (first tab), an int index, a URL-prefix string, or an
    already-resolved target id. Falls back to the first tab on a miss.
    """
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
    return tab  # assume it is already a target id


def new_tab(url: str = "") -> str:
    """Open a new tab (optionally navigating to url) and return its target id."""
    req = urllib.request.Request(
        CDP_HTTP + "/json/new?" + urllib.parse.quote(url or "about:blank"), method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        info = json.load(r)
    return info.get("id")


# ---------------------------------------------------------------------------
# Page operations
# ---------------------------------------------------------------------------

def navigate(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded",
             timeout: int = 30) -> Dict[str, str]:
    """Navigate a tab and return {title, url}."""
    target_id = resolve_tab(tab)
    _cmd(target_id, "Page.navigate", {"url": url}, timeout=timeout)
    time.sleep(0.5)  # let the new document start
    title = _eval(target_id, "document.title || ''", timeout=timeout)
    href = _eval(target_id, "location.href || ''", timeout=timeout)
    return {"title": title or "", "url": href or url}


def fetch(tab: Any = None, url: str = "", selector: str = "body",
          wait_for_text: str = "", timeout: int = 30) -> str:
    """Navigate a tab, wait for optional text, extract selector text."""
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
          timeout: int = 10) -> None:
    """Click an element by CSS selector or accessible text."""
    target_id = resolve_tab(tab)
    _eval(target_id, _click_js(selector, by_text), timeout=timeout)


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
              by_text: bool = False, submit: bool = False, timeout: int = 10) -> None:
    """Type text into an element; optionally press Enter after."""
    target_id = resolve_tab(tab)
    _eval(target_id, _type_js(selector, text, by_text, submit), timeout=timeout)


def evaluate(tab: Any = None, expression: str = "", timeout: int = 10) -> Any:
    """Evaluate JS in a tab and return the result value."""
    target_id = resolve_tab(tab)
    return _eval(target_id, expression, timeout=timeout)


def snapshot(tab: Any = None, depth: int = 10) -> Any:
    """Return the accessibility tree of a tab (list of AX nodes)."""
    target_id = resolve_tab(tab)
    return _cmd(target_id, "Accessibility.getFullAXTree", {}, timeout=10)


def read_text(tab: Any = None, selector: str = "body") -> str:
    """Return the inner text of a selector (default: whole page body)."""
    target_id = resolve_tab(tab)
    js = f"(document.querySelector({json.dumps(selector)}) || document.body).innerText || ''"
    val = _eval(target_id, js)
    return val.strip() if isinstance(val, str) else ""


# ---------------------------------------------------------------------------
# Shadow-DOM / controlled-component helpers (proven in the ASU chat watcher)
# ---------------------------------------------------------------------------

def _find_js(iframe_marker: str) -> str:
    """JS setup block: leaves `doc` (matching iframe's contentDocument, or the
    top document) and `findEl(root, tag, cls)` in scope. findEl pierces
    shadow roots recursively."""
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
    """Fill a controlled component (React/LWC) and optionally press Enter.

    Uses the native value setter + input event (the technique that works for
    React/LWC controlled inputs), then Enter keydown/keyup. Returns True on
    success. If submit=False, only fills (nothing sent).
    """
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
    """Return the current value of a shadow-DOM element, or None."""
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
    """Clear a shadow-DOM element's value (no Enter)."""
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
    """Read page text, piercing iframes and shadow roots.

    If iframe_marker is given, only the matching iframe's document is read
    (e.g. 'lwc.mode' for the Salesforce embedded-messaging iframe).
    """
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
    return val if isinstance(val, str) else ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
