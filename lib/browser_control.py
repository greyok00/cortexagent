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

import atexit
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import websocket  # websocket-client

# Stealth / humanizer / guard / pool — stdlib-only, integrated always-active
# components. Imported lazily-guarded at top so a failure in one never blocks
# the core CDP transport (graceful degradation: automation still works without
# the stealth layer if something is off).
import stealth                      # §1,§2 fingerprint + init script
import injection_guard              # §5 prompt-injection defense
import browser_cdp_guard            # §4 CDP connection security
try:
    import humanizer as _humanizer_mod  # §3 HumanizedAction dispatcher
except Exception:
    _humanizer_mod = None

CDP_HTTP = "http://127.0.0.1:9222"
CDP_URL = CDP_HTTP  # alias kept for the MCP server import

# --- Stealth / humanizer / guard state ------------------------------------
_PROFILE_NAME = os.environ.get("STEALTH_PROFILE", "default")
_profile: Optional[Dict[str, Any]] = None       # derived coherent device profile
_stealth_script: Optional[str] = None           # JS init script (built once)
_isolated_ctx: Dict[str, int] = {}              # target_id -> isolated world ctxId
_stealth_applied: set = set()                    # target_ids with init injected
_guard: Any = None                              # CDPGuard instance (on demand)

# Per-target locks: serialize within one tab (one websocket), parallelize across
# tabs. Falls back to a module-level lock for non-target-scoped ops.
_lock = threading.RLock()
_target_locks: Dict[str, threading.RLock] = {}
_target_locks_guard = threading.Lock()
_ws_cache: Dict[str, Any] = {}    # targetId -> websocket
_id_counter: Dict[str, int] = {}  # targetId -> next message id

# Short-TTL cache for /json so a burst of resolve_tab calls hits the network
# at most once. Tab list is cheap to fetch but pointless to repeat inside a
# tool batch. ~150ms covers a typical MCP burst without losing freshness.
_TABS_TTL_SEC = 0.15
_tabs_cache: List[Dict[str, Any]] = []
_tabs_cache_at: float = 0.0

# Lightweight in-process metrics. Read via health(). Counters are atomic enough
# for observability purposes (no exactness needed). Zero behavior change to
# callers — pure observation.
_metrics_lock = threading.Lock()
_metrics: Dict[str, Any] = {
    "calls": 0,            # total _eval / _cmd calls
    "reconnects": 0,       # websocket reconnects (stale target or first connect)
    "json_fetches": 0,     # /json HTTP round-trips (cache misses + liveness checks)
    "retries": 0,          # one-shot retries inside _eval / _cmd
    "failures": 0,         # calls returning None due to error or timeout
    "last_call_ms": 0.0,   # wall-clock duration of the most recent call
    "started_at": time.time(),
}

_atexit_registered = False


def _atexit_close() -> None:
    """Best-effort cleanup at interpreter exit so we don't leak sockets on the
    browser side when our process dies. Idempotent."""
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
    """Return a per-target RLock. Lazily created under a guard so two callers
    asking for the same target get the same lock."""
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
    """Return a live page-level websocket for target_id, reconnecting if dead.

    Validates the cached socket's target is still in the browser's tab list
    (handles navigation / tab close without disturbing anything else). Sets a
    socket recv timeout so a hung tab cannot block past the caller's deadline.
    """
    ws = _ws_cache.get(target_id)
    if ws is not None:
        # Cheap liveness check: target id must still exist in /json.
        try:
            tabs = _http_json("/json")
        except Exception:
            # /json failed — assume cached socket may be stale; drop and reconnect.
            try: ws.close()
            except Exception: pass
            _ws_cache.pop(target_id, None)
            ws = None
            _invalidate_tabs_cache()  # refresh on the way back up
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
    ws.settimeout(2.0)  # recv-level timeout; caller's deadline still wins via the loop
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": _next_id(target_id), "method": "Page.enable"}))
    _ws_cache[target_id] = ws
    # Inject the stealth init script + create an isolated agent world. Best-effort:
    # a failure here must never block the core transport (graceful degradation).
    try:
        _ensure_stealth(target_id)
    except Exception:
        pass
    _invalidate_tabs_cache()  # a fresh connect implies the cache may be stale
    with _metrics_lock:
        _metrics["reconnects"] += 1
    return ws


