#!/usr/bin/env python3

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

try:
    from wcwidth import wcswidth as _wcswidth
except ImportError:  # pragma: no cover - venv ships wcwidth
    _wcswidth = None







import os
import sys as _sys


def _detect_color() -> int:

    if os.environ.get("NO_COLOR"):
        return 0
    if not _sys.stdout.isatty():
        return 0
    term = os.environ.get("TERM", "")
    if term in ("dumb", ""):
        return 0
    if os.environ.get("COLORTERM") in ("truecolor", "24bit"):
        return 24
    if term.endswith("-256color"):
        return 8
    return 8


_COLOR_BITS: int = _detect_color()
_UNICODE: bool = True


def set_unicode(enabled: bool) -> None:

    global _UNICODE
    _UNICODE = bool(enabled)


def color_bits() -> int:

    return _COLOR_BITS


def is_unicode() -> bool:

    return _UNICODE


def set_title(title: str) -> None:

    if not _sys.stdout.isatty():
        return
    if os.environ.get("TERM", "") in ("dumb", ""):
        return

    safe = title.replace("\x1b", "").replace("\x07", "")
    _sys.stdout.write(f"\x1b]0;{safe}\x07")
    _sys.stdout.flush()







def _sgr(code: str) -> str:

    if _COLOR_BITS == 0:
        return ""
    return f"\x1b[{code}m"


RESET = "\x1b[0m" if _COLOR_BITS > 0 else ""
DIM = "\x1b[2m" if _COLOR_BITS > 0 else ""
BOLD = "\x1b[1m" if _COLOR_BITS > 0 else ""




GREEN_24 = "38;2;74;139;92"
CYAN_24 = "38;2;150;220;255"
PURPLE_24 = "38;2;180;140;200"
YELLOW_24 = "38;2;220;180;80"
RED_24 = "38;2;196;85;77"
DIM_GREY_24 = "38;2;136;136;136"


GREEN_8 = "32"
CYAN_8 = "36"
PURPLE_8 = "35"
YELLOW_8 = "33"
RED_8 = "31"
DIM_GREY_8 = "90"


def _pick(bit24: str, bit8: str) -> str:

    return bit24 if _COLOR_BITS >= 24 else bit8


def GREEN() -> str: return _pick(GREEN_24, GREEN_8)
def CYAN() -> str: return _pick(CYAN_24, CYAN_8)
def PURPLE() -> str: return _pick(PURPLE_24, PURPLE_8)
def YELLOW() -> str: return _pick(YELLOW_24, YELLOW_8)
def RED() -> str: return _pick(RED_24, RED_8)
def DIM_GREY() -> str: return _pick(DIM_GREY_24, DIM_GREY_8)




def _STATUS_GLYPH() -> dict:
    return {
        "ready": ("●", GREEN()),
        "warming": ("◷", YELLOW()),
        "unavailable": ("!", RED()),
        "generating": ("●", GREEN()),
        "waiting_tool": ("◷", YELLOW()),
        "preparing": ("◈", CYAN()),
        "retrying": ("◷", YELLOW()),
        "idle": ("·", DIM_GREY()),
    }


def _color(text: str, code: str) -> str:

    if _COLOR_BITS == 0:
        return text
    return f"{_sgr(code)}{text}{RESET}"


def _pair_with_glyph(text: str, glyph: str, code: str) -> str:

    if _COLOR_BITS == 0:
        return f"{glyph} {BOLD}{text}{RESET}"
    return f"{_sgr(code)}{glyph}{RESET} {BOLD}{text}{RESET}"


def _dim(text: str) -> str:
    if _COLOR_BITS == 0:
        return text
    return f"{DIM}{text}{RESET}"









_BOX_PAIRS = {
    "TL": ("+", "╭"),
    "TR": ("+", "╮"),
    "BL": ("+", "╰"),
    "BR": ("+", "╯"),
    "H":  ("-", "─"),
    "V":  ("|", "│"),
}


def B_TOP_LEFT() -> str:
    return _BOX_PAIRS["TL"][1] if _UNICODE else _BOX_PAIRS["TL"][0]


def B_TOP_RIGHT() -> str:
    return _BOX_PAIRS["TR"][1] if _UNICODE else _BOX_PAIRS["TR"][0]


def B_BOTTOM_LEFT() -> str:
    return _BOX_PAIRS["BL"][1] if _UNICODE else _BOX_PAIRS["BL"][0]


def B_BOTTOM_RIGHT() -> str:
    return _BOX_PAIRS["BR"][1] if _UNICODE else _BOX_PAIRS["BR"][0]


def B_HORIZONTAL() -> str:
    return _BOX_PAIRS["H"][1] if _UNICODE else _BOX_PAIRS["H"][0]


def B_VERTICAL() -> str:
    return _BOX_PAIRS["V"][1] if _UNICODE else _BOX_PAIRS["V"][0]




