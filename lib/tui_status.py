#!/usr/bin/env python3
"""lib/tui_status.py — Codex-style 3-panel status strip for the CortexAgent TUI.

Pure-Python view-model + render layer. **No Textual imports. No I/O.**

This module owns:
  - the boxed 3-panel rendering (Runtime / SlimToken / Memory)
  - the optional 1-line active-work indicator
  - the 1-line footer with shortcuts
  - width-aware layout (3-up → 2+1 → vertical stack)
  - width-aware shrink priority
  - ANSI 24-bit color sequences paired with glyphs (never color alone)

Inputs are typed ``StatusView`` / ``RuntimeView`` / ``SlimTokenView`` /
``MemoryView`` / ``WorkLineView`` dataclasses so the TUI's ``_tick`` can
build them from live data without leaking raw memory rows / proxy JSON /
tool errors / prompts into the renderer.

Why this lives separately from ``lib/tui.py``
``:
    The strip is pure-Python and testable WITHOUT spinning up a Textual
    App. The TUI is untracked local-only and has no committed tests, so
    keeping the renderer separate lets ``tests/test_tui_status.py`` and the
    ``tests/run_smoke.py`` gate cover every layout/shrink/colour pairing
    without Textual in the loop.

Data boundary (the only fields that cross into the renderer)
``:
    RuntimeView   — ctx_pct, ctx_used_tokens, ctx_total_tokens, in_tps,
                    out_tps, model_label, phase (WorkPhase)
    SlimTokenView — saved_pct, tokens_saved, last_in_tokens, last_out_tokens,
                    policy, ran
    MemoryView    — available, groups_total, groups_active, category_labels
                    (max 2, sanitized), detail_hint
    WorkLineView  — phase, label, progress (None for indeterminate),
                    retry_current, retry_max, retry_in_seconds

Rendered glyphs (Unicode box drawing + status markers)
``:
    Borders: ╭ ╮ ╰ ╯ │ ─
    Status :  ● ready · ◷ warming · ! unavailable · ◈ working
    Bar    :  ░ ▒ ▓ █ (10-cell progress, indeterminate alternates ░▒▓▒░░)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

try:
    from wcwidth import wcswidth as _wcswidth
except ImportError:  # pragma: no cover - venv ships wcwidth
    _wcswidth = None


# ── ANSI color ───────────────────────────────────────────────────────────────
# 24-bit truecolor via OSC-equivalent SGR. Pairs every color with a glyph
# so colorblind users and forced-colors terminals still read the state.

def _sgr(code: str) -> str:
    """Wrap ``text`` `` in an ANSI SGR sequence. Caller must pair with reset."""
    return f"\x1b[{code}m"


RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"

# Palette — green / cyan / purple / yellow / red. Hex matches the constants
# already used by lib/tui.py (BG, BG2, TEXT, …). Do not duplicate numbers;
# import from lib.tui if needed.
GREEN = "38;2;74;139;92"      # ready / success
CYAN = "38;2;150;220;255"     # runtime panel accent
PURPLE = "38;2;180;140;200"   # SlimToken panel accent
YELLOW = "38;2;220;180;80"    # warming / stale
RED = "38;2;196;85;77"      # unavailable / failure
DIM_GREY = "38;2;136;136;136"  # hint rows

_STATUS_GLYPH = {
    "ready": ("●", GREEN),
    "warming": ("◷", YELLOW),
    "unavailable": ("!", RED),
    "generating": ("●", GREEN),
    "waiting_tool": ("◷", YELLOW),
    "preparing": ("◈", CYAN),
    "retrying": ("◷", YELLOW),
    "idle": ("·", DIM_GREY),
}


def _color(text: str, code: str) -> str:
    """Apply a 24-bit color to text. Caller is responsible for pairing."""
    return f"{_sgr(code)}{text}{RESET}"


def _pair_with_glyph(text: str, glyph: str, code: str) -> str:
    """Render a text segment with a colored glyph + a same-cell text label.

    The glyph always carries the color so a user with forced-colors / mono
    terminal still sees the marker. The text is bolded but stays default
    foreground for max readability.
    """
    return f"{_sgr(code)}{glyph}{RESET} {BOLD}{text}{RESET}"


def _dim(text: str) -> str:
    return f"{DIM}{text}{RESET}"


# ── Cell-aware width measurement ─────────────────────────────────────────────

def display_width(text: str) -> int:
    """Return the terminal display-cell count of ``text````.

    Falls back to ``len(text)`` if wcwidth is unavailable or returns -1
    (unknown / control chars). Newlines and tabs are normalized to 1 cell
    each so multi-line strings round-trip sensibly through the renderer.
    """
    if not text:
        return 0
    # Newlines and tabs occupy one cell each; replace before measuring.
    flat = text.replace("\t", " ").replace("\n", " ")
    if _wcswidth is None:
        return len(flat)
    try:
        w = _wcswidth(flat)
    except Exception:
        return len(flat)
    return max(0, w) if w >= 0 else len(flat)


def fit_to_cells(text: str, width: int, side: str = "left") -> str:
    """Truncate or pad ``text`` to exactly ``width`` display cells.

    ``side`` is the side that gets padding (``"left"`` / ``"right"``).
    Truncation appends ``…`` (1 cell) when the trimmed content overflowed.
    The function never returns more than ``width`` cells.
    """
    if width <= 0:
        return ""
    # Strip color for measurement; ANSI escapes have 0 cells.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
    if display_width(plain) <= width:
        pad = " " * (width - display_width(plain))
        return plain + pad if side == "left" else pad + plain
    # Truncate. Reserve 1 cell for the ellipsis.
    target = width - 1
    out = []
    used = 0
    for ch in plain:
        cw = 2 if (ord(ch) > 0x1100 and _is_wide(ch)) else 1
        if used + cw > target:
            break
        out.append(ch)
        used += cw
    s = "".join(out) + "…"
    # Pad to width (defensive — should be exact).
    if display_width(s) < width:
        s += " " * (width - display_width(s))
    return s


def _is_wide(ch: str) -> bool:
    """Rough wide-char check when wcwidth is unavailable."""
    o = ord(ch)
    return (
        0x1100 <= o <= 0x115F
        or 0x2E80 <= o <= 0x303E
        or 0x3041 <= o <= 0x33FF
        or 0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xA000 <= o <= 0xA4CF
        or 0xAC00 <= o <= 0xD7A3
        or 0xF900 <= o <= 0xFAFF
        or 0xFE30 <= o <= 0xFE4F
        or 0xFF00 <= o <= 0xFF60
        or 0xFFE0 <= o <= 0xFFE6
        or 0x20000 <= o <= 0x2FFFD
        or 0x30000 <= o <= 0x3FFFD
    )


# ── Work phase enum ──────────────────────────────────────────────────────────

class WorkPhase(str, Enum):
    """Discrete operational phase. Drives glyph + colour + verb label."""
    IDLE = "idle"
    PREPARING = "preparing"           # indeterminate progress allowed
    WARMING = "warming"               # 503 Loading model → WARMING
    GENERATING = "generating"         # indeterminate — no fake percent
    WAITING_TOOL = "waiting_tool"     # indeterminate
    RETRYING = "retrying"             # indeterminate
    UNAVAILABLE = "unavailable"       # backend down
    READY = "ready"                   # model ready, not generating


# ── View model ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuntimeView:
    """Runtime panel: context %, in/out tok/s, model state."""
    ctx_pct: Optional[float]
    ctx_used_tokens: Optional[int]
    ctx_total_tokens: Optional[int]
    in_tps: Optional[float]
    out_tps: Optional[float]
    model_label: Optional[str]
    phase: WorkPhase

    def is_valid(self) -> bool:
        """True iff at least one displayable field is non-None.

        A fully-None RuntimeView is treated as 'model —' (no fabricated
        values).
        """
        return any(
            v is not None
            for v in (self.ctx_pct, self.in_tps, self.out_tps, self.model_label)
        )


@dataclass(frozen=True)
class SlimTokenView:
    """SlimToken panel: saved %, tokens saved, last before→after, policy."""
    saved_pct: Optional[float]      # 0 is a valid value
    tokens_saved: Optional[int]
    last_in_tokens: Optional[int]
    last_out_tokens: Optional[int]
    policy: str                     # conservative / balanced / aggressive / custom
    ran: bool                       # False → renders "not used"


@dataclass(frozen=True)
class MemoryView:
    """Memory panel: groups / active / category labels.

    No raw memory content crosses this boundary — only aggregate counts
    and pre-approved category labels.
    """
    available: bool
    groups_total: Optional[int]
    groups_active: Optional[int]
    category_labels: Tuple[str, ...]
    detail_hint: str = "use m for details"


@dataclass(frozen=True)
class WorkLineView:
    """Active-work indicator (one terminal row above the panels)."""
    phase: WorkPhase
    label: str
    progress: Optional[float] = None        # None = indeterminate
    retry_current: Optional[int] = None
    retry_max: Optional[int] = None
    retry_in_seconds: Optional[float] = None


@dataclass(frozen=True)
class StatusView:
    """Top-level container. The renderer is given one of these."""
    runtime: RuntimeView
    slimtoken: SlimTokenView
    memory: MemoryView
    width: int
    work: Optional[WorkLineView] = None
    shortcuts: Tuple[Tuple[str, str], ...] = (
        ("?", "help"), ("m", "memory"), ("s", "slimtoken"), ("l", "logs"),
    )


# ── Format helpers for each row ─────────────────────────────────────────────

def _format_int(n: int) -> str:
    if n >= 1000:
        # 3100 → 3.1k · 156000 → 156k · 2700000 → 2.7M
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 10_000:
            return f"{n // 1000}k"
        return f"{n / 1000:.1f}k"
    return str(n)


def _format_tps(n: Optional[float]) -> str:
    if n is None or n <= 0:
        return "—/s"
    return f"{n:.1f}/s"


def runtime_rows(rt: RuntimeView, drop: set) -> List[str]:
    """Return the three Runtime panel content rows (no borders)."""
    show_model = "model_name" not in drop and rt.model_label
    show_max = "used_max_ctx" not in drop
    show_rates = "token_rates" not in drop

    # Row 1: percentage + (used/max when room)
    pct = f"{rt.ctx_pct:.1f}%" if rt.ctx_pct is not None else "—%"
    if rt.ctx_used_tokens is not None:
        if show_max and rt.ctx_total_tokens:
            r1 = f"ctx {pct} · {_format_int(rt.ctx_used_tokens)}/{_format_int(rt.ctx_total_tokens)}"
        elif rt.ctx_used_tokens:
            r1 = f"ctx {pct} · {_format_int(rt.ctx_used_tokens)}"
        else:
            r1 = f"ctx {pct}"
    else:
        r1 = f"ctx {pct}"

    # Row 2: in/out tok/s
    if show_rates:
        r2 = f"in {_format_tps(rt.in_tps)} · out {_format_tps(rt.out_tps)}"
    else:
        r2 = ""

    # Row 3: model + phase
    glyph, color = _STATUS_GLYPH.get(rt.phase.value, ("·", DIM_GREY))
    state_word = {
        WorkPhase.READY: "model ready",
        WorkPhase.WARMING: "model warming up",
        WorkPhase.UNAVAILABLE: "model unavailable",
        WorkPhase.GENERATING: "generating",
        WorkPhase.WAITING_TOOL: "waiting for tool",
        WorkPhase.PREPARING: "preparing",
        WorkPhase.RETRYING: "retrying",
        WorkPhase.IDLE: "model —",
    }.get(rt.phase, "model —")
    if show_model:
        r3 = f"{rt.model_label} {state_word}"
    else:
        r3 = state_word

    # Color the phase glyph for row 3
    r3_colored = f"{_sgr(color)}{glyph}{RESET} {_dim(r3)}"
    return [r1, r2, r3_colored]


def slimtoken_rows(st: SlimTokenView, drop: set) -> List[str]:
    """Return the three SlimToken panel content rows (no borders)."""
    show_last = "last_before_after" not in drop
    if not st.ran:
        r1 = "not used"
        r2 = "last —"
        r3 = st.policy or "balanced"
        return [_dim(r1), _dim(r2), _dim(r3)]

    pct = f"{st.saved_pct:.0f}%" if st.saved_pct is not None else "0%"
    saved = _format_int(st.tin) if hasattr(st, "tin") else _format_int(st.tokens_saved or 0)
    saved = _format_int(st.tokens_saved or 0)
    r1 = f"saved {pct} · {saved} tok"

    if show_last and st.last_in_tokens and st.last_out_tokens:
        r2 = f"last {_format_int(st.last_in_tokens)} → {_format_int(st.last_out_tokens)}"
    elif show_last:
        r2 = "last —"
    else:
        r2 = ""

    r3 = st.policy or "balanced"
    return [r1, r2, r3]


def memory_rows(mem: MemoryView, drop: set) -> List[str]:
    """Return the three Memory panel content rows (no borders)."""
    if not mem.available:
        r1 = "memory unavailable !"
        r2 = "last good snapshot"
        r3 = mem.detail_hint or "m for details"
        # The trailing ! is itself the red signal; we still color the word.
        return [
            f"{_sgr(RED)}!{RESET} {_dim('memory unavailable')}",
            _dim(r2),
            _dim(r3),
        ]

    show_labels = "category_labels" not in drop
    total = mem.groups_total if mem.groups_total is not None else "—"
    active = mem.groups_active if mem.groups_active is not None else "—"
    r1 = f"{total} groups · {active} active"

    if show_labels and mem.category_labels:
        labels = " · ".join(mem.category_labels[:2])
        r2 = labels
    elif not show_labels:
        r2 = ""
    elif mem.groups_total and not mem.category_labels:
        r2 = "no memory used this turn"
    else:
        r2 = "—"

    r3 = mem.detail_hint or "use m for details"
    return [r1, _dim(r2), _dim(r3)]


# ── Panel renderer (borders + content) ───────────────────────────────────────

def panel_block(title: str, rows: List[str], width: int, accent: str) -> str:
    """Render one bordered panel as a multi-line string.

    ``rows`` is the list of 3 content strings (already cell-fit if needed).
    ``width`` is the *inner* width; the output adds 2 cells of borders.
    Returns 5 lines total: top border · 3 content · bottom border.
    """
    if width < 6:
        width = 6
    title_part = f" {title} "
    # Top border: ╭─ TITLE ─…─╮
    top_inner = width
    title_cells = display_width(title_part)
    if title_cells + 2 > top_inner:
        # Title too long — truncate.
        title_part = fit_to_cells(title_part, top_inner - 2, "left")
        title_cells = display_width(title_part)
    dash_count = max(0, top_inner - title_cells - 0)
    top = (
        _sgr(accent) + "╭─" + RESET
        + _sgr(accent) + title_part + RESET
        + _sgr(accent) + "─" * dash_count + RESET
        + _sgr(accent) + "╮" + RESET
    )
    mid: List[str] = []
    for r in rows:
        # Each content row gets │ … │ with the content fit/padded to width.
        content = fit_to_cells(r, width, "left")
        # The leading/trailing border glyphs use the accent color so the
        # whole panel reads as a single bordered region.
        mid.append(
            _sgr(accent) + "│" + RESET
            + content
            + _sgr(accent) + "│" + RESET
        )
    bot = (
        _sgr(accent) + "╰" + "─" * width + "╯" + RESET
    )
    return "\n".join([top] + mid + [bot])


# ── Active-work line renderer ────────────────────────────────────────────────

def work_line(work: WorkLineView, width: int) -> str:
    """Render the single-row active-work indicator.

    Indeterminate phases (WARMING, GENERATING, WAITING_TOOL, RETRYING) get
    a Unicode block bar with **no** fake percent. Determinate phases
    (PREPARING with a measured progress) get a percent + bar.
    """
    glyph, color = _STATUS_GLYPH.get(work.phase.value, ("·", DIM_GREY))
    label = work.label
    parts = [_pair_with_glyph("", glyph, color) + " " + _dim(label)]
    # Retry block
    if work.retry_current and work.retry_max and work.retry_in_seconds is not None:
        parts.append(_dim(
            f"retry {work.retry_current}/{work.retry_max} in "
            f"{work.retry_in_seconds:.0f}s"))
    parts.append(_dim("Esc cancel"))
    bar = ""
    if work.progress is not None:
        # Determinate
        pct = max(0, min(100, work.progress))
        bar_chars = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        bar = f" [{bar_chars}] {pct:.0f}%"
        parts.insert(1, _sgr(color) + bar + RESET)
    elif work.phase in (WorkPhase.WARMING, WorkPhase.GENERATING,
                        WorkPhase.WAITING_TOOL, WorkPhase.RETRYING):
        # Indeterminate — alternating blocks. No percent.
        bar = " [░░▒▒▓▓▒▒░░▒▒]"
        parts.insert(1, _sgr(color) + bar + RESET)
    elif work.phase == WorkPhase.PREPARING and work.progress is None:
        bar = " [░░▒▒▓▓▒▒░░▒▒]"
        parts.insert(1, _sgr(color) + bar + RESET)

    out = " · ".join(parts)
    # Fit to width (defensive — usually already fits).
    return fit_to_cells(out, width, "left")


# ── Footer renderer ──────────────────────────────────────────────────────────

def footer_line(shortcuts: Sequence[Tuple[str, str]], width: int) -> str:
    """Render the unbordered footer with width-aware shortcut shrink.

    Drop order (per spec):
        1. SlimToken shortcut
        2. Memory shortcut
        3. Help shortcut
        4. Keep logs and cancel/retry (last)
    """
    # Always keep logs (and Esc cancel / r retry if present) — they aren't in
    # the drop list.
    keep = ("l",)
    keep_verbs = ("logs", "cancel", "retry")
    # Build the full list, then drop until it fits.
    items = list(shortcuts)
    for drop_key in ("s", "m", "?"):
        while True:
            rendered = _join_footer(items)
            if display_width(rendered) <= width:
                break
            # Drop the first item whose key matches drop_key.
            new_items = [it for it in items if it[0] != drop_key]
            if len(new_items) == len(items):
                # Already gone; can't drop more of this key.
                break
            items = new_items
    # Always retain at least one shortcut.
    if not items:
        items = [("l", "logs")]
    return _join_footer(items)


def _join_footer(items: Sequence[Tuple[str, str]]) -> str:
    parts = []
    for key, label in items:
        if key in ("Esc", "r", "ctrl+c"):
            parts.append(_dim(f"{key} {label}"))
        else:
            parts.append(f"{_sgr(CYAN)}{key}{RESET} {_dim(label)}")
    return " · ".join(parts)


# ── Top-level strip renderer ─────────────────────────────────────────────────

def strip_render(view: StatusView) -> str:
    """Render the full bottom region: optional work line + 3-panel strip + footer.

    Layout selection by terminal width:
      >= 96  : 3-up (Runtime | SlimToken | Memory side by side)
      >= 64  : 2+1 (Runtime | SlimToken on top, Memory full-width below)
      else   : vertical stack (Runtime, then SlimToken, then Memory)

    Returns a multi-line string ready to ``Static.update()``.
    """
    width = max(20, view.width)
    panel_w = max(48, min(90, width - 2))
    gap = " "

    rt_drop: set = set()
    st_drop: set = set()
    mem_drop: set = set()

    # Aggressive shrink: as width shrinks past 96, start dropping fields.
    if width < 96:
        rt_drop.add("model_name")
    if width < 80:
        st_drop.add("last_before_after")
    if width < 72:
        mem_drop.add("category_labels")
    if width < 64:
        rt_drop.add("used_max_ctx")
    if width < 56:
        rt_drop.add("token_rates")

    # Determine layout.
    if width >= 96:
        layout = "3up"
    elif width >= 64:
        layout = "2plus1"
    else:
        layout = "stack"

    rt_rows = runtime_rows(view.runtime, rt_drop)
    st_rows = slimtoken_rows(view.slimtoken, st_drop)
    mem_rows = memory_rows(view.memory, mem_drop)

    out_lines: List[str] = []

    # Active-work line.
    if view.work is not None:
        out_lines.append(work_line(view.work, width))
    # Top spacer removed by spec rule: no blank spacer lines.

    if layout == "3up":
        rt_panel = panel_block("RUNTIME", rt_rows, panel_w, CYAN).splitlines()
        st_panel = panel_block("SLIMTOKEN", st_rows, panel_w, PURPLE).splitlines()
        mem_panel = panel_block("MEMORY", mem_rows, panel_w, GREEN).splitlines()
        for a, b, c in zip(rt_panel, st_panel, mem_panel):
            out_lines.append(a + gap + b + gap + c)
    elif layout == "2plus1":
        # Runtime + SlimToken side-by-side on the top three rows; Memory
        # full-width (panel_w + 2 wide on each side of the terminal) below.
        # Each top-panel is panel_w wide; the bottom memory panel matches
        # the combined width (panel_w + gap + panel_w) using the same
        # panel_w but stretched.
        rt_panel = panel_block("RUNTIME", rt_rows, panel_w, CYAN).splitlines()
        st_panel = panel_block("SLIMTOKEN", st_rows, panel_w, PURPLE).splitlines()
        for a, b in zip(rt_panel, st_panel):
            out_lines.append(a + gap + b)
        mem_w = min(90, width - 2)
        mem_panel = panel_block("MEMORY", mem_rows, mem_w, GREEN).splitlines()
        out_lines.extend(mem_panel)
    else:
        # Stack — each panel on its own row band.
        out_lines.extend(panel_block("RUNTIME", rt_rows, panel_w, CYAN).splitlines())
        out_lines.extend(panel_block("SLIMTOKEN", st_rows, panel_w, PURPLE).splitlines())
        out_lines.extend(panel_block("MEMORY", mem_rows, panel_w, GREEN).splitlines())

    # Footer (unbordered, one line).
    out_lines.append(footer_line(view.shortcuts, width))

    return "\n".join(out_lines)


# ── 503 → WARMING mapping ────────────────────────────────────────────────────

def phase_from_proxy_signal(
    stderr_text: Optional[str],
    http_status: Optional[int] = None,
) -> WorkPhase:
    """Map a (stderr_text, http_status) pair from the grammar proxy into a phase.

    Per spec: HTTP 503 with backend message ``Loading model`` maps to
    ``WARMING``. Any other 503 / connection error maps to ``UNAVAILABLE``.
    Cancelled → IDLE (the TUI handles that via TurnPanel.finished_cancelled).
    """
    msg = (stderr_text or "").lower()
    if http_status == 503 and "loading model" in msg:
        return WorkPhase.WARMING
    if http_status == 503 or "503" in msg:
        return WorkPhase.UNAVAILABLE
    if "connection" in msg or "terminated" in msg:
        return WorkPhase.UNAVAILABLE
    if "cancel" in msg:
        return WorkPhase.IDLE
    return WorkPhase.IDLE


# ── Public convenience: a sane empty StatusView ──────────────────────────────

def empty_view(width: int = 100) -> StatusView:
    """A status view with everything unknown — used at boot / first tick."""
    return StatusView(
        runtime=RuntimeView(None, None, None, None, None, None, WorkPhase.IDLE),
        slimtoken=SlimTokenView(0, 0, None, None, "balanced", False),
        memory=MemoryView(False, None, None, ()),
        width=width,
    )


__all__ = [
    "display_width",
    "fit_to_cells",
    "panel_block",
    "strip_render",
    "work_line",
    "footer_line",
    "phase_from_proxy_signal",
    "WorkPhase",
    "RuntimeView",
    "SlimTokenView",
    "MemoryView",
    "WorkLineView",
    "StatusView",
    "empty_view",
]