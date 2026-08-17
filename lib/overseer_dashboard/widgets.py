"""lib/overseer_dashboard/widgets.py — reusable Tk widgets for the Overseer UI.

High-contrast dark graphical widgets: badges, bars, metric rows, tooltips,
section panels, and pipeline stage chips. Everything pairs color with a label
and glyph — never color alone.

2026-08-16 redesign:
  - Bigger base fonts (13/11/15) so the dashboard reads cleanly on 4K.
  - ``TogglePill`` replaces bare checkboxes with always-visible state.
  - ``PresetPillGroup`` for radio-style preset selection.
  - ``PipelineNode`` + ``PathwayStrip`` for the bottom-of-window path view.
  - ``devil_mascot_widget()`` renders the brand devil in the header.
  - ``init_ttk_theme()`` configures ``ttk.Style`` once at boot so the
    OptionMenu / Combobox widgets match the rest of the dashboard.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, List, Optional, Tuple

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from lib.banner import DEVIL_LINES  # noqa: E402

# ── Palette (spec: green/cyan/yellow/red/purple) ───────────────────────────
BG = "#0d0d12"
PANEL = "#15151c"
PANEL2 = "#1a1a24"
PANEL_HOVER = "#22222e"
BORDER = "#2a2a36"
FG = "#e8e8f0"
DIM = "#9a9aac"
GREEN = "#5ec47a"
CYAN = "#4fd6c8"
BLUE = "#5aa8e0"
YELLOW = "#e0a23a"
RED = "#d65a5a"
RED_BRAND = "#e0584a"   # the only brand red — devil + accent
PURPLE = "#b07ae0"
GOLD = "#c9a84c"

# ── Fonts ──────────────────────────────────────────────────────────────────
# 2026-08-16: bumped base sizes again. The user is on 3840×2400 with 1.0×
# scale (HiDPI now uses scaling for widget metrics, not font-size inflation),
# so the base sizes need to be readable on a 4K screen at native pixels.
# The ``_f(size, scale)`` helper multiplies these by ``self._scale``, so on
# a 1.0× display you get the base size; on a 2.0× display you get 2× bigger.
FONT = ("DejaVu Sans", 17)
FONT_SM = ("DejaVu Sans", 14)
FONT_BOLD = ("DejaVu Sans", 17, "bold")
FONT_TITLE = ("DejaVu Sans", 22, "bold")
FONT_TINY = ("DejaVu Sans", 13)
FONT_MONO = ("DejaVu Sans Mono", 16)
FONT_DEVIL = ("DejaVu Sans Mono", 14, "bold")

STATE_COLOR = {
    "complete": GREEN,
    "active": CYAN,
    "queued": DIM,
    "skipped": DIM,
    "failed": RED,
    "changed": YELLOW,
}
STATE_GLYPH = {
    "complete": "✓",
    "active": "◷",
    "queued": "○",
    "skipped": "—",
    "failed": "✕",
    "changed": "◆",
}


# ── ttk theme (call once at boot) ─────────────────────────────────────────
_TTK_THEME_READY = False


def init_ttk_theme(root: Optional[tk.Misc] = None) -> None:
    """Configure ``ttk.Style`` so Combobox / OptionMenu match the dark palette.

    Idempotent. Call once after the Tk root is created.
    """
    global _TTK_THEME_READY
    if _TTK_THEME_READY:
        return
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    base = {
        "fieldbackground": PANEL2,
        "background": PANEL2,
        "foreground": FG,
        "arrowcolor": CYAN,
        "bordercolor": BORDER,
        "lightcolor": PANEL2,
        "darkcolor": PANEL2,
    }
    style.configure("TCombobox", **base, padding=4)
    style.configure("TOptionMenu", **base, padding=4)
    style.configure("TMenubutton", **base, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", PANEL2), ("focus", PANEL2)],
              foreground=[("readonly", FG), ("focus", FG)],
              selectbackground=[("readonly", PANEL2)],
              selectforeground=[("readonly", FG)])
    style.configure("TButton", background=PANEL2, foreground=FG,
                    bordercolor=BORDER, focuscolor=BORDER, padding=6)
    style.configure("TLabelframe", background=PANEL, foreground=CYAN,
                    bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=PANEL, foreground=CYAN,
                    font=FONT_BOLD)
    style.configure("TNotebook", background=PANEL, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=PANEL2, foreground=FG,
                    padding=(12, 6), font=FONT_BOLD)
    style.map("TNotebook.Tab",
              background=[("selected", PANEL), ("active", PANEL_HOVER)],
              foreground=[("selected", CYAN), ("active", CYAN)])
    _TTK_THEME_READY = True


# ── Helpers ───────────────────────────────────────────────────────────────
def _f(size: int, scale: float = 1.0, bold: bool = False,
       mono: bool = False) -> Tuple[str, ...]:
    """Build a font tuple sized by ``size`` and DPI-scaled by ``scale``."""
    family = "DejaVu Sans Mono" if mono else "DejaVu Sans"
    pt = max(8, int(round(size * scale)))
    if bold:
        return (family, pt, "bold")
    return (family, pt)


def _hover_bg(widget: tk.Widget, normal: str, hover: str = PANEL_HOVER) -> None:
    """Wire <Enter>/<Leave> to swap background. Walks all child labels."""
    targets: List[tk.Widget] = [widget]

    def _walk(w: tk.Widget) -> None:
        try:
            for c in w.winfo_children():
                targets.append(c)
                _walk(c)
        except Exception:
            pass

    _walk(widget)

    def _on_enter(_e=None):
        for w in targets:
            try:
                w.configure(bg=hover)
            except Exception:
                pass

    def _on_leave(_e=None):
        for w in targets:
            try:
                w.configure(bg=normal)
            except Exception:
                pass

    for w in targets:
        try:
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)
        except Exception:
            pass


# ── Tooltip ───────────────────────────────────────────────────────────────
class Tooltip:
    """Hover tooltip for a widget. Explains advanced telemetry/controls."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _e=None) -> None:
        if not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + 16
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(self._tip, text=self.text, bg="#20202c", fg=FG,
                       font=FONT_SM, justify="left", padx=10, pady=8,
                       wraplength=320, bd=1, relief="solid",
                       highlightthickness=1, highlightbackground=BORDER)
        lbl.pack()

    def _hide(self, _e=None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


# ── Primitives ────────────────────────────────────────────────────────────
def badge(parent: tk.Widget, text: str, color: str, bg: str = PANEL,
          font: Any = FONT_BOLD) -> tk.Label:
    """A colored status badge (glyph + text)."""
    return tk.Label(parent, text=text, bg=bg, fg=color, font=font,
                    padx=8, pady=3, bd=1, relief="solid",
                    highlightthickness=1, highlightbackground=color)


def section(parent: tk.Widget, title: str, color: str = BLUE,
            padx: int = 12, pady: int = 8, scale: float = 1.0) -> Tuple[tk.Frame, tk.Frame]:
    """A titled panel with a colored header rule."""
    frame = tk.Frame(parent, bg=PANEL, bd=1, relief="solid",
                     highlightthickness=1, highlightbackground=BORDER)
    head = tk.Frame(frame, bg=PANEL)
    head.pack(fill="x", padx=padx, pady=(pady, 0))
    tk.Label(head, text=title, bg=PANEL, fg=color,
             font=_f(14, scale, bold=True), anchor="w").pack(side="left")
    # 3-px beveled divider: 2px color + 1px PANEL highlight below.
    tk.Frame(head, bg=color, height=2).pack(fill="x", pady=(4, 0))
    tk.Frame(head, bg=PANEL, height=1).pack(fill="x")
    body = tk.Frame(frame, bg=PANEL)
    body.pack(fill="x", padx=padx, pady=(6, pady))
    return frame, body


def metric_row(parent: tk.Widget, label: str, value: str, color: str = FG,
               value_font: Any = FONT_BOLD, tooltip: str = "",
               scale: float = 1.0,
               ) -> tk.Frame:
    """A label/value row. Value uses '—' for unavailable, never a fake zero."""
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=2)
    tk.Label(row, text=label, bg=PANEL, fg=DIM, font=_f(11, scale),
             anchor="w").pack(side="left")
    val = tk.Label(row, text=value, bg=PANEL, fg=color,
                   font=_f(13, scale, bold=True), anchor="e")
    val.pack(side="right")
    if tooltip:
        Tooltip(row, tooltip)
    return row