def _eval(target_id: str, expression: str, timeout: float = 8.0) -> Any:
    """Evaluate JS in a tab, returning the result value (or None).

    One-shot retry: if the first attempt times out or the socket errors, the
    cached socket is evicted and we make one more attempt on a fresh socket
    before giving up. This rides out transient tab navigation / socket churn
    without disturbing anything else (no browser restart, no tab close).
    """
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
                        break  # recv timed out or socket died — retry once
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
        # loop ends naturally after attempt 1 (continue) or attempt 2 (break)
    dt_ms = (time.time() - t0) * 1000.0
    with _metrics_lock:
        _metrics["last_call_ms"] = dt_ms
        if last is None:
            _metrics["failures"] += 1
    return last


def _cmd(target_id: str, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Any:
    """Send a CDP command (non-evaluate) and return the result dict (or None).

    Same one-shot retry semantics as _eval.
    """
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
    """Return a snapshot of the engine's runtime metrics + CDP reachability.

    Generic — reports counts and latencies, no site data. Safe to call from
    any consumer (tools, doctor, scripts). Never raises.
    """
    snap: Dict[str, Any] = {}
    with _metrics_lock:
        snap.update(_metrics)
    snap["uptime_sec"] = time.time() - snap.get("started_at", time.time())
    snap.pop("started_at", None)
    snap["cached_sockets"] = len(_ws_cache)
    snap["cached_tab_list_age_ms"] = int((time.time() - _tabs_cache_at) * 1000) if _tabs_cache else -1
    # Live reachability probe (cheap, ~ms): if it fails, surface as not reachable.
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
    """Close all cached page websockets (idempotent)."""
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


# ---------------------------------------------------------------------------
# Stealth layer (§1,§2): init-script injection + isolated agent worlds
# ---------------------------------------------------------------------------

def _real_ua() -> str:
    """Read the real user-agent from the patched Brave binary's /json/version.

    Per spec the UA is generated from the real binary's actual capabilities,
    never spoofed independently of the rest of the fingerprint.
    """
    try:
        with urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=3) as r:
            return json.load(r).get("User-Agent", "")
    except Exception:
        return ""


def _ensure_profile() -> None:
    """Derive the coherent device profile once from the real UA + profile name."""
    global _profile, _stealth_script
    if _profile is not None:
        return
    seed = stealth.profile_seed(_PROFILE_NAME)
    _profile = stealth.derive_profile(seed, _real_ua())
    _stealth_script = stealth.build_init_script(_profile)


def _ensure_stealth(target_id: str) -> None:
    """Register the stealth init script for new documents AND apply it to the
    current document now, then create an isolated execution world for agent
    scripts. Idempotent per target.

    The init script runs in the MAIN world (required: it must intercept the
    page's canvas/WebGL/navigator calls). Agent-injected scripts run in an
    ISOLATED world (createIsolatedWorld) so they never pollute the page's JS
    context.
    """
    if target_id in _stealth_applied:
        return
    _ensure_profile()
    if not _stealth_script:
        return
    with _lock_for(target_id):
        # Register for all future navigations (new documents) in this target.
        _cmd(target_id, "Page.addScriptToEvaluateOnNewDocument",
             {"source": _stealth_script, "runImmediately": True, "worldName": ""})
        # Apply to the current document now. The init script is idempotent (it
        # guards on window.__stealth_patched__ and returns early), so even if
        # runImmediately already applied it this is a safe no-op — it does NOT
        # re-capture the patched prototypes as "originals" (which would recurse).
        _eval(target_id, _stealth_script, timeout=20.0)
        # The isolated agent world is created LAZILY by _isolated_eval (most tabs
        # never need it), so it does not add round-trips to every connect.
    _stealth_applied.add(target_id)


def _create_isolated_world(target_id: str) -> None:
    """Lazily create the agent's isolated execution world for a target."""
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
    """Evaluate JS in the agent's isolated execution world (never the page's
    main context). Falls back to main-world _eval if no isolated world exists
    or the cached one is stale. Retries once on a stale context."""
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
                        # Stale isolated context -> recreate once.
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
    """Navigate a tab and return {title, url}. Raw — no humanizer layer."""
    target_id = resolve_tab(tab)
    _cmd(target_id, "Page.navigate", {"url": url}, timeout=timeout)
    time.sleep(0.5)  # let the new document start
    title = _eval(target_id, "document.title || ''", timeout=timeout)
    href = _eval(target_id, "location.href || ''", timeout=timeout)
    return {"title": title or "", "url": href or url}


