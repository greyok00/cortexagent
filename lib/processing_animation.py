#!/usr/bin/env python3
"""processing_animation — CortexAgent "Cortex processing core" active-work card.

Renders a fixed-height (5-7 row) card directly above the input box while a
request is being processed, showing the current stage, a real progress
percentage, and live metrics (tokens, tok/s, minify savings). Replaces the
small status card **only while an active request exists**.

Per docs/ANIMATION-SPEC.md:
  - CortexAgent-specific visual identity (core + orbiting nodes + packets)
  - 5-7 rows, fixed reserved region, in-place update (never appends frames)
  - One distinct animation per high-level stage (4-frame cycles, ~180 ms)
  - Real percentages only; indeterminate for generation / unknown waits
  - Reduced-motion → static stage illustration (frame 0)
  - Narrow terminals → compact one-line (40-54 cols) / minimal (<40 cols)
  - Never fakes a determinate percentage
"""
from __future__ import annotations

import sys
import time
from typing import List, Optional

# ── Stage definitions ────────────────────────────────────────────────────────
# Each stage: a list of 2-row frames (the visual animation), a user-facing
# status sentence, a label for the progress row, and a short label for the
# compact one-line mode. Static stages (completion / error) hold one frame.
# All visuals are CortexAgent-specific (core + orbit + packets).

_STAGES: dict[str, dict] = {
    "preparing": {
        # Orbiting context nodes around the core (4 frames).
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
        # Wide context entering left, compressed leaving right (contracting).
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
        # Packets converging toward the model core.
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
        # Output stream emerging from the core (expanding waveform).
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
        # Signal dots traveling between the core and a tool marker.
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
        # One-shot success burst (static, shown briefly then removed).
        "frames": [
            ["                ✦  ✓  ✦", "             Request complete"],
        ],
        "status": "Request complete.",
        "label": "Complete",
        "short": "Request complete",
    },
    "error": {
        # Static (non-flashing) alert.
        "frames": [
            ["                !  ◈  !", "          Request needs attention"],
        ],
        "status": "The model connection was interrupted before completion.",
        "label": "Needs attention",
        "short": "Needs attention",
    },
}

# Stage order for the "N of M stages" counter.
_STAGE_ORDER = ["preparing", "slimtoken", "sending", "generating", "tool"]

_FRAME_INTERVAL_MS = 180.0  # per spec: 150-250 ms, no more than ~3 flashes/s