# ── Bar ───────────────────────────────────────────────────────────────────
class Bar(tk.Frame):
    """A labeled progress bar. Never a fake bar — value may be None."""

    def __init__(self, parent: tk.Widget, label: str, color: str = CYAN,
                 width: int = 220, height: int = 14, scale: float = 1.0) -> None:
        super().__init__(parent, bg=PANEL)
        self.color = color
        self.width = width
        self.height = height
        self._label = tk.Label(self, text=label, bg=PANEL, fg=DIM,
                              font=_f(11, scale), anchor="w")
        self._label.pack(fill="x")
        self._canvas = tk.Canvas(self, width=width, height=height, bg=PANEL2,
                                 highlightthickness=0, bd=0)
        self._canvas.pack(fill="x", pady=(2, 0))
        self._text = tk.Label(self, text="—", bg=PANEL, fg=FG,
                              font=_f(11, scale), anchor="e")
        self._text.pack(fill="x")

    def set(self, value: Optional[float], max_value: Optional[float],
            text: Optional[str] = None) -> None:
        self._canvas.delete("all")
        if value is None or not max_value:
            self._text.config(text=text or "—", fg=DIM)
            return
        frac = max(0.0, min(1.0, value / max_value))
        w = max(1, int(self.width * frac))
        self._canvas.create_rectangle(0, 0, w, self.height,
                                      fill=self.color, outline="")
        self._canvas.create_rectangle(w, 0, self.width, self.height,
                                      fill=PANEL2, outline="")
        self._text.config(text=text or f"{value:g} / {max_value:g}", fg=FG)


