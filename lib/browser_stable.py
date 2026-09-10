#!/usr/bin/env python3

from __future__ import annotations

import json
import time
from typing import Any, Callable, List, Optional


def _eval(bc, tab, js: str, timeout: float = 8.0) -> Any:
    return bc._eval(bc.resolve_tab(tab), js, timeout=timeout)


def wait_ready(bc, tab: Any, timeout: float = 30.0, ready_state: str = "complete") -> bool:

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



    deadline = time.time() + timeout
    while time.time() < deadline:
        if _eval(bc, tab, f"!!document.querySelector({json.dumps(selector)})"):
            return True
        time.sleep(0.08)
    return False


def to_pass(fn: Callable[[], Any], *, timeout: float = 15.0, base_delay: float = 0.1,
            max_delay: float = 1.0) -> Any:

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

    sig = _eval(bc, tab, """(() => {
      const b = document.body;
      return (b ? b.children.length : 0) + ':' + (document.querySelectorAll('*').length) + ':' + document.readyState;
    })()""")
    return str(sig)


def stable_click(humanizer: Any, tab: Any, selector_candidates: List[str],
                 by_text: bool = False, retries: int = 3, timeout: int = 10) -> bool:

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

        if before != after:
            continue
        time.sleep(0.15)
    return False


def best_selector(bc, tab: Any, candidates: List[str]) -> Optional[str]:


    ranked = sorted(candidates, key=lambda s: _stability_rank(s))
    for sel in ranked:
        if _eval(bc, tab, f"!!document.querySelector({json.dumps(sel)})"):
            return sel
    return None


def _stability_rank(sel: str) -> int:

    if "data-testid" in sel:
        return 0
    if "[role" in sel:
        return 1
    if sel.startswith("#"):
        return 2
    if "." in sel and "querySelector" not in sel:
        return 3
    return 4