def display_width(text: str) -> int:

    if not text:
        return 0

    flat = text.replace("\t", " ").replace("\n", " ")
    if _wcswidth is None:
        return len(flat)
    try:
        w = _wcswidth(flat)
    except Exception:
        return len(flat)
    return max(0, w) if w >= 0 else len(flat)


def fit_to_cells(text: str, width: int, side: str = "left") -> str:

    if width <= 0:
        return ""

    plain = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
    if display_width(plain) <= width:
        pad = " " * (width - display_width(plain))
        return plain + pad if side == "left" else pad + plain

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

    if display_width(s) < width:
        s += " " * (width - display_width(s))
    return s


def _is_wide(ch: str) -> bool:

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




class WorkPhase(str, Enum):

    IDLE = "idle"
    PREPARING = "preparing"
    WARMING = "warming"
    GENERATING = "generating"
    WAITING_TOOL = "waiting_tool"
    RETRYING = "retrying"
    UNAVAILABLE = "unavailable"
    READY = "ready"




@dataclass(frozen=True)
class RuntimeView:

    ctx_pct: Optional[float]
    ctx_used_tokens: Optional[int]
    ctx_total_tokens: Optional[int]
    in_tps: Optional[float]
    out_tps: Optional[float]
    model_label: Optional[str]
    phase: WorkPhase

    def is_valid(self) -> bool:

        return any(
            v is not None
            for v in (self.ctx_pct, self.in_tps, self.out_tps, self.model_label)
        )


@dataclass(frozen=True)
class SlimTokenView:

    saved_pct: Optional[float]
    tokens_saved: Optional[int]
    last_in_tokens: Optional[int]
    last_out_tokens: Optional[int]
    policy: str
    ran: bool


@dataclass(frozen=True)
class MemoryView:

    available: bool
    groups_total: Optional[int]
    groups_active: Optional[int]
    category_labels: Tuple[str, ...]
    detail_hint: str = "use m for details"


@dataclass(frozen=True)
class WorkLineView:

    phase: WorkPhase
    label: str
    progress: Optional[float] = None
    retry_current: Optional[int] = None
    retry_max: Optional[int] = None
    retry_in_seconds: Optional[float] = None


@dataclass(frozen=True)
class StatusView:

    runtime: RuntimeView
    slimtoken: SlimTokenView
    memory: MemoryView
    width: int
    work: Optional[WorkLineView] = None
    shortcuts: Tuple[Tuple[str, str], ...] = (
        ("?", "help"), ("m", "memory"), ("s", "slimtoken"), ("l", "logs"),
    )




def _format_int(n: int) -> str:
    if n >= 1000:

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

    show_model = "model_name" not in drop and rt.model_label
    show_max = "used_max_ctx" not in drop
    show_rates = "token_rates" not in drop


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


    if show_rates:
        r2 = f"in {_format_tps(rt.in_tps)} · out {_format_tps(rt.out_tps)}"
    else:
        r2 = ""


    glyph, color = _STATUS_GLYPH().get(rt.phase.value, ("·", DIM_GREY()))
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


    r3_colored = f"{_sgr(color)}{glyph}{RESET} {_dim(r3)}"
    return [r1, r2, r3_colored]