# ── StageChip (existing — kept for backward compat) ──────────────────────
class StageChip(tk.Frame):
    """One pipeline stage chip: glyph + name + state color. Clickable."""

    def __init__(self, parent: tk.Widget, name: str,
                 on_click: Optional[Callable] = None, width: int = 90,
                 scale: float = 1.0) -> None:
        super().__init__(parent, bg=PANEL, bd=1, relief="solid",
                         highlightthickness=1, highlightbackground=BORDER)
        self.name = name
        self._state = "queued"
        self._glyph = tk.Label(self, text="○", bg=PANEL, fg=DIM,
                               font=_f(13, scale, bold=True))
        self._glyph.pack(side="left", padx=(6, 4), pady=4)
        self._lbl = tk.Label(self, text=name, bg=PANEL, fg=DIM,
                             font=_f(11, scale))
        self._lbl.pack(side="left", padx=(0, 6), pady=4)
        if on_click:
            for w in (self, self._glyph, self._lbl):
                w.bind("<Button-1>", lambda _e: on_click(self.name))
                w.configure(cursor="hand2")

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        color = STATE_COLOR.get(state, DIM)
        glyph = STATE_GLYPH.get(state, "○")
        self._glyph.config(text=glyph, fg=color)
        self._lbl.config(fg=color)
        self.configure(highlightbackground=color, bg=PANEL)
        if detail:
            Tooltip(self, f"{self.name}: {detail}")


# ── TogglePill ───────────────────────────────────────────────────────────
class TogglePill(tk.Frame):
    """A binary on/off control that ALWAYS shows its state with color + glyph.

    Replaces bare tk.Checkbutton (which renders as an unreadable white square
    in dark themes). Click anywhere on the pill to flip state.
    """

    ON_BG = "#1f3326"
    OFF_BG = "#1a1a24"
    ON_BORDER = GREEN
    OFF_BORDER = DIM

    def __init__(self, parent: tk.Widget, text: str = "",
                 on_text: str = "ON", off_text: str = "OFF",
                 on_color: str = GREEN, off_color: str = DIM,
                 variable: Optional[tk.BooleanVar] = None,
                 command: Optional[Callable[[bool], None]] = None,
                 on_value=None, off_value=None,
                 tooltip: str = "", scale: float = 1.0) -> None:
        super().__init__(parent, bg=self.OFF_BG, bd=1, relief="solid",
                         highlightthickness=2,
                         highlightbackground=self.OFF_BORDER)
        self._on_color = on_color
        self._off_color = off_color
        self._on_text = on_text
        self._off_text = off_text
        self._command = command
        self._on_value = on_value
        self._off_value = off_value
        self._scale = scale
        self._var = variable if variable is not None else tk.BooleanVar(value=False)
        self._dot = tk.Label(self, text="○", bg=self.OFF_BG,
                             fg=self._off_color,
                             font=_f(12, scale, bold=True))
        self._dot.pack(side="left", padx=(8, 2), pady=4)
        self._label = tk.Label(self, text=text or off_text, bg=self.OFF_BG,
                               fg=self._off_color,
                               font=_f(11, scale, bold=True))
        self._label.pack(side="left", padx=(0, 4), pady=4)
        self._state_lbl = tk.Label(self, text=self._off_text, bg=self.OFF_BG,
                                   fg=self._off_color, font=_f(10, scale))
        self._state_lbl.pack(side="left", padx=(2, 8), pady=4)
        if tooltip:
            Tooltip(self, tooltip)
        self._render()
        for w in (self, self._dot, self._label, self._state_lbl):
            w.bind("<Button-1>", self._toggle)
            w.configure(cursor="hand2")

    def _toggle(self, _e=None) -> None:
        self._var.set(not self._var.get())
        self._render()
        if self._command is not None:
            self._command(self.get_value())

    def _render(self) -> None:
        on = bool(self._var.get())
        bg = self.ON_BG if on else self.OFF_BG
        border = self.ON_BORDER if on else self.OFF_BORDER
        color = self._on_color if on else self._off_color
        glyph = "●" if on else "○"
        text = self._on_text if on else self._off_text
        for w in (self, self._dot, self._label, self._state_lbl):
            w.configure(bg=bg)
        self.configure(highlightbackground=border)
        self._dot.configure(fg=color, text=glyph)
        self._state_lbl.configure(fg=color, text=text)

    def get(self) -> bool:
        return bool(self._var.get())

    def get_value(self):
        """Return ``on_value`` if on, ``off_value`` otherwise (defaults to bool)."""
        return self._on_value if self.get() else self._off_value

    def set(self, value: bool) -> None:
        self._var.set(bool(value))
        self._render()


