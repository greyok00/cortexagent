#!/usr/bin/env python3

from __future__ import annotations

import sys
import time
from typing import List, Optional







_STAGES: dict[str, dict] = {
    "preparing": {

        "frames": [
            ["              ╭───────◈───────╮", "              │  ◌  ◉  ◌  ◉   │"],
            ["              ╭───────◈───────╮", "              │  ◉  ◌  ◉  ◌   │"],
            ["              ╭───────◈───────╮", "              │  ◌  ◉  ◌  ◉   │"],
            ["              ╭───────◈───────╮", "              │  ◉  ◌  ◉  ◌   │"],
        ],
        "status": "Organizing your request and checking required context.",
        "label": "Context preparation",
        "short": "Organizing context",
    },
    "slimtoken": {

        "frames": [
            ["   [████████████]  →  ◈  →  [██████████]", "   context before           optimized context"],
            ["   [███████████]  →  ◈  →  [█████████]",   "   context before           optimized context"],
            ["   [██████████]  →  ◈  →  [████████]",     "   context before           optimized context"],
            ["   [█████████]  →  ◈  →  [███████]",       "   context before           optimized context"],
        ],
        "status": "Optimizing context with SlimToken.",
        "label": "SlimToken optimization",
        "short": "Optimizing context",
    },
    "sending": {

        "frames": [
            ["     ◇ ──◇ ──▶ [ ◈ MODEL ]", ""],
            ["    ◇ ──◇ ──◇ ──▶ [ ◈ MODEL ]", ""],
            ["   ◇ ──◇ ──◇ ──◇ ──▶ [ ◈ MODEL ]", ""],
            ["    ◇ ──◇ ──◇ ──▶ [ ◈ MODEL ]", ""],
        ],
        "status": "Sending the request to the model.",
        "label": "Sending / prefill",
        "short": "Sending",
    },
    "generating": {

        "frames": [
            ["   [ ◈ MODEL ] ──▶ ▁", ""],
            ["   [ ◈ MODEL ] ──▶ ▁▃", ""],
            ["   [ ◈ MODEL ] ──▶ ▁▃▆", ""],
            ["   [ ◈ MODEL ] ──▶ ▁▃▆█▆", ""],
        ],
        "status": "Generating a response from the prepared context.",
        "label": "Generating response",
        "short": "Generating",
    },
    "tool": {

        "frames": [
            ["   [ ◈ ] ── · ──▶ [ ⬡ TOOL ]", ""],
            ["   [ ◈ ] ── ·· ──▶ [ ⬡ TOOL ]", ""],
            ["   [ ◈ ] ── ··· ─▶ [ ⬡ TOOL ]", ""],
            ["   [ ◈ ] ── ·· ──▶ [ ⬡ TOOL ]", ""],
        ],
        "status": "Waiting on a tool.",
        "label": "Tool wait",
        "short": "Waiting on tool",
    },
    "completion": {

        "frames": [
            ["                ✦  ✓  ✦", "             Request complete"],
        ],
        "status": "Request complete.",
        "label": "Complete",
        "short": "Request complete",
    },
    "error": {

        "frames": [
            ["                !  ◈  !", "          Request needs attention"],
        ],
        "status": "The model connection was interrupted before completion.",
        "label": "Needs attention",
        "short": "Needs attention",
    },
}


_STAGE_ORDER = ["preparing", "slimtoken", "sending", "generating", "tool"]

_FRAME_INTERVAL_MS = 180.0


def _bar(pct: Optional[float], width: int) -> str:

    if pct is None:

        filled = max(1, width // 3)
        span = max(1, width - filled)
        pos = int((time.time() * 2) % span)
        bar = " " * pos + "█" * filled + " " * (width - pos - filled)
        return f"[{bar}]"
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * pct / 100.0))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.0f}%"


def _truncate(s: str, width: int) -> str:

    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def _pct_str(progress: Optional[float]) -> str:

    if progress is None:
        return ""
    pct = max(0.0, min(100.0, float(progress)))
    return f" {pct:.0f}%"