# ---------------------------------------------------------------------------
# CDP connection security (§4): guard lifecycle
# ---------------------------------------------------------------------------

def start_guard(kill: bool = False) -> Any:
    """Start the CDP guard watching for an exposed endpoint / foreign client
    attachment. Refuses to run if the debug port is bound to a routable iface."""
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
    """Report the live stealth/humanizer/guard state for diagnostics."""
    return {
        "profile": _profile.get("osFamily") if _profile else None,
        "seed": _profile.get("seed") if _profile else None,
        "stealth_applied_targets": list(_stealth_applied),
        "isolated_contexts": dict(_isolated_ctx),
        "humanizer_enabled": (_humanizer_mod._enabled() if _humanizer_mod else False),
        "guard_running": bool(_guard),
    }


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def list_tabs() -> List[Dict[str, Any]]:
    """Return [{index, id, title, url}] for every open page tab.

    Cached for ~150ms so a burst of resolve_tab calls inside one tool batch
    does not re-hit /json every time.
    """
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
    """Force the next list_tabs() to refetch /json. Used by new_tab()."""
    global _tabs_cache_at
    _tabs_cache_at = 0.0


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
    _invalidate_tabs_cache()  # new tab must be visible to the next resolve_tab
    return info.get("id")


# ---------------------------------------------------------------------------
# Page operations
# ---------------------------------------------------------------------------

def navigate(tab: Any = None, url: str = "", wait_until: str = "domcontentloaded",
             timeout: int = 30) -> Dict[str, str]:
    """Navigate a tab (humanized) and return {title, url}.

    Routes through the HumanizedAction dispatcher (§3) when the humanizer is
    enabled; otherwise calls navigate_raw directly. The humanizer adds a
    pre-navigation delay to mimic natural pacing; STEALTH_HUMANIZER=0 disables.
    """
    if _humanizer_mod:
        try:
            return _humanizer_mod.get_humanizer(sys.modules[__name__]).navigate(
                tab, url, wait_until=wait_until, timeout=timeout)
        except Exception:
            pass
    return navigate_raw(tab, url, wait_until=wait_until, timeout=timeout)


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
          timeout: int = 10) -> bool:
    """Click an element by CSS selector or accessible text.

    Routes through the HumanizedAction dispatcher (§3): real Bezier mouse
    movement + jittered click point + occasional misclick/correction via CDP
    Input.dispatchMouseEvent. Falls back to synthetic el.click() if the
    humanizer is disabled (STEALTH_HUMANIZER=0) or unavailable.
    """
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
    """Type text into an element; optionally press Enter after.

    Routes through the HumanizedAction dispatcher (§3): per-character CDP key
    events with humanized timing + occasional mistype/backspace correction,
    falling back to the native-value-setter (reliable for React/LWC controlled
    inputs) if the key-event path produces a mismatch. STEALTH_HUMANIZER=0
    disables and uses the setter directly.
    """
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
    """Evaluate JS in a tab and return the result value."""
    target_id = resolve_tab(tab)
    return _eval(target_id, expression, timeout=timeout)


def snapshot(tab: Any = None, depth: int = 10) -> Any:
    """Return the accessibility tree of a tab (list of AX nodes).

    AX node text/labels are scraped content -> sanitized via the injection
    guard (§5) before returning.
    """
    target_id = resolve_tab(tab)
    tree = _cmd(target_id, "Accessibility.getFullAXTree", {}, timeout=10)
    nodes = tree.get("nodes") if isinstance(tree, dict) else tree
    if isinstance(nodes, list):
        return injection_guard.sanitize_dom_nodes(nodes)
    return tree


def read_text(tab: Any = None, selector: str = "body") -> str:
    """Return the inner text of a selector (default: whole page body).

    All scraped DOM text is treated as UNTRUSTED and run through the
    injection guard (§5) before it can enter agent context.
    """
    target_id = resolve_tab(tab)
    js = f"(document.querySelector({json.dumps(selector)}) || document.body).innerText || ''"
    val = _eval(target_id, js)
    if not isinstance(val, str):
        return ""
    return injection_guard.sanitize(val.strip())


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
    return injection_guard.sanitize(val) if isinstance(val, str) else ""


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