# ── PresetPillGroup ──────────────────────────────────────────────────────
class PresetPillGroup(tk.Frame):
    """A row of mutually-exclusive pills. Exactly one is selected at a time.

    Selecting a preset calls ``on_select(preset_key)``. The caller is
    responsible for rewriting the underlying settings to match.

    Visual model: pills are TogglePills with empty state — clicking one
    lights it up in its brand color and dims the others.
    """

    PRESETS = (
        ("aggressive", "Aggressive", RED),
        ("normal", "Normal", GREEN),
        ("conservative", "Conservative", BLUE),
        ("custom", "Custom", PURPLE),
    )

    def __init__(self, parent: tk.Widget, selected: str = "normal",
                 on_select: Optional[Callable[[str], None]] = None,
                 scale: float = 1.0, tooltip: str = "") -> None:
        super().__init__(parent, bg=PANEL)
        self._on_select = on_select
        self._scale = scale
        self._pills: dict[str, TogglePill] = {}
        self._selected = selected
        for key, label, color in self.PRESETS:
            pill = TogglePill(self, text=label, on_text="", off_text="",
                              on_color=color, off_color=DIM,
                              tooltip=tooltip, scale=scale)
            pill.pack(side="left", padx=2, pady=2)
            # Override click handler to act as radio.
            for w in (pill, pill._dot, pill._label, pill._state_lbl):
                w.bind("<Button-1>",
                       lambda _e, k=key: self.select(k))
            self._pills[key] = pill
        # Hide the state label on these — they're radio pills, not toggles.
        for p in self._pills.values():
            p._state_lbl.pack_forget()
        # Mark the selected one without firing the callback (the caller's
        # callback may reference state that isn't built yet at this point).
        if selected in self._pills:
            self._selected = selected
            for k, p in self._pills.items():
                p.set(k == selected)

    def select(self, key: str) -> None:
        if key not in self._pills:
            return
        self._selected = key
        for k, p in self._pills.items():
            p.set(k == key)
        if self._on_select is not None:
            self._on_select(key)

    def get(self) -> str:
        return self._selected


# ── Button ───────────────────────────────────────────────────────────────
class Button(tk.Button):
    """A styled button with consistent dark theme + hover state."""

    def __init__(self, parent: tk.Widget, text: str,
                 command: Optional[Callable] = None,
                 color: str = BLUE, width: Optional[int] = None,
                 scale: float = 1.0, **kw) -> None:
        super().__init__(parent, text=text, command=command, bg=PANEL2,
                         fg=color, activebackground=PANEL_HOVER,
                         activeforeground=color,
                         font=_f(11, scale, bold=True),
                         bd=1, relief="solid",
                         highlightthickness=1, highlightbackground=BORDER,
                         cursor="hand2", padx=10, pady=4, **kw)
        if width:
            self.config(width=width)
        _hover_bg(self, PANEL2)


