#!/usr/bin/env python3
"""browser_stable — reliability layer for browser_control (§6).

Replaces static sleeps with event-based waits and adds flake resistance:

  - wait_ready()       : wait for document.readyState (Navigation Timing signal).
  - wait_network_idle(): wait until no new network resources arrive for a quiet
                         window (network-idle approximation via Performance API).
  - wait_selector()    : MutationObserver-backed wait for an element to appear.
  - to_pass()          : retry-with-backoff for flaky assertions (toPass-style).
  - stable_click()     : snapshot-before/after + stale-element retry with a
                         fresh element query, trying stable selectors first.
  - best_selector()    : prefer data-testid / stable attrs over text/XPath.

No waitForTimeout / sleep in the wait paths; the only sleeps here are the
small poll intervals and exponential backoff in to_pass, both bounded.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, List, Optional


def _eval(bc, tab, js: str, timeout: float = 8.0) -> Any:
    return bc._eval(bc.resolve_tab(tab), js, timeout=timeout)


def wait_ready(bc, tab: Any, timeout: float = 30.0, ready_state: str = "complete") -> bool:
    """Wait for document.readyState to reach ready_state. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = _eval(bc, tab, "document.readyState")
        if isinstance(st, str) and st and _rs_index(st) >= _rs_index(ready_state):
            return True
        time.sleep(0.05)
    return False


def _rs_index(s: str) -> int:
    return {"loading": 0, "interactive": 1, "domcomplete": 2, "complete": 2}.get(s, 2)


def wait_network_idle(bc, tab: Any, timeout: float = 30.0, quiet_ms: int = 500) -> bool:
    """Return True when no new network resources have arrived for `quiet_ms`.

    Polls performance.getEntriesByType('resource').length; when it stops growing
    for `quiet_ms`, consider the network idle. Combined with readyState this is a
    practical network-idle signal without a persistent PerformanceObserver.
    """
    deadline = time.time() + timeout
    last_count = -1
    quiet_since = None
    while time.time() < deadline:
        count = _eval(bc, tab, "performance.getEntriesByType('resource').length")
        if isinstance(count, (int, float)):
            if count == last_count:
                if quiet_since is None:
                    quiet_since = time.time()
                if (time.time() - quiet_since) * 1000 >= quiet_ms:
                    return True
            else:
                quiet_since = None
            last_count = count
        time.sleep(quiet_ms / 1000.0 / 2 + 0.02)
    return False


def wait_selector(bc, tab: Any, selector: str, timeout: float = 15.0) -> bool:
    """Wait for a CSS selector to appear in the DOM (MutationObserver-backed)."""
    js = f"""(() => {{
      if (document.querySelector({json.dumps(selector)})) return true;
      return new Promise((resolve) => {{
        const obs = new MutationObserver(() => {{
          if (document.querySelector({json.dumps(selector)})) {{ obs.disconnect(); resolve(true); }}
        }});
        obs.observe(document.documentElement, {{childList:true, subtree:true}});
        setTimeout(() => {{ obs.disconnect(); resolve(false); }}, {int(timeout*1000)});
      }});
    }})()"""
    # Promise resolves async; poll a sentinel via a small loop using _eval won't
    # await a promise, so fall back to polling the selector directly.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _eval(bc, tab, f"!!document.querySelector({json.dumps(selector)})"):
            return True
        time.sleep(0.08)
    return False


def to_pass(fn: Callable[[], Any], *, timeout: float = 15.0, base_delay: float = 0.1,
            max_delay: float = 1.0) -> Any:
    """Retry `fn` with exponential backoff until it returns truthy or timeout.

    `fn` should raise or return falsy to signal a flaky-failure; the last result
    (or raised exception) is returned/raised on exhaustion. toPass-style.
    """
    deadline = time.time() + timeout
    delay = base_delay
    last_exc: Optional[Exception] = None
    last: Any = False
    while time.time() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:
            last_exc = e
        time.sleep(delay)
        delay = min(max_delay, delay * 1.7)
    if last_exc:
        raise last_exc
    return last


def _dom_signature(bc, tab: Any) -> str:
    """A cheap DOM-state signature for stale-element / change detection."""
    sig = _eval(bc, tab, """(() => {
      const b = document.body;
      return (b ? b.children.length : 0) + ':' + (document.querySelectorAll('*').length) + ':' + document.readyState;
    })()""")
    return str(sig)


def stable_click(humanizer: Any, tab: Any, selector_candidates: List[str],
                 by_text: bool = False, retries: int = 3, timeout: int = 10) -> bool:
    """Click using the first matching selector among candidates, with
    stale-element retry: snapshot the DOM signature, click, and on failure
    re-query with a fresh selector and retry up to `retries` times."""
    for attempt in range(retries):
        sel = best_selector(humanizer.bc, tab, selector_candidates)
        if not sel:
            time.sleep(0.1)
            continue
        before = _dom_signature(humanizer.bc, tab)
        try:
            ok = humanizer.click(tab, sel, by_text=by_text, timeout=timeout)
            if ok:
                return True
        except Exception:
            pass
        after = _dom_signature(humanizer.bc, tab)
        # if the DOM changed under us (stale), re-query and retry
        if before != after:
            continue
        time.sleep(0.15)
    return False


def best_selector(bc, tab: Any, candidates: List[str]) -> Optional[str]:
    """Return the first candidate that currently matches an element.

    Stable selectors (data-testid, id, [role]) are preferred by ordering the
    caller's candidates; we just pick the first that exists, with a light
    preference for testid if any candidate contains 'data-testid'/'#'.
    """
    # Prefer the most-stable candidate that exists.
    ranked = sorted(candidates, key=lambda s: _stability_rank(s))
    for sel in ranked:
        if _eval(bc, tab, f"!!document.querySelector({json.dumps(sel)})"):
            return sel
    return None


def _stability_rank(sel: str) -> int:
    """Lower = more stable. data-testid > role > id > class > text."""
    if "data-testid" in sel:
        return 0
    if "[role" in sel:
        return 1
    if sel.startswith("#"):
        return 2
    if "." in sel and "querySelector" not in sel:
        return 3
    return 4  # text/xpath-ish