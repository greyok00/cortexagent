#!/usr/bin/env python3
"""humanizer — HumanizedAction dispatcher for browser_control (§3).

Every high-level action (click / type / scroll / navigate) routes through this
module. It is ON by default; disable with the env var STEALTH_HUMANIZER=0 or by
constructing Humanizer(enabled=False). It is *not* structurally non-bypassable:
callers can still use browser_control._eval/_cmd directly, but the public
action API enforces humanized pacing. (Configurable off-switch by design.)

What it adds over raw browser_control:
  - Bezier-curve mouse movement between actions via CDP Input.dispatchMouseEvent
    (real cursor path, never instant jumps or straight lines).
  - Jittered click point inside the element bounding box.
  - Randomized inter-action delays + periodic longer idle "break" windows.
  - Occasional misclick (offset) followed by a visible correction re-click, at
    a low realistic frequency. For typing: occasional mistype + backspace.
  - Per-target cursor memory so the next move starts where the last ended.

Reliability is preserved: humanized typing uses real per-char CDP key events
with a fallback to the native-value-setter if the resulting value mismatches
(the technique that works for React/LWC controlled inputs).
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, Optional, Tuple

import humanize  # existing Bezier + timing primitives (flat lib/ on sys.path)


def _enabled() -> bool:
    return os.environ.get("STEALTH_HUMANIZER", "1") not in ("0", "false", "False")


# Low rate of deliberate mistakes — enough to look human, not enough to slow work.
MISCICK_RATE = 0.04
MISTYPE_RATE = 0.03
IDLE_BREAK_RATE = 0.05      # chance of a longer "break" window after an action
IDLE_BREAK_BAND = (2.0, 6.0)


class Humanizer:
    """Wraps browser_control's low-level CDP send with human pacing.

    bc is the browser_control module (imported lazily to avoid a cycle).
    """

    def __init__(self, bc: Any, enabled: Optional[bool] = None) -> None:
        self.bc = bc
        self.enabled = _enabled() if enabled is None else enabled
        # per-target last cursor position
        self._cursor: Dict[str, Tuple[float, float]] = {}

    # -- low level ----------------------------------------------------------
    def _dispatch(self, target_id: str, method: str, params: Dict[str, Any]) -> Any:
        return self.bc._cmd(target_id, method, params, timeout=10.0)

    def _bbox(self, target_id: str, selector: str, by_text: bool) -> Optional[Dict[str, float]]:
        if by_text:
            js = f"""(() => {{
              const el = [...document.querySelectorAll('*')].find(e => e.textContent && e.textContent.trim() === {json.dumps(selector)});
              if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect();
              return {{x:r.x,y:r.y,w:r.width,h:r.height,ok:true}};
            }})()"""
        else:
            js = f"""(() => {{
              const el = document.querySelector({json.dumps(selector)});
              if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect();
              return {{x:r.x,y:r.y,w:r.width,h:r.height,ok:true}};
            }})()"""
        r = self.bc._eval(target_id, js)
        return r if (isinstance(r, dict) and r.get("ok")) else None

    def _move_to(self, target_id: str, x: float, y: float) -> None:
        """Move the cursor to (x,y) along a Bezier curve, dispatching mouseMoved."""
        start = self._cursor.get(target_id, (random.uniform(50, 400), random.uniform(50, 300)))
        x0, y0 = start
        path = humanize.bezier_path(x0, y0, x, y, steps=random.randint(14, 22), curve=0.2)
        for (px, py) in path:
            self._dispatch(target_id, "Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": px, "y": py, "button": "none", "buttons": 0})
            time.sleep(random.uniform(0.006, 0.018))
        self._cursor[target_id] = (x, y)

    def _press(self, target_id: str, x: float, y: float) -> None:
        self._dispatch(target_id, "Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1})
        time.sleep(random.uniform(0.02, 0.06))
        self._dispatch(target_id, "Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 0})

    def _point_in(self, bbox: Dict[str, float]) -> Tuple[float, float]:
        # jittered point inside the box, biased toward center
        cx, cy = bbox["x"] + bbox["w"] / 2, bbox["y"] + bbox["h"] / 2
        jx = cx + random.uniform(-bbox["w"] / 3, bbox["w"] / 3)
        jy = cy + random.uniform(-bbox["h"] / 3, bbox["h"] / 3)
        return jx, jy

    def _maybe_break(self) -> None:
        if random.random() < IDLE_BREAK_RATE:
            time.sleep(random.uniform(*IDLE_BREAK_BAND))

    # -- public actions -----------------------------------------------------
    def click(self, tab: Any, selector: str, by_text: bool = False, timeout: int = 10) -> bool:
        target_id = self.bc.resolve_tab(tab)
        bbox = self._bbox(target_id, selector, by_text)
        if not bbox:
            return False
        if not self.enabled:
            self.bc._eval(target_id, self.bc._click_js(selector, by_text), timeout=timeout)
            return True
        time.sleep(humanize.get_action_delay("hover"))
        x, y = self._point_in(bbox)
        # occasional misclick: offset well off center, then correct
        if random.random() < MISCICK_RATE:
            ox = x + random.choice([-1, 1]) * (bbox["w"] * 0.6)
            oy = y + random.choice([-1, 1]) * (bbox["h"] * 0.6)
            self._move_to(target_id, ox, oy)
            self._press(target_id, ox, oy)
            time.sleep(humanize.get_action_delay("click"))
            x, y = self._point_in(bbox)
            self._move_to(target_id, x, y)
            self._press(target_id, x, y)
        else:
            self._move_to(target_id, x, y)
            time.sleep(humanize.get_action_delay("click"))
            self._press(target_id, x, y)
        self._maybe_break()
        return True

    def type_text(self, tab: Any, selector: str, text: str, by_text: bool = False,
                  submit: bool = False, timeout: int = 10) -> bool:
        target_id = self.bc.resolve_tab(tab)
        # focus the element first
        focus_js = (
            f"[...document.querySelectorAll('*')].find(e => e.textContent && e.textContent.trim() === {json.dumps(selector)})"
            if by_text else f"document.querySelector({json.dumps(selector)})"
        )
        self.bc._eval(target_id, f"(() => {{ const el = {focus_js}; if (el) el.focus(); return !!el; }})()")
        if not self.enabled:
            self.bc._eval(target_id, self.bc._type_js(selector, text, by_text, submit), timeout=timeout)
            return True
        time.sleep(humanize.get_action_delay("type"))   # pre-field delay
        for ch in text:
            if random.random() < MISTYPE_RATE and ch not in ("\n", "\t", " "):
                self._dispatch(target_id, "Input.dispatchKeyEvent", {
                    "type": "char", "text": random.choice("aeiou") if ch.isalpha() else str(random.randint(0, 9))})
                time.sleep(random.uniform(0.05, 0.12))
                self._dispatch(target_id, "Input.dispatchKeyEvent", {
                    "type": "keyDown", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8})
                self._dispatch(target_id, "Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8})
                time.sleep(random.uniform(0.03, 0.08))
            self._dispatch(target_id, "Input.dispatchKeyEvent", {
                "type": "char", "text": ch, "key": ch if ch.isalnum() else ""})
            time.sleep(humanize.get_action_delay("type"))
        # verify value; fall back to setter if key events didn't take (controlled inputs)
        val = self.bc._eval(target_id, f"(() => {{ const el = {focus_js}; return el ? el.value : null; }})()")
        if val != text:
            self.bc._eval(target_id, self.bc._type_js(selector, text, by_text, False), timeout=timeout)
        if submit:
            self.bc._eval(target_id,
                          "const el=document.activeElement; if(el){el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,bubbles:true}));"
                          "el.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,bubbles:true}));}")
        self._maybe_break()
        return True

    def scroll(self, tab: Any, dy: int = 600, timeout: int = 10) -> None:
        target_id = self.bc.resolve_tab(tab)
        if not self.enabled:
            self.bc._eval(target_id, f"window.scrollBy(0,{int(dy)})")
            return
        # smooth-ish incremental scroll
        remaining = dy
        while remaining != 0:
            step = int(dy * 0.2) if abs(remaining) > 200 else remaining
            self.bc._eval(target_id, f"window.scrollBy(0,{step})")
            remaining -= step
            time.sleep(random.uniform(0.05, 0.12))

    def navigate(self, tab: Any, url: str, wait_until: str = "domcontentloaded",
                 timeout: int = 30) -> Dict[str, str]:
        if self.enabled:
            time.sleep(humanize.get_action_delay("navigate"))
        return self.bc.navigate_raw(tab, url, wait_until=wait_until, timeout=timeout)


# module-level singleton, lazily bound to browser_control
_H: Optional[Humanizer] = None


def get_humanizer(bc: Any) -> Humanizer:
    global _H
    if _H is None or _H.bc is not bc:
        _H = Humanizer(bc)
    return _H