# ── Modal ────────────────────────────────────────────────────────────────
class Modal(tk.Toplevel):
    """A scrollable modal dialog."""

    def __init__(self, master: tk.Widget, title: str, width: int = 760,
                 height: int = 520) -> None:
        super().__init__(master)
        self.title(title)
        self.configure(bg=BG)
        self.geometry(f"{width}x{height}")
        self.transient(master)
        self.grab_set()
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=PANEL, fg=BLUE, font=FONT_TITLE,
                 anchor="w").pack(side="left", padx=14, pady=10)
        Button(head, "✕ Close", command=self.destroy, color=RED).pack(
            side="right", padx=10, pady=8)
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self._sb = tk.Scrollbar(wrap, orient="vertical",
                                command=self._canvas.yview,
                                troughcolor=PANEL2, bg=PANEL2,
                                activebackground=BLUE, highlightthickness=0,
                                bd=0)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self._canvas, bg=BG)
        self._win = self._canvas.create_window((0, 0), window=self.body,
                                               anchor="nw")
        self.body.bind("<Configure>",
                       lambda _e: self._canvas.configure(
                           scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfigure(self._win,
                                                              width=e.width))
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, e) -> None:
        self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def add_text(self, text: str, color: str = FG, font: Any = FONT_MONO) -> None:
        tk.Label(self.body, text=text, bg=BG, fg=color, font=font,
                 justify="left", anchor="w").pack(fill="x", padx=14, pady=2)


# ── ScrollFrame ──────────────────────────────────────────────────────────
class ScrollFrame(tk.Frame):
    """A vertically scrollable container."""

    def __init__(self, parent: tk.Widget, bg: str = BG) -> None:
        super().__init__(parent, bg=bg)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._sb = tk.Scrollbar(self, orient="vertical",
                                command=self._canvas.yview,
                                troughcolor=PANEL2, bg=PANEL2,
                                activebackground=BLUE, highlightthickness=0,
                                bd=0)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self.inner,
                                               anchor="nw")
        self.inner.bind("<Configure>",
                        lambda _e: self._canvas.configure(
                            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfigure(self._win,
                                                              width=e.width))
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, e) -> None:
        try:
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass


# ── Devil mascot ─────────────────────────────────────────────────────────
def devil_mascot_widget(parent: tk.Widget, scale: float = 1.0,
                        tooltip: str = "") -> tk.Frame:
    """Render the 8-line devil mask as a vertical stack of Tk labels.

    Brand red + orange accent for the eyes. Sized for the dashboard header.
    No tooltip — the devil is decorative, click-to-open-modal handles the
    exploration experience.
    """
    wrap = tk.Frame(parent, bg=BG)
    for idx, line in enumerate(DEVIL_LINES):
        tk.Label(wrap, text=line, bg=BG, fg=RED_BRAND,
                 font=FONT_DEVIL, anchor="w").pack(anchor="w")
    return wrap


