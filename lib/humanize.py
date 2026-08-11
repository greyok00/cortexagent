#!/usr/bin/env python3
"""humanize — human-like timing primitives for browser automation.

Human-like timing primitives for browser automation. Only the bits useful to a
coding agent that drives Playwright:
  - get_action_delay(action)        realistic delay for an action type
  - get_typing_delay(text)           realistic per-string typing delay
  - get_variable_sleep(base, var)   jittered sleep duration
  - bezier_path(x0,y0,x1,y1,...)    list of intermediate points on a curved path
  - human_sleep(seconds)            convenience wrapper that sleeps with jitter

No site, earnings, schedule, or DB code. Stdlib only. The model calls these via
Bash (e.g. `python3 lib/humanize.py delay click` or imports them).

Env knobs:
  HUMANIZE_BASE_MULT   float  multiplies every base delay (1.0 = default)
  HUMANIZE_JITTER      float  ± jitter fraction (0.3 = ±30%, default)
"""
from __future__ import annotations

import os
import random
import sys
import time
from typing import List, Tuple

# Per-action delay bands (seconds). Mirrors human_behavior.get_action_delay.
_ACTION_BANDS = {
    "click":      (0.3, 1.5),
    "type":       (0.05, 0.20),   # per character
    "read":       (2.0, 8.0),
    "think":      (1.0, 4.0),
    "navigate":   (1.0, 3.0),
    "scroll":     (0.5, 2.0),
    "form_fill":  (0.5, 2.0),     # per field
    "submit":     (1.0, 3.0),
    "start_task": (2.0, 5.0),
    "drag":       (0.4, 1.2),
    "hover":      (0.2, 0.8),
}


def _multiplier() -> float:
    try:
        return float(os.environ.get("HUMANIZE_BASE_MULT", "1.0"))
    except ValueError:
        return 1.0


def get_action_delay(action: str = "click") -> float:
    """Realistic delay (seconds) for an action type. Random in band × env mult."""
    band = _ACTION_BANDS.get(action, (0.5, 2.0))
    base = random.uniform(*band) * _multiplier()
    return round(base, 3)


def get_typing_delay(text: str) -> float:
    """Realistic total typing delay for a string of text (seconds).

    Per-char base from _ACTION_BANDS["type"] with ±20% per-char jitter, then
    scaled by env multiplier.
    """
    low, high = _ACTION_BANDS["type"]
    per_char = random.uniform(low, high)
    chars = max(1, len(text))
    total = per_char * chars * random.uniform(0.8, 1.2) * _multiplier()
    return round(total, 3)


def get_variable_sleep(base_seconds: float, variance: float = 0.3) -> float:
    """Apply ±variance jitter to a sleep duration and return it (don't sleep)."""
    try:
        var = float(os.environ.get("HUMANIZE_JITTER", str(variance)))
    except ValueError:
        var = variance
    jitter = base_seconds * var
    return round(base_seconds + random.uniform(-jitter, jitter), 3)


def human_sleep(base_seconds: float, variance: float = 0.3) -> float:
    """Sleep for get_variable_sleep(base_seconds). Returns the actual seconds slept."""
    s = get_variable_sleep(base_seconds, variance)
    time.sleep(s)
    return s


def bezier_path(x0: float, y0: float, x1: float, y1: float,
                steps: int = 12, curve: float = 0.25) -> List[Tuple[float, float]]:
    """Generate a list of (x, y) points along a slight quadratic-bezier-like curve.

    Real mouse moves curve slightly off the straight line; this returns the
    intermediate points for Playwright's mouse.move(..., steps=N). `curve` is
    the perpendicular offset as a fraction of the segment length.
    """
    steps = max(2, int(steps))
    # Perpendicular midpoint offset
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    # Perpendicular unit vector (rotated 90°)
    px, py = -dy / length, dx / length
    # Random sign for natural variation
    sign = random.choice([-1.0, 1.0])
    cx = (x0 + x1) / 2 + px * length * curve * sign
    cy = (y0 + y1) / 2 + py * length * curve * sign
    points = []
    for i in range(steps + 1):
        t = i / steps
        # Quadratic Bezier formula
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1
        # Small per-step jitter (a few px) so it doesn't look perfectly smooth
        x += random.uniform(-0.5, 0.5)
        y += random.uniform(-0.5, 0.5)
        points.append((round(x, 2), round(y, 2)))
    return points


# ── CLI ─────────────────────────────────────────────────────────────────────
def _cli(argv: List[str]) -> int:
    if not argv:
        print("usage: humanize.py {delay|typing|sleep|bezier}", file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "delay":
        action = argv[1] if len(argv) > 1 else "click"
        print(get_action_delay(action))
    elif cmd == "typing":
        text = argv[1] if len(argv) > 1 else ""
        print(get_typing_delay(text))
    elif cmd == "sleep":
        base = float(argv[1]) if len(argv) > 1 else 1.0
        var = float(argv[2]) if len(argv) > 2 else 0.3
        print(human_sleep(base, var))
    elif cmd == "bezier":
        # bezier x0 y0 x1 y1 [steps] [curve]
        try:
            x0, y0, x1, y1 = (float(argv[i]) for i in range(1, 5))
        except (IndexError, ValueError):
            print("bezier needs: x0 y0 x1 y1 [steps] [curve]", file=sys.stderr)
            return 2
        steps = int(argv[5]) if len(argv) > 5 else 12
        curve = float(argv[6]) if len(argv) > 6 else 0.25
        for p in bezier_path(x0, y0, x1, y1, steps, curve):
            print(f"{p[0]},{p[1]}")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))