def slimtoken_rows(st: SlimTokenView, drop: set) -> List[str]:

    show_last = "last_before_after" not in drop
    if not st.ran:
        r1 = "not used"
        r2 = "last —"
        r3 = st.policy or "balanced"
        return [_dim(r1), _dim(r2), _dim(r3)]

    pct = f"{st.saved_pct:.0f}%" if st.saved_pct is not None else "0%"
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

    if not mem.available:
        r1 = "memory unavailable !"
        r2 = "last good snapshot"
        r3 = mem.detail_hint or "m for details"

        return [
            f"{_sgr(RED())}!{RESET} {_dim('memory unavailable')}",
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




def panel_block(title: str, rows: List[str], width: int, accent: str) -> str:

    if width < 6:
        width = 6
    title_part = f" {title} "




    top_inner = width
    title_cells = display_width(title_part)
    if title_cells + 2 > top_inner:

        title_part = fit_to_cells(title_part, max(1, top_inner - 2), "left")
        title_cells = display_width(title_part)
    dash_count = max(0, top_inner - title_cells - 1)
    top = (
        _sgr(accent) + B_TOP_LEFT() + B_HORIZONTAL() + RESET
        + _sgr(accent) + title_part + RESET
        + _sgr(accent) + B_HORIZONTAL() * dash_count + RESET
        + _sgr(accent) + B_TOP_RIGHT() + RESET
    )
    mid: List[str] = []
    for r in rows:

        content = fit_to_cells(r, width, "left")


        mid.append(
            _sgr(accent) + B_VERTICAL() + RESET
            + content
            + _sgr(accent) + B_VERTICAL() + RESET
        )
    bot = (
        _sgr(accent) + B_BOTTOM_LEFT() + B_HORIZONTAL() * width + B_BOTTOM_RIGHT() + RESET
    )
    return "\n".join([top] + mid + [bot])




def work_line(work: WorkLineView, width: int) -> str:

    glyph, color = _STATUS_GLYPH().get(work.phase.value, ("·", DIM_GREY()))
    label = work.label
    parts = [_pair_with_glyph("", glyph, color) + " " + _dim(label)]

    if work.retry_current and work.retry_max and work.retry_in_seconds is not None:
        parts.append(_dim(
            f"retry {work.retry_current}/{work.retry_max} in "
            f"{work.retry_in_seconds:.0f}s"))
    parts.append(_dim("Esc cancel"))
    bar = ""
    if work.progress is not None:

        pct = max(0, min(100, work.progress))
        bar_chars = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        bar = f" [{bar_chars}] {pct:.0f}%"
        parts.insert(1, _sgr(color) + bar + RESET)
    elif work.phase in (WorkPhase.WARMING, WorkPhase.GENERATING,
                        WorkPhase.WAITING_TOOL, WorkPhase.RETRYING):

        bar = " [░░▒▒▓▓▒▒░░▒▒]"
        parts.insert(1, _sgr(color) + bar + RESET)
    elif work.phase == WorkPhase.PREPARING and work.progress is None:
        bar = " [░░▒▒▓▓▒▒░░▒▒]"
        parts.insert(1, _sgr(color) + bar + RESET)

    out = " · ".join(parts)

    return fit_to_cells(out, width, "left")




def footer_line(shortcuts: Sequence[Tuple[str, str]], width: int) -> str:




    items = list(shortcuts)
    for drop_key in ("s", "m", "?"):
        while True:
            rendered = _join_footer(items)
            if display_width(rendered) <= width:
                break

            new_items = [it for it in items if it[0] != drop_key]
            if len(new_items) == len(items):

                break
            items = new_items

    if not items:
        items = [("l", "logs")]
    return _join_footer(items)


def _join_footer(items: Sequence[Tuple[str, str]]) -> str:
    parts = []
    for key, label in items:
        if key in ("Esc", "r", "ctrl+c"):
            parts.append(_dim(f"{key} {label}"))
        else:
            parts.append(f"{_sgr(CYAN())}{key}{RESET} {_dim(label)}")
    return " · ".join(parts)




def _inner_widths(width: int) -> Tuple[str, int, int]:

    if width >= 96:
        layout = "3up"
        inner = min(90, max(6, (width - 8) // 3))
        return layout, inner, inner
    if width >= 64:
        layout = "2plus1"
        inner = min(90, max(6, (width - 5) // 2))
        mem_inner = min(90, max(6, width - 2))
        return layout, inner, mem_inner
    layout = "stack"
    inner = min(90, max(6, width - 2))
    return layout, inner, inner


def strip_render(view: StatusView) -> str:

    width = max(20, view.width)
    layout, top_inner, mem_inner = _inner_widths(width)
    gap = " "

    rt_drop: set = set()
    st_drop: set = set()
    mem_drop: set = set()


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

    rt_rows = runtime_rows(view.runtime, rt_drop)
    st_rows = slimtoken_rows(view.slimtoken, st_drop)
    mem_rows = memory_rows(view.memory, mem_drop)

    out_lines: List[str] = []


    if view.work is not None:
        out_lines.append(work_line(view.work, width))


    if layout == "3up":
        rt_panel = panel_block("RUNTIME", rt_rows, top_inner, CYAN()).splitlines()
        st_panel = panel_block("SLIMTOKEN", st_rows, top_inner, PURPLE()).splitlines()
        mem_panel = panel_block("MEMORY", mem_rows, top_inner, GREEN()).splitlines()
        for a, b, c in zip(rt_panel, st_panel, mem_panel):
            out_lines.append(a + gap + b + gap + c)
    elif layout == "2plus1":


        rt_panel = panel_block("RUNTIME", rt_rows, top_inner, CYAN()).splitlines()
        st_panel = panel_block("SLIMTOKEN", st_rows, top_inner, PURPLE()).splitlines()
        for a, b in zip(rt_panel, st_panel):
            out_lines.append(a + gap + b)
        mem_panel = panel_block("MEMORY", mem_rows, mem_inner, GREEN()).splitlines()
        out_lines.extend(mem_panel)
    else:

        out_lines.extend(panel_block("RUNTIME", rt_rows, top_inner, CYAN()).splitlines())
        out_lines.extend(panel_block("SLIMTOKEN", st_rows, top_inner, PURPLE()).splitlines())
        out_lines.extend(panel_block("MEMORY", mem_rows, mem_inner, GREEN()).splitlines())


    out_lines.append(footer_line(view.shortcuts, width))

    return "\n".join(out_lines)




def phase_from_proxy_signal(
    stderr_text: Optional[str],
    http_status: Optional[int] = None,
) -> WorkPhase:

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




def empty_view(width: int = 100) -> StatusView:

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