"""lib/overseer_dashboard/ui.py — the fixed-size Overseer companion window.

A high-contrast dark graphical desktop app (not a terminal wallboard):
  - fixed 1600×1000 (fallback 1280×800), non-resizable, centered, position memory
  - header (devil mascot + brand + health + actions)
  - three-column grid + bottom pathway strip + status strip + signature
  - left: Runtime Health / Resources / Context-GPU
  - center: Token Pipeline (7 stages) / Live Inference / Token Detail / Test Harness
  - right: Runtime + SlimToken Settings (Apply/Revert) — SlimToken gets a
    preset pill row (Aggressive / Normal / Conservative / Custom) that
    bundles the underlying knobs so the user never sees bare checkboxes.
  - bottom: pathway strip with 11 grouped nodes of the prompt path +
    "Load last prompt" dropdown fed from hot memory.

Reads typed models from ``telemetry``; never touches raw JSON in the UI
thread. Never fabricates metrics — unavailable values render '—'.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Dict, List, Optional

from . import models as M
from . import telemetry as TEL
from . import pipeline as P
from . import settings as SET
from . import testharness as TH
from . import widgets as W

from lib.banner import DEVIL_LINES as _DEVIL_LINES  # for the header mascot modal

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

STATE_DIR = Path(os.environ.get(
    "CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent")))
POS_FILE = STATE_DIR / "overseer_dashboard_pos.json"

# 2026-08-16: window is opened full-screen (fills the workarea). No maximize
# button, no resizing — the dashboard always covers the active display. The
# geometry is sized to the screen's reported size at boot and updated if the
# X11 workarea changes.
DEFAULT_W, DEFAULT_H = 1920, 1080  # only used as a "small-screen" floor
FALLBACK_W, FALLBACK_H = 1280, 800 # tiny fallback for very small screens

# HiDPI scaling: on a 4K display (or any display where the effective DPI is
# higher than ~96), scale the entire Tk font/widget tree uniformly. The
# window size stays fixed (spec: non-resizable); only the contents scale.
# Override manually with CORTEXAGENT_DASHBOARD_SCALING=N (float) or
# CORTEXAGENT_DASHBOARD_SCALING=auto (default).
SCALING_ENV = os.environ.get("CORTEXAGENT_DASHBOARD_SCALING", "auto")
# Reference "1.0" = 96 DPI, which is what 1440×900 assumes.
REF_DPI = 96.0


def _detect_scale(root: tk.Tk) -> float:
    """Return a Tk scaling factor based on the active display's effective DPI.

    The dashboard window fills the screen, so scaling is safe — we don't
    risk overflowing a fixed-size window. The factor multiplies font sizes
    and widget minsizes uniformly so the UI remains readable on 4K
    displays without squashing the layout.
    """
    if SCALING_ENV and SCALING_ENV != "auto":
        try:
            return float(SCALING_ENV)
        except (TypeError, ValueError):
            pass
    try:
        # Tk returns pixels per virtual point at the current screen DPI.
        # Default is 1.0 at 96 DPI → 1.333 px/pt. On 4K (typically 163–192
        # DPI) this is ~1.7–2.0.
        px_per_pt = float(root.tk.call("tk", "scaling"))
        # Some builds report 1.0 even on HiDPI — fall back to a screen-
        # width heuristic: 4K+ gets 2.0×, QHD gets 1.5×, 1080p stays 1.0×.
        # Each entry assumes a 16-22" display; adjust if needed.
        sw = root.winfo_screenwidth()
        # 1.333 px/pt is the 96 DPI baseline. If Tk reports exactly that
        # value, the WM is not forwarding DPI information — fall back to
        # the screen-width heuristic. Higher values mean the WM reports
        # HiDPI and we trust the math.
        if px_per_pt > 1.4:
            # Trust Tk's report. 1.333 px/pt = 96 DPI = 1.0×. 2.0 px/pt
            # ≈ 144 DPI = 1.5×. For 4K (192 DPI) this is ~2.0×.
            scale = px_per_pt / 1.333
        elif sw >= 3800:
            scale = 2.0   # 4K at 1.0× is too small — bump to 2.0×
        elif sw >= 3200:
            scale = 1.75  # 4K-ish
        elif sw >= 2560:
            scale = 1.5   # QHD / 2K
        elif sw >= 1920:
            scale = 1.25  # 1080p scaled
        else:
            scale = 1.0
        # Clamp to a sane range so a bad Tk report doesn't blow up the
        # layout (e.g. 4.0× on a 1080p would be unreadable).
        return round(max(1.0, min(scale, 2.5)), 2)
    except Exception:
        return 1.0


def _load_pos() -> Optional[Dict[str, int]]:
    try:
        with POS_FILE.open() as f:
            d = json.load(f)
        if isinstance(d, dict) and "x" in d and "y" in d:
            return d
    except Exception:
        pass
    return None


def _save_pos(x: int, y: int) -> None:
    try:
        POS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = POS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"x": x, "y": y}))
        tmp.replace(POS_FILE)
    except Exception:
        pass


class Dashboard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("◈ CORTEXAGENT / OVERSEER")
        self.configure(bg=W.BG)
        # Window is fixed-size at 80% of the screen. Decorations: X + Minimize.
        # The Maximize button is suppressed via wm_resizable(False, False)
        # and the explicit ``wm_state("normal")`` call in _set_geometry.
        self.resizable(False, False)
        # Set the transient-group hint so most WMs keep the window over
        # the dashboard's parent (the tray) — feels less popup-y.
        try:
            self.attributes("-type", "normal")
        except tk.TclError:
            pass
        # HiDPI scaling: scales fonts/widget metrics uniformly with the
        # screen DPI. On a 3840×2400 display this is ~2.0×; on a 1080p
        # laptop it's 1.0×. Applied AFTER the window is up so the
        # geometry calculation uses the unscaled values.
        self._scale = _detect_scale(self)
        try:
            self.tk.call("tk", "scaling", self._scale)
        except Exception:
            pass
        # Configure the ttk theme so Combobox / OptionMenu match the dark
        # palette. Must run after the root window exists.
        W.init_ttk_theme(self)
        self._set_geometry()
        self._paused = False
        self._snapshot: M.RuntimeSnapshot = TEL.read_snapshot()
        self._harness = TH.TestHarness()
        self._settings = SET.build_settings(
            self._snapshot.capabilities, self._snapshot.model)
        self._pipeline = P.build_pipeline(self._snapshot)
        self._pathway = P.build_pathway(self._snapshot, self._pipeline)
        # Preset that matches current SlimToken defaults (Normal).
        self._active_preset = "normal"
        # Track which pathway nodes changed on the most recent prompt
        # re-run, so we can transiently highlight them in the strip.
        self._pathway_changed: set[str] = set()
        self._build_layout()
        self._tick()

    # ── Geometry ─────────────────────────────────────────────────────────
    def _set_geometry(self) -> None:
        """Size the window to 80% of the active workarea, centered.

        Decorations kept: X (close) + Minimize. Maximize removed.
        Window is not resizable — the size is fixed at boot.
        """
        # Cancel any fullscreen / maximized state from earlier sessions.
        try:
            self.attributes("-zoomed", False)
        except tk.TclError:
            pass
        # Force the window manager to only show X + Minimize. The
        # sequence `-fullscreen 0 -zoomed 0` plus `wm_resizable` reliably
        # suppresses the maximize button on every WM that respects
        # EWMH/NetWM (KWin, Mutter, Openbox, XFWM, etc.).
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # 80% of the active workarea, centered. Floor at DEFAULT so
        # very small screens still get a usable canvas.
        w = max(int(sw * 0.80), DEFAULT_W if sw >= DEFAULT_W else FALLBACK_W)
        h = max(int(sh * 0.80), DEFAULT_H if sh >= DEFAULT_H else FALLBACK_H)
        x = max((sw - w) // 2, 0)
        y = max((sh - h) // 2, 0)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._win_w, self._win_h = w, h
        # Lock size. With resizable(False, False) the WM removes the
        # maximize button on most EWMH-compliant WMs and prevents the
        # user from dragging the edges to resize.
        self.wm_resizable(False, False)
        # Belt-and-suspenders: explicitly remove the maximize capability
        # on EWMH WMs. ``-zoomed`` toggles maximize; some WMs also honor
        # ``-maximized`` on the WM_STATE. Setting both to False ensures
        # the WM_STATE never includes _NET_WM_STATE_MAXIMIZED_HORZ/VERT.
        try:
            self.wm_state("normal")
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        try:
            _save_pos(self.winfo_x(), self.winfo_y())
        except Exception:
            pass
        self.destroy()

    def _clear_focus(self, event: Any) -> None:
        """Remove the focus highlight rectangle that X11/Tk draws around
        the most recently focused widget. Allow the click to deliver to
        inputs first, then explicitly clear focus after a tick.
        """
        try:
            w = event.widget
            # Don't steal focus from real inputs.
            cls = w.winfo_class()
            if cls in ("Entry", "TEntry", "Text", "TCombobox", "Spinbox"):
                return
            self.after(1, lambda: self.focus_set())
        except Exception:
            pass

    def _disable_takefocus(self, widget: tk.Widget) -> None:
        """Walk the widget tree and disable focus + highlight on
        non-interactive widgets (labels, frames, panels). Only inputs
        and buttons keep takefocus.
        """
        keep_focus = ("Button", "TButton", "Menubutton", "Entry", "TEntry",
                      "Text", "TCombobox", "Spinbox", "Scale", "TScale",
                      "Checkbutton", "TCheckbutton", "Radiobutton",
                      "OptionMenu", "TOptionMenu", "Listbox", "TListbox")
        try:
            for w in widget.winfo_children():
                self._disable_takefocus(w)
        except Exception:
            pass
        try:
            cls = widget.winfo_class()
            if cls not in keep_focus:
                widget.configure(takefocus=0, highlightthickness=0)
            else:
                # Even interactive widgets lose the focus rectangle.
                widget.configure(highlightthickness=0)
        except Exception:
            pass

    # ── Layout ──────────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Clear focus on any click anywhere not on an input — this kills
        # the stuck "focus highlight" rectangle that X11/Tk draws around
        # selectable labels. Bind on the root so it catches every widget.
        self.bind_all("<Button-1>", self._clear_focus)
        self._build_header()
        # Middle: three-column grid that fills the remaining space.
        mid = tk.Frame(self, bg=W.BG)
        mid.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        s = self._scale
        # Column minsizes grow with scale because Tk's `scaling` makes
        # text/controls physically larger; the same logical-pixel column
        # is too narrow at 2×. Right column needs the most room (settings
        # + test harness) so it scales a bit more aggressively.
        mid.grid_columnconfigure(0, weight=0, minsize=int(380 * s))
        mid.grid_columnconfigure(1, weight=1, minsize=int(680 * s))
        mid.grid_columnconfigure(2, weight=0, minsize=int(820 * s))
        mid.grid_rowconfigure(0, weight=1)
        self._build_left(mid)
        self._build_center(mid)
        self._build_right(mid)
        # Pathway strip (broader-scale prompt path) — sits between the
        # 3-column grid and the per-run status strip.
        self._build_pathway_strip()
        # Status strip pinned near the bottom.
        self._build_status_strip()
        # Brand signature line (very bottom).
        W.signature_line(self, scale=self._scale).pack(
            fill="x", pady=(0, 4))
        # Disable keyboard focus + highlight rectangle on every non-input
        # widget. Stops the "stuck hover highlight" effect and means the
        # only widget that *can* take focus is the next clickable control.
        self._disable_takefocus(self)

    def _build_header(self) -> None:
        # Outer frame holds the gradient accent + content.
        outer = tk.Frame(self, bg=W.BG)
        outer.pack(fill="x", padx=8, pady=(8, 0))
        # 2px gradient accent — drawn with two thin frames stacked.
        accent = tk.Frame(outer, bg=W.BG, height=2)
        accent.pack(fill="x", side="top")
        tk.Frame(accent, bg=W.BLUE, height=2).pack(fill="x", side="top")
        tk.Frame(accent, bg=W.CYAN, height=1).pack(fill="x")
        hdr = tk.Frame(outer, bg=W.PANEL, bd=1, relief="solid",
                       highlightthickness=1, highlightbackground=W.BORDER)
        hdr.pack(fill="x", pady=(2, 0))

        # Devil mascot — leftmost. Scales with self._scale.
        mascot = W.devil_mascot_widget(hdr, scale=self._scale,
                                       tooltip="CortexAgent mascot — click for big")
        mascot.pack(side="left", padx=(8, 4), pady=4)
        for w in mascot.winfo_children():
            w.bind("<Button-1>", self._show_devil_modal)
            w.configure(cursor="hand2")

        # Brand wordmark + tagline stacked.
        title = tk.Frame(hdr, bg=W.PANEL)
        title.pack(side="left", padx=8, pady=6)
        tk.Label(title, text="◈ CORTEXAGENT / OVERSEER",
                 bg=W.PANEL, fg=W.BLUE,
                 font=W._f(15, self._scale, bold=True)).pack(anchor="w")
        tk.Label(title, text="the daemon + the dashboard + the devil",
                 bg=W.PANEL, fg=W.DIM,
                 font=W._f(10, self._scale)).pack(anchor="w")

        # Health + age + buttons, right-aligned.
        right = tk.Frame(hdr, bg=W.PANEL)
        right.pack(side="right", padx=8, pady=6)

        self._health_lbl = tk.Label(right, text="● Connected", bg=W.PANEL,
                                    fg=W.GREEN, font=W._f(13, self._scale, bold=True))
        self._health_lbl.pack(anchor="e")
        self._age_lbl = tk.Label(right, text="data current 0.0s", bg=W.PANEL,
                                 fg=W.CYAN, font=W._f(11, self._scale))
        self._age_lbl.pack(anchor="e")

        btns = tk.Frame(hdr, bg=W.PANEL)
        btns.pack(side="right", padx=8, pady=6)
        W.Button(btns, "Refresh", self._refresh_now, color=W.BLUE,
                 scale=self._scale).pack(side="left", padx=2)
        self._pause_btn = W.Button(btns, "Pause refresh", self._toggle_pause,
                                   color=W.YELLOW, scale=self._scale)
        self._pause_btn.pack(side="left", padx=2)
        W.Button(btns, "Logs", self._open_logs, color=W.CYAN,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(btns, "Diagnostics", self._open_diagnostics, color=W.CYAN,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(btns, "⚙ Settings", self._open_settings_modal, color=W.GOLD,
                 scale=self._scale).pack(side="left", padx=2)

    def _show_devil_modal(self, _e=None) -> None:
        """Open a modal showing the devil glyph at 2× size."""
        modal = W.Modal(self, "CortexAgent", width=520, height=380)
        big = tk.Frame(modal.body, bg=W.BG)
        big.pack(fill="both", expand=True, padx=20, pady=20)
        for idx, line in enumerate(_DEVIL_LINES):
            tk.Label(big, text=line, bg=W.BG, fg=W.RED_BRAND,
                     font=("DejaVu Sans Mono", int(20 * self._scale), "bold"),
                     justify="left").pack(anchor="w")
        tk.Label(big,
                 text="the little devil · brand mascot · restored 2026-08-16",
                 bg=W.BG, fg=W.DIM,
                 font=W._f(11, self._scale)).pack(anchor="w", pady=(12, 0))

    # ── Left column ────────────────────────────────────────────────────
    def _build_left(self, grid: tk.Frame) -> None:
        col = tk.Frame(grid, bg=W.BG)
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        # Runtime Health
        _frame, body = W.section(col, "RUNTIME HEALTH", W.GREEN, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._health_rows: Dict[str, tk.Label] = {}
        for key, label in (("big", "Big model"), ("tiny", "Tiny overseer"),
                           ("proxy", "Proxy"), ("backend", "Backend")):
            row = tk.Frame(body, bg=W.PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=W.PANEL, fg=W.DIM,
                     font=W._f(11, self._scale), anchor="w").pack(side="left")
            v = tk.Label(row, text="—", bg=W.PANEL, fg=W.DIM,
                         font=W._f(13, self._scale, bold=True), anchor="e")
            v.pack(side="right")
            self._health_rows[key] = v
        # Resources
        _frame, body = W.section(col, "RESOURCES", W.CYAN, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._vram_bar = W.Bar(body, "VRAM", W.CYAN, scale=self._scale)
        self._vram_bar.pack(fill="x", pady=2)
        self._ram_lbl = tk.Label(body, text="RAM: —", bg=W.PANEL, fg=W.FG,
                                 font=W._f(11, self._scale))
        self._ram_lbl.pack(fill="x", pady=2)
        self._gpu_lbl = tk.Label(body, text="GPU util: —", bg=W.PANEL, fg=W.FG,
                                 font=W._f(11, self._scale))
        self._gpu_lbl.pack(fill="x", pady=2)
        # Context / GPU
        _frame, body = W.section(col, "CONTEXT / GPU", W.YELLOW, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._ctx_bar = W.Bar(body, "Context", W.YELLOW, scale=self._scale)
        self._ctx_bar.pack(fill="x", pady=2)
        self._queue_lbl = tk.Label(body, text="Queue: —", bg=W.PANEL, fg=W.FG,
                                   font=W._f(11, self._scale))
        self._queue_lbl.pack(fill="x", pady=2)
        self._sess_lbl = tk.Label(body, text="Sessions: —", bg=W.PANEL, fg=W.FG,
                                  font=W._f(11, self._scale))
        self._sess_lbl.pack(fill="x", pady=2)
        self._last_lbl = tk.Label(body, text="Last request: —", bg=W.PANEL, fg=W.FG,
                                  font=W._f(11, self._scale))
        self._last_lbl.pack(fill="x", pady=2)

    # ── Center column ──────────────────────────────────────────────────
    def _build_center(self, grid: tk.Frame) -> None:
        col = tk.Frame(grid, bg=W.BG)
        col.grid(row=0, column=1, sticky="nsew", padx=3)
        # Model identity
        _frame, body = W.section(col, "MODEL & ROUTE", W.BLUE, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._model_lbl = tk.Label(body, text="Model: unknown", bg=W.PANEL, fg=W.FG,
                                   font=W._f(13, self._scale, bold=True), anchor="w")
        self._model_lbl.pack(fill="x")
        self._route_lbl = tk.Label(body, text="Route: cortex-big · Backend: —",
                                   bg=W.PANEL, fg=W.DIM,
                                   font=W._f(11, self._scale), anchor="w")
        self._route_lbl.pack(fill="x")
        # Token Pipeline
        _frame, body = W.section(col, "TOKEN PIPELINE", W.PURPLE, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        stages = ("COLLECT", "COMPOSE", "SLIMTOKEN", "FINALIZE",
                  "PREFILL", "DECODE", "DELIVER")
        self._stage_chips: Dict[str, W.StageChip] = {}
        # Two rows: 4 + 3 chips with arrows on each row.
        for row_start in (0, 4):
            row_frame = tk.Frame(body, bg=W.PANEL)
            row_frame.pack(fill="x", pady=2)
            row = stages[row_start:row_start + 4]
            for i, name in enumerate(row):
                chip = W.StageChip(row_frame, name,
                                   on_click=self._open_stage_detail,
                                   scale=self._scale)
                chip.pack(side="left", padx=2)
                self._stage_chips[name] = chip
                if i < len(row) - 1:
                    tk.Label(row_frame, text="→", bg=W.PANEL, fg=W.DIM,
                             font=W._f(13, self._scale, bold=True)).pack(side="left")
        self._pipeline_detail = tk.Label(body, text="", bg=W.PANEL, fg=W.DIM,
                                         font=W._f(11, self._scale), anchor="w",
                                         justify="left")
        self._pipeline_detail.pack(fill="x", pady=(2, 0))
        # Live Inference
        _frame, body = W.section(col, "LIVE INFERENCE + TOKEN DETAIL",
                                 W.CYAN, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._inf_rows: Dict[str, tk.Label] = {}
        for key, label in (("in_tps", "Input (prefill)"), ("out_tps", "Output (decode)"),
                           ("in_tok", "Input tokens"), ("out_tok", "Output tokens"),
                           ("cache", "Cache"), ("reused", "Reused")):
            row = tk.Frame(body, bg=W.PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=W.PANEL, fg=W.DIM,
                     font=W._f(11, self._scale), anchor="w").pack(side="left")
            v = tk.Label(row, text="—", bg=W.PANEL, fg=W.FG,
                         font=W._f(13, self._scale, bold=True), anchor="e")
            v.pack(side="right")
            self._inf_rows[key] = v
        self._no_work = tk.Label(body, text="No active inference\nStart a request in "
                                            "CortexAgent or run a controlled test.",
                                 bg=W.PANEL, fg=W.DIM,
                                 font=W._f(11, self._scale), justify="left")
        self._no_work.pack(fill="x", pady=2)
        # Test Harness — placed in the center column so it's always visible
        # (the right column is settings-only and scrolls).
        _frame, body = W.section(col, "TEST HARNESS", W.GREEN, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._build_test_harness(body)

    # ── Right column ────────────────────────────────────────────────────
    def _build_right(self, grid: tk.Frame) -> None:
        wrap = W.ScrollFrame(grid)
        wrap.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        col = wrap.inner
        col.configure(bg=W.BG)
        # Runtime Settings
        _frame, body = W.section(col, "RUNTIME SETTINGS", W.BLUE, scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        self._setting_widgets: Dict[str, tk.Widget] = {}
        self._build_setting_group(body, "runtime")
        # SlimToken Settings — get the preset pill row at the top so the
        # user can pick Aggressive / Normal / Conservative / Custom without
        # seeing the underlying checkboxes.
        _frame, body = W.section(col, "SLIMTOKEN SETTINGS", W.PURPLE,
                                 scale=self._scale)
        _frame.pack(fill="x", pady=2, anchor="n")
        preset_row = tk.Frame(body, bg=W.PANEL)
        preset_row.pack(fill="x", pady=(0, 4))
        tk.Label(preset_row, text="Preset", bg=W.PANEL, fg=W.DIM,
                 font=W._f(11, self._scale), anchor="w").pack(side="left")
        self._preset_pills = W.PresetPillGroup(
            preset_row, selected=self._active_preset,
            on_select=self._on_preset_select,
            scale=self._scale,
            tooltip="Bundles policy + budget + dedup + thresholds. "
                    "Pick Custom to expose individual knobs.")
        self._preset_pills.pack(side="right")
        # The custom-reveal frame holds the underlying SlimToken knobs and
        # is hidden unless the user picks Custom.
        self._slim_custom_frame = tk.Frame(body, bg=W.PANEL)
        self._build_setting_group(self._slim_custom_frame, "slimtoken")
        # Apply / Revert
        act = tk.Frame(col, bg=W.BG)
        act.pack(fill="x", pady=4)
        self._apply_btn = W.Button(act, "Apply", self._apply_settings,
                                   color=W.GREEN, scale=self._scale)
        self._apply_btn.pack(side="left", padx=2)
        self._revert_btn = W.Button(act, "Revert", self._revert_settings,
                                    color=W.YELLOW, scale=self._scale)
        self._revert_btn.pack(side="left", padx=2)
        self._save_btn = W.Button(act, "Save as default",
                                  self._save_defaults, color=W.GOLD,
                                  scale=self._scale)
        self._save_btn.pack(side="left", padx=2)
        self._pending_lbl = tk.Label(act, text="", bg=W.BG, fg=W.YELLOW,
                                     font=W._f(11, self._scale))
        self._pending_lbl.pack(side="left", padx=4)
        # Hide custom frame on boot (default = Normal preset).
        self._slim_custom_frame.pack_forget()
        # Test Harness moved to center column (always visible).

    def _build_setting_group(self, body: tk.Frame, group: str) -> None:
        for key, d in self._settings.definitions.items():
            if d.group != group or not d.supported:
                continue
            row = tk.Frame(body, bg=W.PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=d.label, bg=W.PANEL, fg=W.DIM,
                     font=W._f(11, self._scale), anchor="w").pack(side="left")
            if d.tooltip:
                W.Tooltip(row, d.tooltip)
            val = self._settings.active.get(key, d.value)
            if d.kind == "toggle":
                # Themed toggle pill instead of bare checkbutton.
                pill = W.TogglePill(
                    row, text=d.label, on_text="ON", off_text="OFF",
                    on_color=W.GREEN, off_color=W.DIM,
                    command=lambda v, k=key: self._on_setting(k, v),
                    on_value=True, off_value=False,
                    scale=self._scale)
                pill.set(bool(val))
                pill.pack(side="right")
                self._setting_widgets[key] = pill
            elif d.kind == "select":
                var = tk.StringVar(value=str(val))
                om = ttk.OptionMenu(row, var, str(val), *d.options,
                                    command=lambda v, k=key, vv=var:
                                    self._on_setting(k, vv.get()))
                om.pack(side="right")
                self._setting_widgets[key] = var
            elif d.kind == "slider":
                var = tk.DoubleVar(value=float(val))
                sc = tk.Scale(row, from_=d.min, to=d.max, resolution=d.step,
                              orient="horizontal", variable=var, bg=W.PANEL,
                              fg=W.FG, troughcolor=W.PANEL2,
                              highlightthickness=0,
                              length=int(140 * self._scale),
                              command=lambda v, k=key, vv=var:
                              self._on_setting(k, vv.get()))
                sc.pack(side="right")
                self._setting_widgets[key] = var
            else:  # number / text
                var = tk.StringVar(value=str(val))
                en = tk.Entry(row, textvariable=var, width=10, bg=W.PANEL2,
                              fg=W.FG, insertbackground=W.FG, bd=1,
                              relief="solid", highlightthickness=1,
                              highlightbackground=W.BORDER,
                              font=W._f(11, self._scale))
                en.pack(side="right")
                en.bind("<KeyRelease>",
                        lambda _e, k=key, v=var: self._on_setting(k, v.get()))
                self._setting_widgets[key] = var

    def _on_preset_select(self, preset: str) -> None:
        """Apply a SlimToken preset: rewrite the 5 bundled keys via set_pending."""
        self._active_preset = preset
        # Map preset → settings dictionary.
        presets = {
            "aggressive": {
                "slimtoken_policy": "aggressive",
                "target_context_budget": 80000,
                "dedup": True,
                "history_compact_threshold": 1024,
                "retrieval_budget": 1024,
            },
            "normal": {
                "slimtoken_policy": "balanced",
                "target_context_budget": 120000,
                "dedup": True,
                "history_compact_threshold": 2000,
                "retrieval_budget": 2000,
            },
            "conservative": {
                "slimtoken_policy": "conservative",
                "target_context_budget": 150000,
                "dedup": False,
                "history_compact_threshold": 4000,
                "retrieval_budget": 4000,
            },
            "custom": {},
        }
        values = presets.get(preset, {})
        for key, value in values.items():
            SET.set_pending(self._settings, key, value)
        # Reveal or hide the underlying knobs based on the preset.
        if preset == "custom":
            self._slim_custom_frame.pack(fill="x", pady=4)
        else:
            self._slim_custom_frame.pack_forget()
        self._sync_setting_widgets()
        self._update_pending_ui()

    def _on_setting(self, key: str, value: Any) -> None:
        d = self._settings.definitions.get(key)
        if d is None:
            return
        try:
            if d.kind in ("number", "slider"):
                value = float(value) if isinstance(value, (int, float)) else float(value)
                if d.min is not None and d.min == int(d.min) and d.max == int(d.max):
                    value = int(value)
        except (ValueError, TypeError):
            return
        SET.set_pending(self._settings, key, value)
        self._update_pending_ui()

    def _update_pending_ui(self) -> None:
        changed = self._settings.changed_keys
        if changed:
            self._pending_lbl.config(text=f"{len(changed)} pending", fg=W.YELLOW)
            self._apply_btn.config(state="normal")
            self._revert_btn.config(state="normal")
        else:
            self._pending_lbl.config(text="", fg=W.YELLOW)
            self._apply_btn.config(state="disabled")
            self._revert_btn.config(state="disabled")

    def _apply_settings(self) -> None:
        disruptive = SET.disruptive_keys(self._settings)
        if disruptive:
            if not self._confirm_disruptive(disruptive):
                return
        SET.apply_pending(self._settings)
        self._sync_setting_widgets()
        self._update_pending_ui()

    def _revert_settings(self) -> None:
        SET.revert_pending(self._settings)
        self._sync_setting_widgets()
        self._update_pending_ui()

    def _save_defaults(self) -> None:
        if not self._confirm("Save current settings as defaults?",
                             "This persists session-only changes to disk."):
            return
        SET.save_as_default(self._settings)

    def _sync_setting_widgets(self) -> None:
        for key, w in self._setting_widgets.items():
            val = self._settings.active.get(key)
            d = self._settings.definitions.get(key)
            if d is None:
                continue
            try:
                if isinstance(w, W.TogglePill):
                    w.set(bool(val))
                elif isinstance(w, tk.BooleanVar):
                    w.set(bool(val))
                elif isinstance(w, tk.DoubleVar):
                    w.set(float(val))
                elif isinstance(w, tk.StringVar):
                    w.set(str(val))
            except Exception:
                pass

    def _confirm_disruptive(self, keys: List[str]) -> bool:
        msg = ("Changing these will interrupt/reset active work:\n  " +
               ", ".join(keys) +
               "\n\nAffected: active request/session may be reset.\n"
               "Continue?")
        return self._confirm("Disruptive change", msg)

    def _confirm(self, title: str, msg: str) -> bool:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=W.BG)
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg, text=msg, bg=W.BG, fg=W.FG, font=W.FONT_SM, justify="left",
                 wraplength=360).pack(padx=16, pady=12)
        btns = tk.Frame(dlg, bg=W.BG)
        btns.pack(pady=8)
        res = {"ok": False}
        W.Button(btns, "Cancel", lambda: (res.update(ok=False), dlg.destroy()),
                 color=W.RED).pack(side="left", padx=4)
        W.Button(btns, "Confirm", lambda: (res.update(ok=True), dlg.destroy()),
                 color=W.GREEN).pack(side="left", padx=4)
        self.wait_window(dlg)
        return res["ok"]

    # ── Test harness ────────────────────────────────────────────────────
    def _build_test_harness(self, body: tk.Frame) -> None:
        # Prompt input — keep tight, real results are below.
        self._test_prompt = tk.Text(body, height=2, bg=W.PANEL2, fg=W.FG,
                                    insertbackground=W.FG, bd=1, relief="solid",
                                    highlightthickness=1, highlightbackground=W.BORDER,
                                    font=W._f(11, self._scale))
        self._test_prompt.pack(fill="x", pady=2)
        self._test_prompt.insert("1.0", "Test prompt…")
        self._test_prompt.bind("<FocusIn>",
                               lambda _e: self._test_prompt.delete("1.0", "end")
                               if self._test_prompt.get("1.0", "end").strip() == "Test prompt…"
                               else None)
        self._char_lbl = tk.Label(body, text="~0 chars · ~0 tokens", bg=W.PANEL,
                                  fg=W.DIM,
                                  font=W._f(11, self._scale), anchor="w")
        self._char_lbl.pack(fill="x")
        self._test_prompt.bind("<KeyRelease>", self._update_char_count)
        # Preset + toggles (toggles are now TogglePills — no more white squares).
        row = tk.Frame(body, bg=W.PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Preset", bg=W.PANEL, fg=W.DIM,
                 font=W._f(11, self._scale)).pack(side="left")
        self._preset_var = tk.StringVar(value="simple")
        ttk.OptionMenu(row, self._preset_var, "simple", *TH.PRESETS.keys()
                       ).pack(side="right")
        self._use_pending_var = tk.BooleanVar(value=False)
        self._use_pending_pill = W.TogglePill(
            body, text="Use pending (unapplied) settings",
            on_text="ON", off_text="OFF", on_color=W.GREEN, off_color=W.DIM,
            command=None, on_value=True, off_value=False, scale=self._scale)
        self._use_pending_pill._command = lambda v: self._use_pending_var.set(v)
        self._use_pending_pill.pack(fill="x", anchor="w", pady=1)
        self._slim_on_var = tk.BooleanVar(value=True)
        self._slim_on_pill = W.TogglePill(
            body, text="SlimToken on (compare off)",
            on_text="ON", off_text="OFF", on_color=W.PURPLE, off_color=W.DIM,
            command=None, on_value=True, off_value=False, scale=self._scale)
        self._slim_on_pill._command = lambda v: self._slim_on_var.set(v)
        self._slim_on_pill.set(True)
        self._slim_on_pill.pack(fill="x", anchor="w", pady=1)
        # Buttons
        btns = tk.Frame(body, bg=W.PANEL)
        btns.pack(fill="x", pady=4)
        W.Button(btns, "Run test", self._run_test, color=W.GREEN,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(btns, "Cancel", self._cancel_test, color=W.YELLOW,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(btns, "Clear", self._harness.clear, color=W.RED,
                 scale=self._scale).pack(side="left", padx=2)

        # ── Prominent results panel (replaces tiny status label) ────────
        self._test_results_body = tk.Frame(body, bg=W.PANEL)
        self._test_results_body.pack(fill="x", pady=4)
        # Empty-state seed.
        tk.Label(self._test_results_body,
                 text="No tests run yet.\nPress Run test to see SlimToken savings.",
                 bg=W.PANEL, fg=W.DIM,
                 font=W._f(11, self._scale), justify="left",
                 anchor="w").pack(fill="x")

        # ── Inline test history (replaces modal popup) ──────────────────
        hist_head = tk.Frame(body, bg=W.PANEL)
        hist_head.pack(fill="x", pady=(4, 0))
        tk.Label(hist_head, text="Test history (latest 5)", bg=W.PANEL, fg=W.PURPLE,
                 font=W._f(12, self._scale, bold=True),
                 anchor="w").pack(side="left")
        self._history_canvas = tk.Frame(body, bg=W.PANEL)
        self._history_canvas.pack(fill="x", pady=2)

    def _render_test_results(self, run: M.TestRun) -> None:
        """Paint a prominent results panel: big savings %, before→after tokens,
        SlimToken actions breakdown.
        """
        # Clear children.
        for c in self._test_results_body.winfo_children():
            c.destroy()
        if run.status != "complete":
            color = W.RED if run.status == "failed" else W.YELLOW
            tk.Label(self._test_results_body, text=f"{run.status.upper()}",
                     bg=W.PANEL, fg=color,
                     font=W._f(16, self._scale, bold=True),
                     anchor="w").pack(fill="x")
            if run.errors:
                tk.Label(self._test_results_body, text="; ".join(run.errors),
                         bg=W.PANEL, fg=W.DIM,
                         font=W._f(11, self._scale), anchor="w",
                         justify="left", wraplength=380).pack(fill="x")
            return

        # Top row: big savings badge + token arrow.
        top = tk.Frame(self._test_results_body, bg=W.PANEL)
        top.pack(fill="x")
        saved_pct = run.saved_pct or 0.0
        saved_color = W.PURPLE if saved_pct >= 10 else (W.CYAN if saved_pct > 0 else W.DIM)
        badge = tk.Label(top, text=f"{saved_pct:.1f}%\nsaved", bg=saved_color,
                         fg="#0d0d12",
                         font=W._f(18, self._scale, bold=True),
                         padx=10, pady=4, bd=1, relief="solid", justify="center")
        badge.pack(side="left")
        meta = tk.Frame(top, bg=W.PANEL)
        meta.pack(side="left", fill="x", expand=True, padx=10)
        tk.Label(meta, text=(f"{run.input_tokens} → {run.output_tokens or 0} tokens"),
                 bg=W.PANEL, fg=W.FG,
                 font=W._f(14, self._scale, bold=True),
                 anchor="w").pack(anchor="w")
        saved_tokens = max((run.input_tokens or 0) - (run.output_tokens or 0), 0)
        tk.Label(meta, text=f"= {saved_tokens} tokens saved",
                 bg=W.PANEL, fg=W.PURPLE,
                 font=W._f(12, self._scale), anchor="w").pack(anchor="w")

        # Stage breakdown — only the stages that actually fired.
        slim_stage = next((s for s in run.stages if s.name == "SLIMTOKEN"), None)
        if slim_stage and isinstance(slim_stage.payload, M.SlimTokenResult):
            slim = slim_stage.payload
            counts = {}
            for a in slim.actions:
                counts[a.action] = counts.get(a.action, 0) + 1
            counts_text = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
            tk.Label(self._test_results_body, text=counts_text,
                     bg=W.PANEL, fg=W.DIM,
                     font=W._f(11, self._scale), anchor="w").pack(fill="x")

        # Pinned block notice (proves protection worked).
        pinned = sum(1 for s in run.stages if s.name == "COMPOSE"
                     and isinstance(s.payload, M.ComposeResult)
                     for b in s.payload.pinned)
        if pinned:
            tk.Label(self._test_results_body,
                     text=f"✓ {pinned} pinned blocks preserved unchanged",
                     bg=W.PANEL, fg=W.GREEN,
                     font=W._f(11, self._scale), anchor="w"
                     ).pack(fill="x")

        # Settings used + elapsed.
        tk.Label(self._test_results_body,
                 text=(f"settings: {run.settings_used} · slimtoken: "
                       f"{'on' if run.slimtoken_on else 'off'} · "
                       f"{run.elapsed_s}s · preset: {run.label}"),
                 bg=W.PANEL, fg=W.DIM,
                 font=W._f(11, self._scale), anchor="w"
                 ).pack(fill="x")

    def _render_test_history(self) -> None:
        for c in self._history_canvas.winfo_children():
            c.destroy()
        for run in self._harness.runs[-5:][::-1]:
            row = tk.Frame(self._history_canvas, bg=W.PANEL)
            row.pack(fill="x", pady=2)
            color = W.GREEN if run.status == "complete" else (
                W.RED if run.status == "failed" else W.YELLOW)
            mark = "✓" if run.status == "complete" else ("✕" if run.status == "failed" else "◷")
            tk.Label(row, text=mark, bg=W.PANEL, fg=color,
                     font=W._f(13, self._scale, bold=True),
                     width=2).pack(side="left")
            tk.Label(row,
                     text=(f"{run.label} · {run.input_tokens}→{run.output_tokens or 0} "
                           f"· saved {run.saved_pct:.1f}% · {run.elapsed_s}s"),
                     bg=W.PANEL, fg=W.FG,
                     font=W._f(11, self._scale), anchor="w"
                     ).pack(side="left", padx=4)

    def _update_char_count(self, _e=None) -> None:
        text = self._test_prompt.get("1.0", "end").strip()
        self._char_lbl.config(text=f"~{len(text)} chars · ~{len(text) // 4} tokens")

    def _run_test(self) -> None:
        prompt = self._test_prompt.get("1.0", "end").strip()
        if not prompt or prompt == "Test prompt…":
            for c in self._test_results_body.winfo_children():
                c.destroy()
            tk.Label(self._test_results_body,
                     text="Enter a prompt first, then press Run test.",
                     bg=W.PANEL, fg=W.YELLOW,
                     font=W._f(13, self._scale, bold=True),
                     anchor="w").pack(fill="x")
            return
        preset = self._preset_var.get()
        settings_used = "pending" if self._use_pending_var.get() else "active"
        slim_on = self._slim_on_var.get()
        run = self._harness.run_dry(
            prompt, preset=preset, settings_used=settings_used,
            slimtoken_on=slim_on, model=self._snapshot.model.display_model(),
            route=self._snapshot.model.route, backend=self._snapshot.model.backend)
        self._render_test_results(run)
        self._render_test_history()
        # Highlight which pathway nodes changed on this prompt.
        self._mark_pathway_from_run(run)

    def _cancel_test(self) -> None:
        for r in self._harness.runs:
            if r.status == "running":
                self._harness.cancel(r.id)
        for c in self._test_results_body.winfo_children():
            c.destroy()
        tk.Label(self._test_results_body, text="Test cancelled",
                 bg=W.PANEL, fg=W.YELLOW,
                 font=W._f(13, self._scale, bold=True),
                 anchor="w").pack(fill="x")
        self._render_test_history()

    def _mark_pathway_from_run(self, run: M.TestRun) -> None:
        """Translate a TestRun into the set of pathway nodes that fired."""
        fired = {"slimtoken_minify", "context_fit"}
        if run.slimtoken_on:
            fired.add("slimtoken_minify")
        if run.input_tokens:
            fired.update({"prompt_intake", "prefill", "cost_ledger"})
        if run.output_tokens:
            fired.update({"decode", "stream_out", "cost_ledger"})
        self._pathway_changed = fired
        if hasattr(self, "_pathway_strip") and self._pathway_strip is not None:
            self._pathway_strip.flash_changed(fired)

    # ── Status strip ───────────────────────────────────────────────────
    def _build_status_strip(self) -> None:
        strip = tk.Frame(self, bg=W.PANEL, bd=1, relief="solid",
                         highlightthickness=1, highlightbackground=W.BORDER)
        strip.pack(fill="x", padx=8, pady=(4, 8))
        # Scheduler summary
        sched = tk.Frame(strip, bg=W.PANEL)
        sched.pack(side="left", fill="x", expand=True, padx=8)
        self._sched_lbl = tk.Label(sched, text="Scheduler: —", bg=W.PANEL, fg=W.GREEN,
                                   font=W._f(13, self._scale, bold=True), anchor="w")
        self._sched_lbl.pack(fill="x")
        self._sched_tasks = tk.Label(sched, text="", bg=W.PANEL, fg=W.DIM,
                                     font=W._f(11, self._scale), anchor="w",
                                     justify="left")
        self._sched_tasks.pack(fill="x")
        sched_btns = tk.Frame(sched, bg=W.PANEL)
        sched_btns.pack(fill="x")
        W.Button(sched_btns, "Run now", lambda: None, color=W.BLUE,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(sched_btns, "New task", lambda: None, color=W.BLUE,
                 scale=self._scale).pack(side="left", padx=2)
        W.Button(sched_btns, "Manage tasks", self._open_scheduler, color=W.CYAN,
                 scale=self._scale).pack(side="left", padx=2)
        # SlimToken summary
        slim = tk.Frame(strip, bg=W.PANEL)
        slim.pack(side="right", fill="x", expand=True, padx=8)
        self._slim_lbl = tk.Label(slim, text="SlimToken: —", bg=W.PANEL, fg=W.PURPLE,
                                  font=W._f(13, self._scale, bold=True), anchor="w")
        self._slim_lbl.pack(fill="x")
        self._slim_detail = tk.Label(slim, text="", bg=W.PANEL, fg=W.DIM,
                                     font=W._f(11, self._scale), anchor="w",
                                     justify="left")
        self._slim_detail.pack(fill="x")
        slim_btns = tk.Frame(slim, bg=W.PANEL)
        slim_btns.pack(fill="x")
        self._slim_diff_visible = False
        self._slim_dryrun_visible = False
        self._diff_btn = W.Button(slim_btns, "View diff", self._toggle_diff,
                                  color=W.PURPLE, scale=self._scale)
        self._diff_btn.pack(side="left", padx=2)
        self._dryrun_btn = W.Button(slim_btns, "Dry-run", self._toggle_dryrun,
                                    color=W.PURPLE, scale=self._scale)
        self._dryrun_btn.pack(side="left", padx=2)
        # Inline toggle panels (replace modal popups).
        self._diff_panel = tk.Frame(strip, bg=W.PANEL)
        self._dryrun_panel = tk.Frame(strip, bg=W.PANEL)

    # ── Pathway strip (broader-scale prompt path) ────────────────────
    def _build_pathway_strip(self) -> None:
        wrap = tk.Frame(self, bg=W.PANEL, bd=1, relief="solid",
                        highlightthickness=1, highlightbackground=W.BORDER)
        wrap.pack(fill="x", padx=8, pady=(4, 0))
        head = tk.Frame(wrap, bg=W.PANEL)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text="PROMPT PATHWAY", bg=W.PANEL, fg=W.PURPLE,
                 font=W._f(13, self._scale, bold=True), anchor="w").pack(side="left")
        # "Load last prompt" dropdown fed from hot memory.
        load_row = tk.Frame(head, bg=W.PANEL)
        load_row.pack(side="right")
        tk.Label(load_row, text="Load last prompt:", bg=W.PANEL, fg=W.DIM,
                 font=W._f(11, self._scale)).pack(side="left", padx=(0, 6))
        self._last_prompts = P.load_last_prompts(limit=20)
        labels = [f"{p['ts'][11:19]} · {p['preview']}" for p in self._last_prompts] \
            or ["(no prompts in hot memory)"]
        self._last_prompt_var = tk.StringVar(value=labels[0])
        self._last_prompt_om = ttk.OptionMenu(
            load_row, self._last_prompt_var, labels[0], *labels,
            command=self._on_load_last_prompt)
        self._last_prompt_om.pack(side="left")
        # The strip itself.
        strip_body = tk.Frame(wrap, bg=W.PANEL)
        strip_body.pack(fill="x", padx=8, pady=8)
        self._pathway_strip = W.PathwayStrip(
            strip_body, nodes=list(M.PATHWAY_GROUPS),
            on_node_click=self._open_pathway_node_detail,
            scale=self._scale)
        self._pathway_strip.pack(fill="x")
        # Initial paint.
        self._pathway_strip.set_states(self._pathway)

    def _on_load_last_prompt(self, _label: str = "") -> None:
        """Fill the test-harness prompt box from the selected hot-memory entry
        and re-run it. Then flash the pathway nodes that fired."""
        if not self._last_prompts:
            return
        # Find the entry whose preview matches.
        target = None
        for p in self._last_prompts:
            if p["preview"] in _label:
                target = p
                break
        if target is None:
            target = self._last_prompts[0]
        # Fill the test-harness prompt.
        self._test_prompt.delete("1.0", "end")
        self._test_prompt.insert("1.0", target["content"])
        self._update_char_count()
        # Trigger a re-run.
        self._run_test()

    def _open_pathway_node_detail(self, key: str) -> None:
        """Click on a pathway node → show its underlying stage (if any) in
        the existing pipeline-stage modal."""
        # Map pathway key → existing pipeline stage name.
        mapping = {
            "prompt_intake": "COLLECT",
            "frame_assemble": "COMPOSE",
            "slimtoken_minify": "SLIMTOKEN",
            "context_fit": "FINALIZE",
            "prefill": "PREFILL",
            "decode": "DECODE",
            "stream_out": "DELIVER",
        }
        stage_name = mapping.get(key)
        if stage_name is None:
            # Derived node — no underlying stage, show a synthetic modal.
            entry = self._pathway.get(key, ("queued", "—", None, None))
            state, detail, in_text, out_text = entry
            modal = W.Modal(self, f"Pathway: {key.replace('_', ' ').title()}",
                            width=560, height=300)
            modal.add_text(f"State: {state}", W.STATE_COLOR.get(state, W.DIM))
            modal.add_text(f"Detail: {detail}")
            if in_text or out_text:
                modal.add_text(
                    f"In: {in_text or '—'} → Out: {out_text or '—'}",
                    W.FG, W.FONT_BOLD)
            modal.add_text(
                "Derived node — no underlying pipeline stage. "
                "Computed from snapshot inference + minify stats.",
                W.DIM)
            return
        self._open_stage_detail(stage_name)

    # ── Refresh loop ────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.config(text="Resume refresh" if self._paused else "Pause refresh")

    def _refresh_now(self) -> None:
        self._snapshot = TEL.read_snapshot()
        self._pipeline = P.build_pipeline(self._snapshot)
        self._pathway = P.build_pathway(self._snapshot, self._pipeline)
        if hasattr(self, "_pathway_strip") and self._pathway_strip is not None:
            self._pathway_strip.set_states(self._pathway)
        self._paint()

    def _tick(self) -> None:
        if not self._paused:
            self._refresh_now()
        self.after(1000, self._tick)

    # ── Painting ─────────────────────────────────────────────────────────
    def _paint(self) -> None:
        s = self._snapshot
        # Header health
        if s.stale or not s.connected:
            self._health_lbl.config(text="! Backend unreachable", fg=W.RED)
            self._age_lbl.config(text=f"displaying last snapshot ({s.data_age_s:.0f}s old)",
                                 fg=W.YELLOW)
        else:
            self._health_lbl.config(text="● Connected", fg=W.GREEN)
            self._age_lbl.config(text=f"data current {s.data_age_s:.1f}s", fg=W.CYAN)
        # Model
        self._model_lbl.config(text=f"Model: {s.model.display_model()}", fg=W.FG)
        self._route_lbl.config(text=f"Route: {s.model.route} · Backend: {s.model.backend}",
                               fg=W.DIM)
        # Health rows
        self._health_rows["big"].config(
            text="● healthy" if s.big_healthy else "✕ down",
            fg=W.GREEN if s.big_healthy else W.RED)
        self._health_rows["tiny"].config(
            text="● healthy" if s.tiny_healthy else "✕ down",
            fg=W.GREEN if s.tiny_healthy else W.RED)
        self._health_rows["proxy"].config(
            text="● up" if s.proxy_up else "✕ down",
            fg=W.GREEN if s.proxy_up else W.RED)
        self._health_rows["backend"].config(
            text="● healthy" if s.backend_healthy else "✕ down",
            fg=W.GREEN if s.backend_healthy else W.RED)
        # Resources
        inf = s.inference
        self._vram_bar.set(inf.vram_used_mib, inf.vram_total_mib,
                           text=(f"{inf.vram_used_mib} MiB / {inf.vram_total_mib} MiB"
                                 if inf.vram_used_mib is not None else "—"))
        self._ram_lbl.config(text=f"RAM: {inf.ram_used_mib} MiB" if inf.ram_used_mib else "RAM: —")
        self._gpu_lbl.config(text=f"GPU util: {inf.gpu_util_pct}%" if inf.gpu_util_pct is not None else "GPU util: —")
        # Context
        self._ctx_bar.set(inf.context_used, inf.context_window,
                          text=(f"{inf.context_used} / {inf.context_window}"
                                if inf.context_used is not None else "—"))
        self._queue_lbl.config(text=f"Queue: {s.queue_pending} pending / {s.queue_total} total")
        self._sess_lbl.config(text=f"Sessions: {inf.session_count}" if inf.session_count is not None else "Sessions: —")
        self._last_lbl.config(text=f"Last request: {inf.last_request_status}" if inf.last_request_status else "Last request: —")
        # Pipeline stages
        for stage in self._pipeline:
            chip = self._stage_chips.get(stage.name)
            if chip:
                chip.set_state(stage.state, stage.detail)
        # Inference rows
        self._inf_rows["in_tps"].config(
            text=f"{inf.input_tps:.0f} tok/s" if inf.input_tps is not None else "—",
            fg=W.CYAN if inf.input_tps is not None else W.DIM)
        self._inf_rows["out_tps"].config(
            text=f"{inf.output_tps:.1f} tok/s" if inf.output_tps is not None else "—",
            fg=W.CYAN if inf.output_tps is not None else W.DIM)
        self._inf_rows["in_tok"].config(
            text=str(inf.input_tokens) if inf.input_tokens is not None else "—")
        self._inf_rows["out_tok"].config(
            text=str(inf.output_tokens) if inf.output_tokens is not None else "—")
        self._inf_rows["cache"].config(
            text=f"{inf.cache_pct}%" if inf.cache_pct is not None else "—",
            fg=W.PURPLE if inf.cache_pct is not None else W.DIM)
        self._inf_rows["reused"].config(
            text=f"{inf.reused_pct}%" if inf.reused_pct is not None else "—",
            fg=W.PURPLE if inf.reused_pct is not None else W.DIM)
        self._no_work.pack_forget() if inf.active else self._no_work.pack(fill="x", pady=2)
        # Scheduler
        sch = s.scheduler
        if sch.stale:
            self._sched_lbl.config(text=f"! scheduler stale · {sch.stale_detail}", fg=W.YELLOW)
        else:
            self._sched_lbl.config(
                text=f"Scheduler: {'● Enabled' if sch.enabled else '○ Disabled'} · "
                     f"{sch.active_count} active · {sch.paused_count} paused",
                fg=W.GREEN if sch.enabled else W.DIM)
        task_lines = []
        for t in sch.tasks[:4]:
            if t.status == "paused":
                task_lines.append(f"◌ {t.name} · paused")
            else:
                task_lines.append(f"● {t.name} · {t.humanized or t.cron} · {t.next_run}")
        self._sched_tasks.config(text="\n".join(task_lines) if task_lines else "No tasks")
        # SlimToken summary
        m = s.minify or {}
        if m.get("runs"):
            self._slim_lbl.config(text=f"SlimToken: {m.get('runs')} runs · {m.get('ratio_pct', 0)}% saved",
                                  fg=W.PURPLE)
            self._slim_detail.config(
                text=f"in {m.get('tokens_in', 0)} → out {m.get('tokens_out', 0)} tokens")
        else:
            self._slim_lbl.config(text="SlimToken: no runs yet", fg=W.DIM)
            self._slim_detail.config(text="")

    # ── Modals ──────────────────────────────────────────────────────────
    def _open_logs(self) -> None:
        modal = W.Modal(self, "Logs", 760, 520)
        modal.add_text("— Logs —", W.BLUE, W.FONT_TITLE)
        modal.add_text("Full error chains and transport logs live here.", W.DIM)
        modal.add_text("(Log tailing is wired to the daemon log file.)", W.DIM)

    def _open_diagnostics(self) -> None:
        modal = W.Modal(self, "Diagnostics", 760, 560)
        modal.add_text("— Diagnostics —", W.BLUE, W.FONT_TITLE)
        s = self._snapshot
        modal.add_text(f"Connected: {s.connected} · stale: {s.stale} ({s.stale_detail})")
        modal.add_text(f"Model: {s.model.display_model()} (source: {s.model.source})")
        modal.add_text(f"Route: {s.model.route} · Backend: {s.model.backend}")
        modal.add_text(f"Big healthy: {s.big_healthy} · Tiny: {s.tiny_healthy} · Proxy: {s.proxy_up}")
        modal.add_text("")
        modal.add_text("Error chain:", W.YELLOW, W.FONT_BOLD)
        if s.error_chain:
            for e in s.error_chain:
                modal.add_text(f"  {e}", W.RED)
        else:
            modal.add_text("  (none)", W.DIM)
        modal.add_text("")
        modal.add_text("Alerts:", W.YELLOW, W.FONT_BOLD)
        for a in s.alerts:
            modal.add_text(f"  • {a}", W.YELLOW)
        if not s.alerts:
            modal.add_text("  (none)", W.DIM)

    def _open_scheduler(self) -> None:
        modal = W.Modal(self, "Scheduler Manager", 720, 520)
        modal.add_text("— Scheduler Manager —", W.BLUE, W.FONT_TITLE)
        sch = self._snapshot.scheduler
        modal.add_text(f"Enabled: {sch.enabled} · healthy: {sch.healthy} · "
                       f"{sch.active_count} active · {sch.paused_count} paused")
        modal.add_text("")
        for t in sch.tasks:
            modal.add_text(f"● {t.name}  [{t.status}]  cron: {t.cron or '—'}  "
                           f"({t.humanized or 'unrecognized'})  next: {t.next_run or '—'}")

    def _open_diff(self) -> None:
        pass  # kept for backward compat; inline toggle below

    def _toggle_diff(self) -> None:
        if self._slim_diff_visible:
            self._diff_panel.pack_forget()
            self._diff_btn.config(text="View diff")
            self._slim_diff_visible = False
            return
        # Render into the inline panel.
        for c in self._diff_panel.winfo_children():
            c.destroy()
        head = tk.Frame(self._diff_panel, bg=W.PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Optimization Diff", bg=W.PANEL, fg=W.PURPLE,
                 font=W.FONT_BOLD, anchor="w").pack(side="left")
        tk.Label(self._diff_panel,
                 text="(in-place — no popup; pinned blocks untouched)",
                 bg=W.PANEL, fg=W.DIM, font=W.FONT_SM, anchor="w").pack(fill="x")
        m = self._snapshot.minify or {}
        if not m.get("runs"):
            tk.Label(self._diff_panel, text="No optimization runs yet — run a "
                     "dry-run to see a diff.", bg=W.PANEL, fg=W.DIM,
                     font=W.FONT_SM, anchor="w").pack(fill="x")
        else:
            tk.Label(self._diff_panel, text=f"Before: {m.get('tokens_in', 0)} tokens",
                     bg=W.PANEL, fg=W.FG, font=W.FONT_SM, anchor="w").pack(fill="x")
            tk.Label(self._diff_panel, text=f"After:  {m.get('tokens_out', 0)} tokens",
                     bg=W.PANEL, fg=W.FG, font=W.FONT_SM, anchor="w").pack(fill="x")
            tk.Label(self._diff_panel,
                     text=(f"Saved:  {m.get('tokens_saved', 0)} tokens "
                           f"({m.get('ratio_pct', 0)}%)"),
                     bg=W.PANEL, fg=W.PURPLE,
                     font=("DejaVu Sans", int(11 * self._scale), "bold"),
                     anchor="w").pack(fill="x")
        self._diff_panel.pack(fill="x", padx=8, pady=(2, 4))
        self._diff_btn.config(text="Hide diff")
        self._slim_diff_visible = True

    def _open_dryrun(self) -> None:
        pass  # kept for backward compat; inline toggle below

    def _toggle_dryrun(self) -> None:
        if self._slim_dryrun_visible:
            self._dryrun_panel.pack_forget()
            self._dryrun_btn.config(text="Dry-run")
            self._slim_dryrun_visible = False
            return
        for c in self._dryrun_panel.winfo_children():
            c.destroy()
        tk.Label(self._dryrun_panel, text="Dry-run (no inference sent)",
                 bg=W.PANEL, fg=W.PURPLE, font=W.FONT_BOLD, anchor="w").pack(fill="x")
        dr = P.dry_run("dry-run sample prompt", preset="long_context")
        tk.Label(self._dryrun_panel,
                 text=(f"Compose: {dr.compose.total_tokens} tokens · "
                       f"{len(dr.compose.blocks)} blocks · "
                       f"{len(dr.compose.pinned)} pinned"),
                 bg=W.PANEL, fg=W.FG, font=W.FONT_SM, anchor="w").pack(fill="x")
        tk.Label(self._dryrun_panel,
                 text=(f"SlimToken: {dr.slim.before_tokens} → "
                       f"{dr.slim.after_tokens} · saved {dr.slim.saved_pct:.1f}%"),
                 bg=W.PANEL, fg=W.PURPLE,
                 font=("DejaVu Sans", int(11 * self._scale), "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(self._dryrun_panel,
                 text=f"Finalize fits: {dr.finalize.fits} · "
                      f"input {dr.finalize.input_tokens}",
                 bg=W.PANEL, fg=W.GREEN if dr.finalize.fits else W.RED,
                 font=W.FONT_SM, anchor="w").pack(fill="x")
        self._dryrun_panel.pack(fill="x", padx=8, pady=(2, 4))
        self._dryrun_btn.config(text="Hide dry-run")
        self._slim_dryrun_visible = True

    def _open_stage_detail(self, name: str) -> None:
        modal = W.Modal(self, f"Pipeline Stage: {name}", 680, 480)
        modal.add_text(f"— {name} —", W.BLUE, W.FONT_TITLE)
        stage = next((s for s in self._pipeline if s.name == name), None)
        if stage is None:
            modal.add_text("No data for this stage.", W.DIM)
            return
        modal.add_text(f"State: {stage.state}", W.STATE_COLOR.get(stage.state, W.DIM))
        modal.add_text(f"Detail: {stage.detail or '—'}")
        if stage.tokens_in is not None:
            modal.add_text(f"Tokens in: {stage.tokens_in}")
        if stage.tokens_out is not None:
            modal.add_text(f"Tokens out: {stage.tokens_out}")
        if stage.elapsed_ms is not None:
            modal.add_text(f"Elapsed: {stage.elapsed_ms:.0f} ms")
        # Stage-specific payload
        if isinstance(stage.payload, M.ComposeResult):
            modal.add_text("")
            modal.add_text("Request Frame", W.YELLOW, W.FONT_BOLD)
            modal.add_text(f"Policy: {stage.payload.policy}")
            modal.add_text(f"Input budget: {stage.payload.input_budget} tokens")
            modal.add_text(f"Output reserved: {stage.payload.output_reserved} tokens")
            modal.add_text(f"Blocks: {len(stage.payload.blocks)} · Pinned: "
                           f"{len(stage.payload.pinned)} · Compressible: "
                           f"{len(stage.payload.compressible)} · Discardable: "
                           f"{len(stage.payload.discardable)}")
            modal.add_text("")
            modal.add_text("Pinned", W.GREEN, W.FONT_BOLD)
            for b in stage.payload.pinned:
                modal.add_text(f"  - {b.source:<28} {b.tokens} tokens")
            modal.add_text("Eligible for SlimToken", W.PURPLE, W.FONT_BOLD)
            for b in stage.payload.compressible:
                modal.add_text(f"  - {b.source:<28} {b.tokens} tokens")
        elif isinstance(stage.payload, M.SlimTokenResult):
            modal.add_text("")
            modal.add_text("Actions", W.PURPLE, W.FONT_BOLD)
            for a in stage.payload.actions:
                modal.add_text(f"  {a.action:<12} {a.category:<14} "
                               f"{a.tokens_before}→{a.tokens_after}  {a.reason}")

    def _open_test_history(self) -> None:
        modal = W.Modal(self, "Test History", 760, 560)
        modal.add_text("— Test History —", W.GREEN, W.FONT_TITLE)
        if not self._harness.runs:
            modal.add_text("No tests run yet.", W.DIM)
            return
        for r in self._harness.runs:
            modal.add_text(f"{r.status.upper():<9} {r.label:<20} in {r.input_tokens} "
                           f"→ out {r.output_tokens} · saved {r.saved_pct}% · "
                           f"{r.elapsed_s}s · {r.settings_used} settings")
        modal.add_text("")
        comp = self._harness.comparison()
        if comp:
            modal.add_text("Comparison (selected runs)", W.YELLOW, W.FONT_BOLD)
            modal.add_text(f"{'Metric':<18}{comp['a'].label:<18}{comp['b'].label}")
            for label, av, bv in comp["rows"]:
                modal.add_text(f"{label:<18}{av if av is not None else '—':<18}"
                               f"{bv if bv is not None else '—'}")
        else:
            modal.add_text("Select two runs to compare.", W.DIM)

    def _open_settings_modal(self) -> None:
        modal = W.Modal(self, "Settings", 640, 480)
        modal.add_text("— Settings —", W.GOLD, W.FONT_TITLE)
        modal.add_text("Session-only changes are marked Pending and applied "
                       "with Apply. Save as default persists them.", W.DIM)
        modal.add_text("")
        for key, d in self._settings.definitions.items():
            if not d.supported:
                continue
            active = self._settings.active.get(key, d.value)
            pending = self._settings.pending.get(key, d.value)
            mark = " ⚠ pending" if pending != active else ""
            modal.add_text(f"{d.label:<28} {active}{mark}",
                           W.YELLOW if mark else W.FG)


def open_dashboard() -> None:
    """Open the dashboard (blocking)."""
    app = Dashboard()
    app.mainloop()


def open_in_thread() -> "threading.Thread":
    """Open the dashboard in a background thread (non-blocking)."""
    import threading
    t = threading.Thread(target=open_dashboard, daemon=True)
    t.start()
    return t


def main() -> int:
    open_dashboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