# ── PipelineNode + PathwayStrip ─────────────────────────────────────────
class PipelineNode(tk.Frame):
    """A single pathway node with state glyph + name + in/out mini-label.

    Larger and more legible than StageChip. Designed for the bottom-of-window
    pathway strip showing ~10-12 grouped stages of the prompt path.
    """

    def __init__(self, parent: tk.Widget, name: str, sub: str = "",
                 on_click: Optional[Callable] = None,
                 scale: float = 1.0) -> None:
        super().__init__(parent, bg=PANEL, bd=1, relief="solid",
                         highlightthickness=2, highlightbackground=BORDER)
        self.name = name
        self._scale = scale
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=6, pady=(4, 0))
        self._glyph = tk.Label(head, text="○", bg=PANEL, fg=DIM,
                               font=_f(13, scale, bold=True))
        self._glyph.pack(side="left", padx=(0, 4))
        self._lbl = tk.Label(head, text=name, bg=PANEL, fg=DIM,
                             font=_f(11, scale, bold=True), anchor="w")
        self._lbl.pack(side="left", fill="x", expand=True)
        if sub:
            self._sub = tk.Label(self, text=sub, bg=PANEL, fg=DIM,
                                 font=_f(9, scale))
            self._sub.pack(fill="x", padx=6, pady=(0, 4))
        else:
            self._sub = None
        if on_click:
            for w in (self, self._glyph, self._lbl):
                w.bind("<Button-1>", lambda _e: on_click(self.name))
                w.configure(cursor="hand2")
        self._state = "queued"

    def set_state(self, state: str, detail: str = "",
                  in_text: Optional[str] = None,
                  out_text: Optional[str] = None) -> None:
        self._state = state
        color = STATE_COLOR.get(state, DIM)
        glyph = STATE_GLYPH.get(state, "○")
        self._glyph.config(text=glyph, fg=color)
        self._lbl.config(fg=color)
        self.configure(highlightbackground=color)
        if self._sub is not None:
            if in_text or out_text:
                txt = ""
                if in_text:
                    txt += f"in {in_text}"
                if out_text:
                    if txt:
                        txt += " → "
                    txt += f"out {out_text}"
                self._sub.config(text=txt, fg=color)
            elif detail:
                self._sub.config(text=detail[:40], fg=color)
        # No hover tooltip here — the sub-label already shows the detail.
        # Re-creating Tooltip on every refresh was leaving dangling
        # <Enter>/<Leave> bindings that showed stale text in random
        # positions. The click handler (``on_click``) opens a real modal
        # with the full payload if the user wants more.

    def flash(self, color: str = YELLOW, ms: int = 800) -> None:
        """Briefly ring the node in ``color`` to signal 'this changed'."""
        original = self.cget("highlightbackground")
        self.configure(highlightbackground=color)
        try:
            self.after(ms, lambda: self.configure(highlightbackground=original))
        except Exception:
            pass


class PathwayStrip(tk.Frame):
    """A horizontal strip of PipelineNodes with arrows between them.

    Holds an ordered list of node keys. ``set_states(dict)`` updates each
    node from a {key: (state, detail, in_text, out_text)} map.
    ``flash_changed(set)`` transiently highlights nodes whose keys changed.
    """

    def __init__(self, parent: tk.Widget, nodes: List[str],
                 on_node_click: Optional[Callable[[str], None]] = None,
                 scale: float = 1.0) -> None:
        super().__init__(parent, bg=PANEL)
        self._scale = scale
        self._on_click = on_node_click
        self._nodes: dict[str, PipelineNode] = {}
        for i, key in enumerate(nodes):
            if i > 0:
                tk.Label(self, text="→", bg=PANEL, fg=DIM,
                         font=_f(13, scale, bold=True)).pack(
                    side="left", padx=2)
            node = PipelineNode(self, name=key.replace("_", " ").title(),
                                on_click=on_node_click, scale=scale)
            node.pack(side="left", padx=2, pady=2)
            self._nodes[key] = node

    def set_states(self, states: dict) -> None:
        for key, node in self._nodes.items():
            entry = states.get(key, ("queued", "", None, None))
            if len(entry) == 2:
                state, detail = entry
                in_text = out_text = None
            elif len(entry) == 4:
                state, detail, in_text, out_text = entry
            else:
                state, detail = entry[0], entry[1]
                in_text = out_text = None
            node.set_state(state, detail, in_text, out_text)

    def flash_changed(self, changed_keys) -> None:
        for key in changed_keys:
            node = self._nodes.get(key)
            if node is not None:
                node.flash()


# ── SignatureLine (footer) ───────────────────────────────────────────────
def signature_line(parent: tk.Widget, scale: float = 1.0,
                   version: str = "v0.4.x") -> tk.Frame:
    """Bottom-of-window brand signature. Dim, single line, anchored."""
    row = tk.Frame(parent, bg=BG)
    tk.Label(row, text=f"◈ cortexagent · overseer · {version}",
             bg=BG, fg=DIM, font=_f(10, scale), anchor="w").pack(
        side="left", padx=10)
    return row


__all__ = [
    "BG", "PANEL", "PANEL2", "BORDER", "FG", "DIM", "GREEN", "CYAN",
    "BLUE", "YELLOW", "RED", "PURPLE", "GOLD", "RED_BRAND",
    "FONT", "FONT_SM", "FONT_BOLD", "FONT_TITLE", "FONT_TINY", "FONT_MONO",
    "STATE_COLOR", "STATE_GLYPH",
    "init_ttk_theme", "_f", "_hover_bg",
    "Tooltip", "badge", "section", "metric_row", "Bar", "StageChip",
    "TogglePill", "PresetPillGroup", "Button", "Modal", "ScrollFrame",
    "devil_mascot_widget", "PipelineNode", "PathwayStrip", "signature_line",
]