def _bar(pct: Optional[float], width: int) -> str:
    """Render a determinate progress bar, or an indeterminate pulse.

    ``pct`` is 0-100 or None (indeterminate). Never fakes a percentage: when
    ``pct`` is None the bar is a moving block and no number is shown.
    """
    if pct is None:
        # Indeterminate: a block sweeping left→right.
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
    """Truncate to ``width`` display columns without breaking ANSI."""
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def _pct_str(progress: Optional[float]) -> str:
    """A percentage string only when a determinate value exists."""
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
    """Compose the Cortex processing-core card as a list of terminal rows.

    Args:
        stage: one of ``_STAGES`` keys.
        progress: 0-100 determinate, or None for indeterminate.
        metrics: dict with optional ``tokens``, ``tok_s``, ``saved``, ``saved_pct``.
        terminal_width: current terminal width (for scaling / narrow fallback).
        reduced_motion: render a static illustration (no cycling frames).
        stage_index: 1-based current stage position (for "N of M").
        stage_total: total stages in the pipeline.
        frame: which frame of the stage animation to draw (0-based).
        frame_interval_ms: frame duration (used only to pick a default frame).

    Returns:
        List of rows (no trailing newlines). Empty list if stage unknown.
    """
    if stage not in _STAGES:
        return []
    spec = _STAGES[stage]
    metrics = metrics or {}

    # Narrow-terminal fallbacks (spec layout rules).
    if terminal_width < 40:
        # Minimal one line: `◈ Working · 48%` (or `◈ Working` indeterminate).
        return [f"◈ {spec['short']}{_pct_str(progress)}"]
    if terminal_width <= 54:
        # 40-54 cols: simplified one-line animation with the stage visual.
        short = spec["short"]
        return [f"◈  ◌ ◉ ◌  {short}{_pct_str(progress)}"]

    # Full card. Cap panel at 72, floor at 40, never exceed terminal.
    panel = min(72, terminal_width - 2)
    panel = max(40, panel)
    inner = panel - 2  # inside the borders

    # Pick the animation frame. Static stages and reduced-motion → frame 0.
    frames = spec["frames"]
    if reduced_motion or len(frames) == 1:
        frame = 0
    else:
        frame = frame % len(frames)
    visual = frames[frame]

    # ── Assemble rows ──
    rows: List[str] = []

    # Top border with title.
    title = " CORTEX / ACTIVE "
    rows.append("╭─" + title + "─" * max(0, inner - len(title)) + "╮")

    # Stage visual (2 rows), centered, truncated to inner width.
    for vline in visual:
        v = _truncate(vline, inner)
        pad = max(0, (inner - len(v)) // 2)
        rows.append("│" + " " * pad + v + " " * (inner - pad - len(v)) + "│")

    # Status sentence.
    status = _truncate(spec["status"], inner)
    rows.append("│" + status + " " * (inner - len(status)) + "│")

    # Progress row: bar + % + stage label.
    bar_width = max(8, inner - len(spec["label"]) - 4)
    bar = _bar(progress, bar_width)
    prog_row = _truncate(f"{bar}  {spec['label']}", inner)
    rows.append("│" + prog_row + " " * (inner - len(prog_row)) + "│")

    # Metrics / action row.
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

    # Bottom border.
    rows.append("╰" + "─" * inner + "╯")

    return rows


def pick_frame(stage: str, reduced_motion: bool = False,
               frame_interval_ms: float = _FRAME_INTERVAL_MS) -> int:
    """Choose the animation frame to draw based on elapsed time.

    Static stages (single frame) and reduced-motion always return 0. Animated
    stages cycle deterministically with the wall clock so callers never need
    their own busy loop — the existing render tick just calls this.
    """
    spec = _STAGES.get(stage)
    if not spec or reduced_motion:
        return 0
    frames = spec["frames"]
    if len(frames) <= 1:
        return 0
    interval_s = max(0.05, frame_interval_ms / 1000.0)
    return int(time.monotonic() / interval_s) % len(frames)


class ProcessingAnimation:
    """In-place renderer for the Cortex processing-core card.

    Usage:
        anim = ProcessingAnimation(stream=sys.stderr)
        anim.show("generating", progress=None, metrics={"tok_s": 47.6})
        ...
        anim.hide()

    ``show`` clears the previously-rendered card (cursor-up + erase per row)
    before drawing the new one, so the card updates in place and never appends
    frames to the transcript. When the stream is not a TTY, rows are printed
    fresh each call instead.
    """

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
        # Clear the previous card (cursor-up + erase-line per row).
        for _ in self._last_rows:
            self.stream.write("\x1b[1A\x1b[2K")
        # Draw the new card.
        for row in rows:
            self.stream.write(row + "\n")
        self.stream.flush()
        self._last_rows = rows

    def hide(self) -> None:
        """Clear the card and return to normal input layout."""
        for _ in self._last_rows:
            self.stream.write("\x1b[1A\x1b[2K")
        self.stream.flush()
        self._last_rows = []


# ── Phase → stage mapping (for the TUI's WorkPhase enum) ────────────────────

def stage_from_workphase(phase: str) -> str:
    """Map a ``lib.tui_status.WorkPhase`` value to an animation stage.

    ``phase`` is the string form of WorkPhase (idle / preparing / warming /
    generating / waiting_tool / retrying / unavailable / ready). Unknown or
    idle values map to ``preparing`` (harmless static-ish fallback).
    """
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


# ── Smoke-test entry point ──────────────────────────────────────────────────

def _smoke() -> int:
    """Render every stage to stdout and exit 0. Used by the smoke gate."""
    for stage in _STAGES:
        for f in range(min(2, len(_STAGES[stage]["frames"]))):
            rows = render_card(stage, progress=48.0, metrics={
                "tokens": "12.6k", "tok_s": 47.6, "saved": "2.7k", "saved_pct": 18.0,
            }, terminal_width=80, frame=f)
            for r in rows:
                print(r)
            print()
    # Indeterminate (generation) + narrow-terminal fallbacks.
    for w in (80, 50, 38):
        rows = render_card("generating", progress=None, terminal_width=w)
        print(f"--- width {w} ---")
        for r in rows:
            print(r)
    # Reduced-motion: every stage renders static frame 0 (single-frame).
    rows = render_card("sending", progress=None, terminal_width=80, reduced_motion=True)
    print("--- reduced-motion sending ---")
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        sys.exit(_smoke())
    # Manual demo: cycle stages for ~7s (in-place on stderr, needs a TTY).
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