def render_card(
    stage: str = "preparing",
    progress: Optional[float] = None,
    metrics: Optional[dict] = None,
    terminal_width: int = 80,
    reduced_motion: bool = False,
    stage_index: Optional[int] = None,
    stage_total: int = 5,
    frame: int = 0,
    frame_interval_ms: float = _FRAME_INTERVAL_MS,
) -> List[str]:

    if stage not in _STAGES:
        return []
    spec = _STAGES[stage]
    metrics = metrics or {}


    if terminal_width < 40:

        return [f"◈ {spec['short']}{_pct_str(progress)}"]
    if terminal_width <= 54:

        short = spec["short"]
        return [f"◈  ◌ ◉ ◌  {short}{_pct_str(progress)}"]


    panel = min(72, terminal_width - 2)
    panel = max(40, panel)
    inner = panel - 2


    frames = spec["frames"]
    if reduced_motion or len(frames) == 1:
        frame = 0
    else:
        frame = frame % len(frames)
    visual = frames[frame]


    rows: List[str] = []


    title = " CORTEX / ACTIVE "
    rows.append("╭─" + title + "─" * max(0, inner - len(title)) + "╮")


    for vline in visual:
        v = _truncate(vline, inner)
        pad = max(0, (inner - len(v)) // 2)
        rows.append("│" + " " * pad + v + " " * (inner - pad - len(v)) + "│")


    status = _truncate(spec["status"], inner)
    rows.append("│" + status + " " * (inner - len(status)) + "│")


    bar_width = max(8, inner - len(spec["label"]) - 4)
    bar = _bar(progress, bar_width)
    prog_row = _truncate(f"{bar}  {spec['label']}", inner)
    rows.append("│" + prog_row + " " * (inner - len(prog_row)) + "│")


    bits: List[str] = []
    if stage_index is not None:
        bits.append(f"{stage_index} of {stage_total} stages")
    if metrics.get("tokens"):
        bits.append(f"{metrics['tokens']} tokens")
    if metrics.get("tok_s"):
        bits.append(f"{metrics['tok_s']:.0f} tok/s")
    if metrics.get("saved"):
        bits.append(f"saved {metrics['saved']} tokens")
    if metrics.get("saved_pct"):
        bits.append(f"({metrics['saved_pct']:.0f}%)")
    bits.append("Esc stop")
    metric_row = _truncate(" · ".join(bits), inner)
    rows.append("│" + metric_row + " " * (inner - len(metric_row)) + "│")


    rows.append("╰" + "─" * inner + "╯")

    return rows


def pick_frame(stage: str, reduced_motion: bool = False,
               frame_interval_ms: float = _FRAME_INTERVAL_MS) -> int:

    spec = _STAGES.get(stage)
    if not spec or reduced_motion:
        return 0
    frames = spec["frames"]
    if len(frames) <= 1:
        return 0
    interval_s = max(0.05, frame_interval_ms / 1000.0)
    return int(time.monotonic() / interval_s) % len(frames)


class ProcessingAnimation:


    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr
        self._is_tty = hasattr(self.stream, "isatty") and self.stream.isatty()
        self._last_rows: List[str] = []

    def show(
        self,
        stage: str = "preparing",
        progress: Optional[float] = None,
        metrics: Optional[dict] = None,
        terminal_width: int = 80,
        reduced_motion: bool = False,
        stage_index: Optional[int] = None,
        stage_total: int = 5,
        frame: Optional[int] = None,
        frame_interval_ms: float = _FRAME_INTERVAL_MS,
    ) -> None:
        if frame is None:
            frame = pick_frame(stage, reduced_motion, frame_interval_ms)
        rows = render_card(
            stage, progress, metrics, terminal_width,
            reduced_motion, stage_index, stage_total, frame, frame_interval_ms,
        )
        if not rows:
            return

        for _ in self._last_rows:
            self.stream.write("\x1b[1A\x1b[2K")

        for row in rows:
            self.stream.write(row + "\n")
        self.stream.flush()
        self._last_rows = rows

    def hide(self) -> None:

        for _ in self._last_rows:
            self.stream.write("\x1b[1A\x1b[2K")
        self.stream.flush()
        self._last_rows = []




def stage_from_workphase(phase: str) -> str:

    return {
        "preparing": "preparing",
        "warming": "sending",
        "generating": "generating",
        "waiting_tool": "tool",
        "retrying": "sending",
        "unavailable": "error",
        "ready": "completion",
        "idle": "preparing",
    }.get(phase, "preparing")




def _smoke() -> int:

    for stage in _STAGES:
        for f in range(min(2, len(_STAGES[stage]["frames"]))):
            rows = render_card(stage, progress=48.0, metrics={
                "tokens": "12.6k", "tok_s": 47.6, "saved": "2.7k", "saved_pct": 18.0,
            }, terminal_width=80, frame=f)
            for r in rows:
                print(r)
            print()

    for w in (80, 50, 38):
        rows = render_card("generating", progress=None, terminal_width=w)
        print(f"--- width {w} ---")
        for r in rows:
            print(r)

    rows = render_card("sending", progress=None, terminal_width=80, reduced_motion=True)
    print("--- reduced-motion sending ---")
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        sys.exit(_smoke())

    import shutil
    anim = ProcessingAnimation()
    cols = shutil.get_terminal_size().columns if hasattr(shutil, "get_terminal_size") else 80
    stages = ["preparing", "slimtoken", "sending", "generating", "tool", "completion"]
    try:
        for i, st in enumerate(stages, 1):
            anim.show(st, progress=min(100, i * 20), metrics={
                "tokens": "12.6k", "tok_s": 47.6,
            }, terminal_width=cols, stage_index=i, stage_total=5,
                      reduced_motion="--static" in sys.argv)
            time.sleep(1.0)
        anim.hide()
    except KeyboardInterrupt:
        anim.hide()
