#!/usr/bin/env python3

from __future__ import annotations

import os
import random
import sys
import time
from typing import List, Tuple


_ACTION_BANDS = {
    "click":      (0.3, 1.5),
    "type":       (0.05, 0.20),
    "read":       (2.0, 8.0),
    "think":      (1.0, 4.0),
    "navigate":   (1.0, 3.0),
    "scroll":     (0.5, 2.0),
    "form_fill":  (0.5, 2.0),
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

    band = _ACTION_BANDS.get(action, (0.5, 2.0))
    base = random.uniform(*band) * _multiplier()
    return round(base, 3)


def get_typing_delay(text: str) -> float:

    low, high = _ACTION_BANDS["type"]
    per_char = random.uniform(low, high)
    chars = max(1, len(text))
    total = per_char * chars * random.uniform(0.8, 1.2) * _multiplier()
    return round(total, 3)


def get_variable_sleep(base_seconds: float, variance: float = 0.3) -> float:

    try:
        var = float(os.environ.get("HUMANIZE_JITTER", str(variance)))
    except ValueError:
        var = variance
    jitter = base_seconds * var
    return round(base_seconds + random.uniform(-jitter, jitter), 3)


def human_sleep(base_seconds: float, variance: float = 0.3) -> float:

    s = get_variable_sleep(base_seconds, variance)
    time.sleep(s)
    return s


def bezier_path(x0: float, y0: float, x1: float, y1: float,
                steps: int = 12, curve: float = 0.25) -> List[Tuple[float, float]]:

    steps = max(2, int(steps))

    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5 or 1.0

    px, py = -dy / length, dx / length

    sign = random.choice([-1.0, 1.0])
    cx = (x0 + x1) / 2 + px * length * curve * sign
    cy = (y0 + y1) / 2 + py * length * curve * sign
    points = []
    for i in range(steps + 1):
        t = i / steps

        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1

        x += random.uniform(-0.5, 0.5)
        y += random.uniform(-0.5, 0.5)
        points.append((round(x, 2), round(y, 2)))
    return points



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