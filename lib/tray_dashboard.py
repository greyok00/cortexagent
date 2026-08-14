"""CortexAgent tray popout dashboard — 4K-aware (HiDPI-scales), animated.

Replaces the original 440×360 / 9pt flat panels. New layout:
  - Tk scaling 3.5 (1080p) / 4.0 (1440p) / 4.5 (4K+); overridable via
    CORTEXAGENT_DASHBOARD_SCALING env
  - 40% screen width × 95% screen height, anchored RIGHT, so the terminal
    that spawned the popout keeps the LEFT 60% (user-facing constraint).
    Override size ratio with CORTEXAGENT_DASHBOARD_SCALE (default 0.40).
  - 18pt base fonts, monospace 18pt body, 22pt panel headers, 28pt hero
  - Embedded `lib.banner.LOGO` (8-line wolf-knight ASCII glyph, ice-blue)
  - Animated charts (Tk Canvas only — stdlib, no matplotlib):
      * tok/s sparkline (60-sample rolling)
      * VRAM bar chart (used/free/cap)
      * minify savings panel (% saved + 60s sparkline + runs + tokens)
      * memory tier panel (hot H, warm W, cold C)
      * active sessions list
      * plan tracker (Step N of M)
      * queue depth + scheduler count
      * health alerts strip
      * step counter (▓▓░░ with pulse on update)
  - Escapes on <Escape>; closes via WM X or button.

Reads state from:
  - Daemon control socket        lib/control.send_request("status")
  - Overseer state JSON          ~/.cortexagent/overseer_state.json
  - Big-model steps              ~/.cortexagent/big_model_steps.json
  - Proxy /metrics (HTTP :8081)  VRAM + tok/s + minify snapshot
  - Overseer plan JSON           ~/.cortexagent/overseer_plan.json
  - Overseer queue JSON          ~/.cortexagent/overseer_queue.json
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from lib.state_format import format_dashboard as _format_dashboard  # noqa: E402
from collections import deque
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

# ── Paths ────────────────────────────────────────────────────────────────────
HOME = Path.home()
STATE_DIR = HOME / ".cortexagent"
OVERSEER_STATE = STATE_DIR / "overseer_state.json"
BIG_STEP_STATE = STATE_DIR / "big_model_steps.json"
MINIFY_STATS = STATE_DIR / "minify_stats.json"
PLAN_FILE = STATE_DIR / "overseer_plan.json"
QUEUE_FILE = STATE_DIR / "overseer_queue.json"

# Proxy endpoints
PROXY_PORT = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
PROXY_METRICS = f"http://127.0.0.1:{PROXY_PORT}/metrics"

# ── Color palette ────────────────────────────────────────────────────────────
BG = "#0d0d12"
PANEL = "#15151c"
BORDER = "#2a2a36"
FG = "#e8e8f0"
DIM = "#7a7a8c"
ICE = "#96dcff"          # banner ice-blue (Tk hex extraction from ANSI)
ACCENT = "#c9a84c"       # gold
SUCCESS = "#5ec47a"
WARN = "#e0a23a"
ALERT = "#d65a5a"
ACTIVE = "#5aa8e0"

# Memory tier colors (hot/warm/cold — warm to cool)
HOT_FG = "#f08a8a"
WARM_FG = "#e0a23a"
COLD_FG = "#5aa8e0"


# ── Idle-tip rotation pool ──────────────────────────────────────────────────
_TIPS: List[str] = [
    "Tip: 'Reload models' in the tray menu reloads big + reloads config.",
    "Tip: 'Reload config' re-reads cortexagent.conf without restarting the daemon.",
    "Tip: 'Restart overseer' kills and restarts the overseer service.",
    "Tip: double-click the tray icon to toggle this dashboard.",
    "Tip: pressing Esc closes this window — the tray icon stays.",
    "Tip: lib/minify + slimtoken dedup → typical 8-50% prompt-token savings (see the panel below).",
    "Tip: tok/s sparkline shows the last 60s of inference throughput.",
    "Tip: VRAM bar shows current GPU usage vs total (the big model allocates ~13GB).",
    "Tip: the step counter pulses when a new tool-call lands.",
    "Tip: hover won't work — this is Tk, not HTML — but everything updates every second.",
]


def _rotating_tip() -> str:
    bucket = int(time.time() // 15)
    return _TIPS[bucket % len(_TIPS)]


# ── State readers ──────────────────────────────────────────────────────────
def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        with path.open() as f:
            d = json.load(f)
        return d if d else default
    except Exception:
        return default


def _read_daemon_status() -> Dict[str, Any]:
    try:
        repo = Path(__file__).resolve().parent.parent
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from lib import control
        return control.send_request("status", timeout=2) or {}
    except Exception:
        return {}


def _read_proxy_metrics() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(PROXY_METRICS, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {}


def _format_kb(n: int) -> str:
    if n is None:
        return "—"
    if n < 1024:
        return f"{n}"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}K"
    return f"{n / (1024 * 1024):.1f}M"


def _model_id_daemon(daemon: Dict[str, Any]) -> str:
    big = (daemon.get("big") or {})
    # v0.5.3: the daemon returns `model` (full path) and `alias` (short).
    # Accept any of these so the panel renders the model name in real time.
    # v0.5.4: prefer the basename of the model path so the user sees the
    # actual model (e.g. "Qwen3.6-35B-A3B-UD-IQ3_S.gguf") rather than the
    # generic "cortexagent" alias. The alias is still used as fallback.
    path = (big.get("model") or big.get("model_path") or "")
    if path and "/" in path:
        path = path.rsplit("/", 1)[-1]
    return (path or big.get("alias") or big.get("name") or "?")


# ── Inline tk unicode-glyph renderer ────────────────────────────────────────
def _render_banner(parent: tk.Widget) -> tk.Frame:
    """Render the lib.banner.LOGO as a Tk Text widget with ice-blue glyphs.

    `lib/banner.LOGO` is 8 lines of block characters drawn frame-uniform.
    We use a Text widget per line so the colors render correctly under Tk.
    """
    from lib.banner import LOGO, LOGO_W
    frame = tk.Frame(parent, bg=BG)
    for ln in LOGO:
        # Pad each line so the banner stays frame-uniform (Tk doesn't auto-pad).
        padded = ln.ljust(LOGO_W)
        lbl = tk.Label(frame, text=padded, bg=BG, fg=ICE,
                       font=("DejaVu Sans Mono", 16, "bold"),
                       anchor="w", justify="left")
        lbl.pack(anchor="w", padx=0, pady=0)
    tag = tk.Label(frame, text="CORTEXAGENT", bg=BG, fg=ICE,
                   font=("DejaVu Sans", 13, "bold"))
    tag.pack(anchor="w", padx=2, pady=(4, 0))
    sub = tk.Label(frame, text="by GreyOK00 · overseer dashboard",
                   bg=BG, fg=DIM, font=("DejaVu Sans", 10))
    sub.pack(anchor="w", padx=2, pady=0)
    return frame


# ── Chart widgets ───────────────────────────────────────────────────────────
class Sparkline(tk.Canvas):
    """Rolling-window sparkline. Renders as a single polyline + last-value tag.

    Optional second series via ``set_series`` so the TOK/SECOND panel can show
    input vs decode rates on the same axis. ``color2`` is the input-rate color
    (lighter teal); the primary ``color`` is the decode rate (active teal).
    """

    def __init__(self, master: tk.Widget, width: int = 360, height: int = 80,
                 history_max: int = 60, color: str = ACTIVE,
                 color2: Optional[str] = None, bg: str = PANEL, **kw) -> None:
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self.w = width
        self.h = height
        self.color = color
        self.color2 = color2 or color
        self.history: deque = deque(maxlen=history_max)
        self.history2: deque = deque(maxlen=history_max)
        self._label_id: Optional[int] = None
        self._label2_id: Optional[int] = None

    def push(self, value: float) -> None:
        try:
            self.history.append(float(value))
        except Exception:
            return
        self._redraw()

    def set_series(self, primary: deque, secondary: Optional[deque] = None) -> None:
        """Replace rolling buffers (used by _paint_charts so input + decode
        share one axis without each one reallocating the deque)."""
        self.history = primary
        self.history2 = secondary if secondary is not None else deque(maxlen=len(primary))
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        # Show second-series line only if it has actual values — avoids clutter
        # when the proxy only reported a decode rate (single-stream jobs).
        has2 = any(v > 0 for v in self.history2)
        vals = list(self.history)
        if has2:
            vals = vals + list(self.history2)
        if len(vals) < 2:
            return
        lo = min(vals)
        hi = max(vals)
        if hi - lo < 0.001:
            hi = lo + 1.0
        pad = 8
        inner_w = self.w - 2 * pad
        inner_h = self.h - 2 * pad

        def _points(seq: deque) -> List[Tuple[float, float]]:
            n = len(seq)
            if n < 2:
                return []
            step = inner_w / max(n - 1, 1)
            return [(pad + step * i,
                     pad + inner_h * (1 - (v - lo) / (hi - lo)))
                    for i, v in enumerate(seq)]

        # Draw secondary series first (behind), then primary.
        if has2:
            pts2 = _points(self.history2)
            if pts2:
                self.create_line(pts2, fill=self.color2, width=1, smooth=True,
                                 dash=(3, 2))
                lx, ly = pts2[-1]
                self.create_oval(lx - 2, ly - 2, lx + 2, ly + 2,
                                 fill=self.color2, outline="")
        pts = _points(self.history)
        if pts:
            self.create_line(pts, fill=self.color, width=2, smooth=True)
            lx, ly = pts[-1]
            r = 3
            self.create_oval(lx - r, ly - r, lx + r, ly + r,
                             fill=self.color, outline=ACCENT)
            try:
                tag = f"{self.history[-1]:.1f}"
            except Exception:
                tag = "?"
            if self._label_id is not None:
                self.delete(self._label_id)
            self._label_id = self.create_text(self.w - 4, 10, anchor="ne",
                                              text=tag, fill=FG,
                                              font=("DejaVu Sans Mono", 10, "bold"))
            # When both series present, also label the secondary.
            if has2 and self.history2:
                try:
                    tag2 = f"in {self.history2[-1]:.0f}"
                except Exception:
                    tag2 = ""
                if tag2 and self._label2_id is not None:
                    self.delete(self._label2_id)
                if tag2:
                    self._label2_id = self.create_text(
                        self.w - 4, 26, anchor="ne", text=tag2, fill=self.color2,
                        font=("DejaVu Sans Mono", 9, "bold"))


class VRAMBar(tk.Canvas):
    """Horizontal stacked VRAM bar with used/free/cap segments.

    When called with the optional ``by_proc`` dict (from the daemon's
    ``vram_by_proc`` payload), the bar colour-codes big vs tiny vs other so the
    user can see who is holding the GPU — not just the total. When omitted,
    falls back to the legacy used/free view (single solid colour).
    """

    def __init__(self, master: tk.Widget, width: int = 360, height: int = 80,
                 bg: str = PANEL, **kw) -> None:
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self.w = width
        self.h = height

    def draw(self, used_mib: Optional[int], total_mib: Optional[int],
             by_proc: Optional[Dict[str, int]] = None) -> None:
        self.delete("all")
        if not used_mib or not total_mib or total_mib <= 0:
            self.create_text(self.w / 2, self.h / 2, text="VRAM: —",
                              fill=DIM, font=("DejaVu Sans Mono", 11))
            return
        used_ratio = used_mib / total_mib
        free = total_mib - used_mib
        pad = 4
        bar_y0 = self.h * 0.45
        bar_y1 = self.h * 0.85
        bar_w = self.w - 2 * pad
        used_w = bar_w * used_ratio
        free_w = bar_w - used_w
        # Stacked per-process breakdown when available — otherwise fall back to
        # the single-colour legacy bar.
        if by_proc:
            big = max(0, int(by_proc.get("big_mib", 0) or 0))
            tiny = max(0, int(by_proc.get("tiny_mib", 0) or 0))
            other = max(0, int(by_proc.get("other_mib", 0) or 0))
            seg_total = max(big + tiny + other, 1)
            # Big → ACCENT (teal), tiny → ICE (light blue), other → WARN (gold)
            x_cursor = pad
            for seg, col, lbl in (
                (big,   ACCENT, "big"),
                (tiny,  ICE,    "tiny"),
                (other, WARN,   "other"),
            ):
                if seg <= 0:
                    continue
                w = used_w * (seg / seg_total)
                if w < 1:
                    continue
                self.create_rectangle(x_cursor, bar_y0, x_cursor + w, bar_y1,
                                      fill=col, outline=BORDER)
                x_cursor += w
        else:
            used_color = WARN if used_ratio > 0.85 else ACCENT
            self.create_rectangle(pad, bar_y0, pad + used_w, bar_y1,
                                  fill=used_color, outline=BORDER)
        # Free segment
        self.create_rectangle(pad + used_w, bar_y0, pad + used_w + free_w, bar_y1,
                              fill=BORDER, outline=BORDER)
        # Label
        label = (f"VRAM  {used_mib / 1024:.1f} / "
                 f"{total_mib / 1024:.1f} GB  ({used_ratio * 100:.0f}% used)")
        self.create_text(pad + 6, bar_y0 - 14, anchor="nw", text=label,
                         fill=FG, font=("DejaVu Sans Mono", 11, "bold"))
        # Per-process breakdown legend (only when stacked colour-coded).
        if by_proc:
            big = max(0, int(by_proc.get("big_mib", 0) or 0))
            tiny = max(0, int(by_proc.get("tiny_mib", 0) or 0))
            other = max(0, int(by_proc.get("other_mib", 0) or 0))
            legend_parts = []
            if big:
                legend_parts.append(f"big {big/1024:.1f} GB")
            if tiny:
                legend_parts.append(f"tiny {tiny/1024:.1f} GB")
            if other:
                legend_parts.append(f"other {other/1024:.1f} GB")
            if legend_parts:
                self.create_text(pad + 6, bar_y1 + 4, anchor="nw",
                                 text=" + ".join(legend_parts) +
                                      f"  ·  free {free / 1024:.1f} GB",
                                 fill=DIM, font=("DejaVu Sans Mono", 9))


class StepBar(tk.Canvas):
    """Animated step counter with block-glyph progress + pulse on update."""

    def __init__(self, master: tk.Widget, width: int = 360, height: int = 90,
                 bg: str = PANEL, **kw) -> None:
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self.w = width
        self.h = height
        self._pulse_on = False
        self._pulse_after_id: Optional[str] = None

    def draw(self, steps: List[Dict[str, Any]], current: int) -> None:
        self.delete("all")
        total = len(steps)
        if total == 0:
            self.create_text(self.w / 2, self.h / 2, text="no active task",
                              fill=DIM, font=("DejaVu Sans Mono", 12))
            return
        bar = ""
        for i in range(total):
            if i <= current:
                bar += "▓"
            else:
                bar += "░"
        pct = int((current + 1) / max(total, 1) * 100)
        self.create_text(8, 14, anchor="nw",
                         text=f"{bar}  Step {current + 1} of {total}  ({pct}%)",
                         fill=ACCENT,
                         font=("DejaVu Sans Mono", 14, "bold"))
        # Last 7 step labels (current ± 3)
        labels: List[Tuple[str, str]] = []
        if current >= 3:
            labels.append(("…", DIM))
        for i in range(max(0, current - 3), min(total, current + 4)):
            mark = "✓" if i < current else ("●" if i == current else "○")
            col = SUCCESS if i < current else (ACTIVE if i == current else DIM)
            labels.append((f"{mark} {steps[i].get('label', f'step {i+1}')[:40]}", col))
        for j, (t, c) in enumerate(labels):
            self.create_text(8, 36 + j * 14, anchor="nw", text=t,
                             fill=c, font=("DejaVu Sans Mono", 11))


# ── Main dashboard window ───────────────────────────────────────────────────
class Dashboard(tk.Tk):
    POLL_MS = 1000  # 1Hz refresh cadence

    def __init__(self) -> None:
        super().__init__()
        self.title("CortexAgent — Overseer")
        self.configure(bg=BG)
        # v0.5.3: bigger window default (was 1280x720 — too cramped on 1080p).
        # User reported "tiny for 1080p" — bumped to 1920x1080 so the right
        # column doesn't get clipped, and the Tk scaling factor increased so
        # the on-screen text actually fills the panel cells. Env override
        # preserved (CORTEXAGENT_DASHBOARD_SCALING).
        #
        # v0.5.4: CONSTRAINT — the dashboard must fit on screen NEXT to a
        # terminal (the user opens it from the tray while the CLI is running
        # in a terminal). Before this fix the 90%-of-screen change on a 4K
        # display made the popout 3456x2160, covering the terminal entirely.
        # Now the window is sized to ~40% of screen width, full height, and
        # positioned on the RIGHT side so the terminal keeps the LEFT 60%.
        # Adjust CORTEXAGENT_DASHBOARD_SCALE to change the size ratio.
        try:
            sw = self.winfo_screenwidth() or 1920
            sh = self.winfo_screenheight() or 1080
        except Exception:
            sw, sh = 1920, 1080
        # Width: ~40% of screen (capped between 900 and 1700). Height: full
        # screen (capped 720..1980). The terminal that spawned the popout
        # keeps the other ~60% on the left.
        try:
            scale = float(os.environ.get("CORTEXAGENT_DASHBOARD_SCALE", "0.40"))
        except Exception:
            scale = 0.40
        ww = max(900, min(int(sw * scale), 1700))
        wh = max(720, min(int(sh * 0.95), 1980))
        # Anchor to the RIGHT side of the screen so the terminal on the left
        # stays visible. x = sw - ww (right edge); y = 0.
        try:
            x = max(0, sw - ww)
            y = max(0, (sh - wh) // 2)
            self.geometry(f"{ww}x{wh}+{x}+{y}")
        except Exception:
            self.geometry(f"{ww}x{wh}")
        self.minsize(900, 720)

        # HiDPI scaling: env override first, then derive from screen height.
        # Higher scaling = bigger text. 1080p gets 3.75; 4K gets 4.5.
        # Clamp 1.5..5.5.
        try:
            env_scale = os.environ.get("CORTEXAGENT_DASHBOARD_SCALING")
            if env_scale:
                scaling = float(env_scale)
            else:
                px_h = sh
                if px_h >= 2160:
                    scaling = 4.5
                elif px_h >= 1440:
                    scaling = 4.0
                else:
                    scaling = 3.5
            scaling = max(1.5, min(scaling, 5.5))
            self.tk.call("tk", "scaling", scaling)
        except Exception:
            pass

        # Esc to close
        self.bind("<Escape>", lambda e: self.destroy())
        # R to force-refresh (when window is focused)
        self.bind("<Key-r>", lambda e: self._refresh())

        # ── Fonts (v0.5.4: bumped for 4K readability BUT the window is now
        # sized to fit beside a terminal, so on-screen text post-scaling is:
        #   1080p screen: ~16-32px (matches what the user saw working)
        #   1440p screen: ~18-36px   4K: ~20-40px
        self.f_mono_s = tkfont.Font(family="DejaVu Sans Mono", size=14)
        self.f_mono = tkfont.Font(family="DejaVu Sans Mono", size=18)
        self.f_mono_b = tkfont.Font(family="DejaVu Sans Mono", size=18, weight="bold")
        self.f_mono_l = tkfont.Font(family="DejaVu Sans Mono", size=24, weight="bold")
        self.f_label = tkfont.Font(family="DejaVu Sans", size=18, weight="bold")
        self.f_label_l = tkfont.Font(family="DejaVu Sans", size=22, weight="bold")
        self.f_label_xl = tkfont.Font(family="DejaVu Sans", size=28, weight="bold")
        self.f_tip = tkfont.Font(family="DejaVu Sans", size=16, slant="italic")

        # ── Rolling buffers
        self.toks_history: deque = deque(maxlen=60)        # decode (output) rate
        self.toks_in_history: deque = deque(maxlen=60)     # prompt-eval (input) rate
        self.minify_history: deque = deque(maxlen=60)

        # ── Build layout
        self._build_layout()

        # First paint + recurring refresh
        self._refresh()
        self.after(self.POLL_MS, self._tick)

    # ── Layout ──────────────────────────────────────────────────────────
    def _build_layout(self) -> None:
        # Top bar (row 0) + 3-column body (row 1).
        # 3-column body: left = banner + identity; middle = charts;
        # right = tables + alerts.
        self.columnconfigure(0, weight=0, minsize=280)
        self.columnconfigure(1, weight=1, minsize=520)
        self.columnconfigure(2, weight=1, minsize=400)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)

        self._build_topbar()

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, columnspan=3, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=280)
        body.columnconfigure(1, weight=1, minsize=520)
        body.columnconfigure(2, weight=1, minsize=400)
        body.rowconfigure(0, weight=1)

        self.left = tk.Frame(body, bg=BG)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        self.mid = tk.Frame(body, bg=BG)
        self.mid.grid(row=0, column=1, sticky="nsew", padx=6, pady=12)
        self.right = tk.Frame(body, bg=BG)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(6, 12), pady=12)

        self._build_left()
        self._build_middle()
        self._build_right()

    # ── Top bar (refresh button + last-updated + data freshness) ─────────
    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, highlightbackground=BORDER,
                       highlightthickness=1, bd=0)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew",
                 padx=12, pady=(12, 6))
        bar.columnconfigure(0, weight=0)
        bar.columnconfigure(1, weight=1)
        bar.columnconfigure(2, weight=0)

        # Refresh button (left)
        self.refresh_btn = tk.Button(
            bar, text="↻ Refresh", bg=PANEL, fg=ACCENT,
            activebackground=PANEL, activeforeground=ICE,
            font=self.f_label, bd=0, cursor="hand2",
            command=self._refresh)
        self.refresh_btn.grid(row=0, column=0, sticky="w", padx=(10, 6), pady=6)

        # Last-updated timestamp (center, expands)
        self.refresh_ts_lbl = tk.Label(
            bar, text="last refreshed —", bg=PANEL, fg=DIM,
            font=self.f_mono, anchor="w")
        self.refresh_ts_lbl.grid(row=0, column=1, sticky="ew", padx=6, pady=6)

        # Data freshness one-liner (right, clickable)
        self.freshness_lbl = tk.Label(
            bar, text="checking data…", bg=PANEL, fg=DIM,
            font=self.f_mono, cursor="hand2", anchor="e")
        self.freshness_lbl.grid(row=0, column=2, sticky="e", padx=(6, 12), pady=6)
        self.freshness_lbl.bind("<Button-1>", lambda e: self._show_freshness_popover())

        # Cache: mtime cache + last-popover closed time (debounce the click)
        self._fresh_mtimes: Dict[str, float] = {}
        self._fresh_window: Optional[tk.Toplevel] = None

    def _panel(self, parent: tk.Widget, title: str) -> Tuple[tk.Frame, tk.Label]:
        """Return (frame, title_label) so callers can append into the panel."""
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        outer.pack(fill="x", pady=6)
        title_lbl = tk.Label(outer, text=title, bg=PANEL, fg=ACCENT,
                             font=self.f_label, anchor="w")
        title_lbl.pack(fill="x", padx=10, pady=(8, 4))
        return outer, title_lbl

    # ── Left column ─────────────────────────────────────────────────────
    def _build_left(self) -> None:
        # Banner art header
        banner = _render_banner(self.left)
        banner.pack(fill="x", pady=(4, 8))
        # Active session (NEW — surfaces which session/profile is in use).
        _, self.sess_title = self._panel(self.left, "ACTIVE SESSION")
        self.sess_pid_lbl = tk.Label(self.sess_title, text="(none)",
                                     bg=PANEL, fg=SUCCESS,
                                     font=self.f_label_xl, anchor="w")
        self.sess_pid_lbl.pack(fill="x", padx=10, pady=(2, 4))
        self.sess_detail_lbl = tk.Label(self.sess_title, text="",
                                        bg=PANEL, fg=FG, font=self.f_mono,
                                        anchor="w", justify="left",
                                        wraplength=440)
        self.sess_detail_lbl.pack(fill="x", padx=10, pady=(0, 8))
        # Identity / state
        _, self.ov_title = self._panel(self.left, "OVERSEER")
        self.ov_dot_lbl = tk.Label(self.ov_title, text="●", bg=PANEL, fg=DIM,
                                   font=self.f_mono_l, width=2)
        self.ov_dot_lbl.grid(row=0, column=0, sticky="w", padx=10, pady=2)
        self.ov_state_lbl = tk.Label(self.ov_title, text="starting…", bg=PANEL,
                                     fg=FG, font=self.f_label_l,
                                     anchor="w")
        self.ov_state_lbl.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        # Use pack on a child Frame for cleaner grid in panel
        body = tk.Frame(self.ov_title, bg=PANEL)
        body.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 8))
        self.ov_desc_lbl = tk.Label(body, text="", bg=PANEL, fg=FG,
                                    font=self.f_mono, anchor="w",
                                    justify="left", wraplength=440)
        self.ov_desc_lbl.pack(fill="x")
        self.ov_stats_lbl = tk.Label(body, text="", bg=PANEL, fg=DIM,
                                     font=self.f_mono, anchor="w",
                                     justify="left", wraplength=440)
        self.ov_stats_lbl.pack(fill="x", pady=(2, 0))
        self.ov_model_lbl = tk.Label(body, text="", bg=PANEL, fg=ICE,
                                     font=self.f_mono, anchor="w")
        self.ov_model_lbl.pack(fill="x", pady=(2, 0))
        self.ov_title.columnconfigure(1, weight=1)

        # Tips (rotates every 15s)
        _, tip_title = self._panel(self.left, "TIPS")
        self.tip_lbl = tk.Label(tip_title, text="💡 " + _rotating_tip(),
                                bg=PANEL, fg=DIM, font=self.f_tip,
                                anchor="w", justify="left", wraplength=440)
        self.tip_lbl.pack(fill="x", padx=10, pady=(0, 8))

    # ── Middle column ───────────────────────────────────────────────────
    def _build_middle(self) -> None:
        # Tok/s sparkline (decode rate as solid line, prompt-eval rate as
        # dashed lighter line on the same axis when both are reported).
        _, tok_title = self._panel(self.mid, "TOKENS / SECOND (60s, solid=decode, dashed=prompt)")
        self.spark_tok = Sparkline(tok_title, width=560, height=90,
                                   color=ACTIVE, color2=ICE)
        self.spark_tok.pack(fill="x", padx=10, pady=(0, 8))
        # VRAM bar
        _, vram_title = self._panel(self.mid, "VRAM (NVIDIA GPU — by process)")
        self.vram_bar = VRAMBar(vram_title, width=560, height=80)
        self.vram_bar.pack(fill="x", padx=10, pady=(0, 8))
        # Big-model step bar
        _, step_title = self._panel(self.mid, "BIG MODEL — STEP COUNTER")
        self.step_bar = StepBar(step_title, width=560, height=150)
        self.step_bar.pack(fill="x", padx=10, pady=(0, 8))
        # Minify savings
        self._build_minify_panel()
        # Plan tracker
        _, plan_title = self._panel(self.mid, "PLAN TRACKER")
        self.plan_lbl = tk.Label(plan_title, text="(no plan set)", bg=PANEL,
                                 fg=DIM, font=self.f_mono, anchor="w",
                                 justify="left", wraplength=800)
        self.plan_lbl.pack(fill="x", padx=10, pady=(0, 8))

    def _build_minify_panel(self) -> None:
        _, m_title = self._panel(self.mid, "MINIFY SAVINGS (60s)")
        # Top row: big percentage + counters
        top = tk.Frame(m_title, bg=PANEL)
        top.pack(fill="x", padx=10, pady=(0, 4))
        self.minify_pct_lbl = tk.Label(top, text="—", bg=PANEL, fg=SUCCESS,
                                       font=("DejaVu Sans Mono", 32, "bold"),
                                       anchor="w")
        self.minify_pct_lbl.pack(side="left")
        self.minify_pct_unit = tk.Label(top, text="saved",
                                        bg=PANEL, fg=DIM,
                                        font=self.f_label, anchor="w")
        self.minify_pct_unit.pack(side="left", padx=(4, 18))
        self.minify_counters_lbl = tk.Label(top, text="",
                                            bg=PANEL, fg=FG,
                                            font=self.f_mono, anchor="w",
                                            justify="left")
        self.minify_counters_lbl.pack(side="left", fill="x", expand=True)
        # Sparkline of recent savings %
        self.spark_minify = Sparkline(m_title, width=560, height=80,
                                      color=SUCCESS)
        self.spark_minify.pack(fill="x", padx=10, pady=(0, 8))

    # ── Right column ────────────────────────────────────────────────────
    def _build_right(self) -> None:
        # Memory tiers
        _, mem_title = self._panel(self.right, "MEMORY TIERS")
        body = tk.Frame(mem_title, bg=PANEL)
        body.pack(fill="x", padx=10, pady=(0, 8))
        self.mem_hot = self._make_mem_row(body, "Hot",  HOT_FG)
        self.mem_warm = self._make_mem_row(body, "Warm", WARM_FG)
        self.mem_cold = self._make_mem_row(body, "Cold", COLD_FG)

        # Sessions list
        _, sess_title = self._panel(self.right, "ACTIVE SESSIONS")
        # Treeview with scrollbar-ish packing
        cols = ("pid", "model", "state", "idle")
        self.sess_tv = ttk.Treeview(sess_title, columns=cols, show="headings",
                                     height=4)
        for c, w in (("pid", 60), ("model", 90), ("state", 70), ("idle", 60)):
            self.sess_tv.heading(c, text=c.title())
            self.sess_tv.column(c, width=w, anchor="w")
        self.sess_tv.pack(fill="x", padx=10, pady=(0, 8))

        # Health alerts
        _, alert_title = self._panel(self.right, "HEALTH ALERTS")
        self.alerts_lbl = tk.Label(alert_title, text="(none)", bg=PANEL,
                                   fg=SUCCESS, font=self.f_mono, anchor="w",
                                   justify="left", wraplength=440)
        self.alerts_lbl.pack(fill="x", padx=10, pady=(0, 8))

        # Queue depth + scheduler
        _, q_title = self._panel(self.right, "QUEUE + SCHEDULE")
        self.q_lbl = tk.Label(q_title, text="—", bg=PANEL, fg=FG,
                              font=self.f_mono, anchor="w",
                              justify="left", wraplength=440)
        self.q_lbl.pack(fill="x", padx=10, pady=(0, 8))

    def _make_mem_row(self, parent, label: str, color: str) -> Dict[str, Any]:
        """Build a Hot/Warm/Cold row with label, count, and a tiny bar."""
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        lbl = tk.Label(row, text=f"{label}", bg=PANEL, fg=color,
                       font=("DejaVu Sans Mono", 14, "bold"), width=6, anchor="w")
        lbl.pack(side="left")
        count_lbl = tk.Label(row, text="—", bg=PANEL, fg=FG,
                             font=("DejaVu Sans Mono", 14), width=6, anchor="w")
        count_lbl.pack(side="left")
        bar = tk.Canvas(row, height=18, bg=BG, highlightthickness=0, bd=0)
        bar.pack(side="left", fill="x", expand=True)
        cap_lbl = tk.Label(row, text="/ —", bg=PANEL, fg=DIM,
                           font=("DejaVu Sans Mono", 12), anchor="w", width=10)
        cap_lbl.pack(side="left", padx=(6, 0))
        return {"label": lbl, "count": count_lbl, "bar": bar, "cap": cap_lbl}

    def _draw_mem_bar(self, row: Dict[str, Any], value: int, cap: int,
                       color: str) -> None:
        bar: tk.Canvas = row["bar"]
        bar.delete("all")
        bar.update_idletasks()
        w = bar.winfo_width()
        h = 14
        if w <= 1:
            w = 200
        frac = (value / cap) if cap > 0 else 0.0
        frac = max(0.0, min(1.0, frac))
        bar.create_rectangle(0, 0, w * frac, h, fill=color, outline=BORDER)
        bar.create_rectangle(w * frac, 0, w, h, fill=BORDER, outline=BORDER)

    # ── Refresh tick ────────────────────────────────────────────────────
    def _tick(self) -> None:
        try:
            self._refresh()
        except Exception:
            pass
        self.after(self.POLL_MS, self._tick)

    def _refresh(self) -> None:
        # Single shared read path via lib.state_format.format_dashboard() —
        # same bundle tray + webui + statusline consume. Paint functions below
        # now receive the normalized bundle (dashboard) instead of raw file
        # contents. To add a new field, edit state_format.py once.
        bundle = _format_dashboard()
        state = bundle  # alias for readability in paint calls below
        overseer = _read_json(OVERSEER_STATE)
        daemon = (state.get("daemon") if isinstance(state.get("daemon"), dict) else {})
        steps = {"steps": state.get("big_steps", []),
                 "step_count": state.get("big_step_count", 0),
                 "tool_calls": state.get("big_tool_calls", 0)}
        plan = {"name": state.get("plan_name", ""),
                "total_steps": state.get("plan_total_steps", 0),
                "current_step": state.get("plan_current", 0)}
        # v0.5.3: pass real queue + schedule (was always []). The state
        # bundle has the live values; no need to re-read the disk files.
        queue = state.get("queue") or []
        schedule = state.get("schedule") or []
        # daemon has vram_by_proc — pass it via state for the VRAM bar.
        metrics = {"proxy_up": state.get("proxy_up", False),
                   "current_in_tps": state.get("current_in_tps", 0),
                   "current_out_tps": state.get("current_out_tps", 0),
                   "vram_big_mb": state.get("vram_big_mb", 0),
                   "vram_tiny_mb": state.get("vram_tiny_mb", 0),
                   "vram_other_mb": state.get("vram_other_mb", 0),
                   "vram_by_proc": (daemon.get("vram_by_proc") if isinstance(daemon.get("vram_by_proc"), dict) else {})}

        self._paint_session(daemon)
        self._paint_overseer(overseer, daemon, metrics)
        self._paint_charts(metrics, steps, daemon)
        self._paint_minify(metrics, overseer)
        self._paint_plan(plan)
        self._paint_mem(overseer)
        self._paint_alerts(overseer)
        self._paint_queue(queue, schedule)
        self._paint_tip(overseer, daemon)

        # ── Top bar: refresh timestamp + data freshness ─────────────────
        try:
            self.refresh_ts_lbl.config(
                text=f"last refreshed {time.strftime('%H:%M:%S')}",
                fg=ICE)
        except Exception:
            pass
        try:
            self._paint_freshness()
        except Exception:
            pass

    # ── Overseer + identity ─────────────────────────────────────────────
    def _paint_overseer(self, ov: Dict[str, Any], daemon: Dict[str, Any],
                        metrics: Dict[str, Any]) -> None:
        big = (daemon.get("big") or {})
        tiny = (daemon.get("tiny") or {})
        proxy = (daemon.get("proxy") or {})
        big_loaded = bool(big.get("running")) and bool(big.get("healthy"))
        tiny_loaded = bool(tiny.get("running")) or bool(tiny.get("healthy"))
        proxy_up = bool(proxy.get("running"))
        active = int(daemon.get("active_sessions", 0) or 0)
        idle = daemon.get("idle_sec")

        if not big_loaded and not tiny_loaded:
            dot, st, desc = DIM, "offline", "all models down"
        elif active > 0:
            dot, st, desc = ACTIVE, "thinking", "reasoning model running — session active"
        elif big_loaded:
            dot, st, desc = SUCCESS, "idle", "big model loaded, ready for chat"
        elif tiny_loaded:
            dot, st, desc = WARN, "loading", "warming up the big model"
        else:
            dot, st, desc = DIM, "idle", "daemon up, no model loaded"

        self.ov_dot_lbl.config(fg=dot)
        self.ov_state_lbl.config(text=st, fg=dot)
        self.ov_desc_lbl.config(text=desc)

        # Stats line
        parts: List[str] = []
        parts.append("big: " + ("ready" if big_loaded else "stopped"))
        parts.append("tiny: " + ("ready" if tiny_loaded else "stopped"))
        parts.append("proxy: " + ("up" if proxy_up else "down"))
        if isinstance(idle, (int, float)) and active > 0:
            parts.append(f"last req {int(idle)}s ago")
        active_sessions = daemon.get("sessions") or []
        if active_sessions:
            parts.append(f"{len(active_sessions)} session(s)")
        elif active:
            parts.append(f"{active} session(s)")
        self.ov_stats_lbl.config(text="  ·  ".join(parts))

        # Model path (just the basename)
        model_path = _model_id_daemon(daemon)
        model_short = (model_path.split("/")[-1] if "/" in model_path
                       else model_path.split("\\")[-1] if "\\" in model_path
                       else model_path)
        self.ov_model_lbl.config(text=f"🧠 {model_short}")

    # ── Charts (tok/s sparkline + VRAM + step counter) ──────────────────
    def _paint_charts(self, metrics: Dict[str, Any],
                      steps: Dict[str, Any],
                      ov: Optional[Dict[str, Any]] = None) -> None:
        # Decode rate (output tokens/s) — prefer the explicit out field, fall
        # back to the legacy current_tok_s which the proxy still aliases to it.
        out_tps = float(metrics.get("current_out_tps", 0.0)
                        or metrics.get("current_tok_s", 0.0) or 0.0)
        in_tps = float(metrics.get("current_in_tps", 0.0) or 0.0)
        self.toks_history.append(out_tps)
        self.toks_in_history.append(in_tps)
        self.spark_tok.set_series(self.toks_history, self.toks_in_history)

        used = int(metrics.get("vram_used_mib", 0) or 0) or None
        total = int(metrics.get("vram_total_mib", 0) or 0) or None
        # Per-process VRAM breakdown from daemon — when present, render the
        # stacked colour-coded bar (big / tiny / other); otherwise fall back
        # to the legacy single-colour view.
        vbp: Optional[Dict[str, int]] = None
        if isinstance(ov, dict):
            vbp = ov.get("vram_by_proc")
        self.vram_bar.draw(used, total, by_proc=vbp)

        step_list = steps.get("steps") or []
        cur_idx = int(steps.get("current", 0) or 0)
        self.step_bar.draw(step_list, cur_idx)

    # ── Minify panel ────────────────────────────────────────────────────
    def _paint_minify(self, metrics: Dict[str, Any],
                      ov: Dict[str, Any]) -> None:
        # Prefer the daemon-merged snapshot (state["minify"]) — keeps the
        # rolling history the proxy wrote, but lets the overseer also surface
        # lifetime totals. Fall back to the live proxy metrics.
        m = (ov.get("minify") if isinstance(ov.get("minify"), dict) else None) \
            or (metrics.get("minify") if isinstance(metrics.get("minify"), dict) else None) \
            or _read_json(MINIFY_STATS)
        if not isinstance(m, dict) or not m:
            self.minify_pct_lbl.config(text="—", fg=DIM)
            self.minify_pct_unit.config(text="no runs yet")
            self.minify_counters_lbl.config(text="")
            self.spark_minify.history = self.minify_history
            self.spark_minify._redraw()
            return
        ratio = float(m.get("ratio_pct", 0.0) or 0.0)
        saved = int(m.get("tokens_saved", 0) or 0)
        tin = int(m.get("tokens_in", 0) or 0)
        tout = int(m.get("tokens_out", 0) or 0)
        runs = int(m.get("runs", 0) or 0)
        color = (SUCCESS if ratio >= 8 else
                 ACCENT if ratio >= 3 else
                 DIM if runs == 0 else WARN)
        self.minify_pct_lbl.config(text=f"{ratio:.1f}%", fg=color)
        self.minify_pct_unit.config(text=("saved" if saved else "no savings yet"))
        self.minify_counters_lbl.config(
            text=(f"{saved:,} tok saved across {runs} run(s)\n"
                  f"in {tin:,} · out {tout:,} · last {float(m.get('last_saved_pct', 0.0)):.1f}%"))
        # Sparkline: rebuild from the snapshot's history_60s list each tick.
        hist = m.get("history_60s") or []
        # Seed deque from snapshot when under cap, otherwise use rolling deque.
        if hist:
            pts = [float(v) for (_t, v) in hist[-60:]]
            self.minify_history = deque(pts, maxlen=60)
        self.spark_minify.history = self.minify_history
        self.spark_minify._redraw()

    # ── Plan tracker ────────────────────────────────────────────────────
    def _paint_plan(self, plan: Dict[str, Any]) -> None:
        if not plan or plan.get("error") or not plan.get("name"):
            self.plan_lbl.config(text="(no plan set)", fg=DIM)
            return
        name = str(plan.get("name", "?"))[:60]
        total = int(plan.get("total_steps", 0) or 0)
        step = int(plan.get("current_step", 0) or 0)
        done = bool(plan.get("completed"))
        steps = plan.get("steps") or []
        current_label = (steps[step - 1] if 0 < step <= len(steps) else "—")
        head = (f"{'✅' if done else '➡️'} '{name}'  Step {step}/{total}")
        lines = [head]
        if not done and step > 0:
            lines.append(f"  now: {current_label[:80]}")
        # Show prev/next steps too
        if 0 < step - 1 <= len(steps):
            lines.append(f"  prev: {steps[step - 2][:80]}")
        if step < len(steps):
            lines.append(f"  next: {steps[step][:80]}")
        self.plan_lbl.config(text="\n".join(lines), fg=FG if not done else SUCCESS)

    # ── Memory tiers ────────────────────────────────────────────────────
    def _paint_mem(self, ov: Dict[str, Any]) -> None:
        # Reuse overseer._get_memory_stats when available; otherwise peek at
        # the structured state ("last memory" snapshot the overseer logs).
        try:
            from lib import overseer
            stats = overseer._get_memory_stats()
        except Exception:
            stats = {"hot": 0, "warm": 0, "cold": 0,
                     "hot_bytes": 0, "warm_bytes": 0}
        # No caps (HARD RULE 2026-08-11): every prompt appends, never trimmed.
        # The dashboard shows count + bytes (MB) instead of "/N" fullness.
        self.mem_hot["count"].config(text=str(stats["hot"]))
        self.mem_warm["count"].config(text=str(stats["warm"]))
        self.mem_cold["count"].config(text=str(stats["cold"]))
        hot_mb = stats.get("hot_bytes", 0) / (1024 * 1024)
        warm_mb = stats.get("warm_bytes", 0) / (1024 * 1024)
        self.mem_hot["cap"].config(text=f"{hot_mb:.1f} MB")
        self.mem_warm["cap"].config(text=f"{warm_mb:.1f} MB")
        self.mem_cold["cap"].config(text="unlimited")
        # Bars: render at UI-friendly proportions — 1.0 = full bar width.
        # Pick soft targets so the bar is informative, not capped-at-N.
        SOFT_HOT = 1000.0   # 1k entries = full bar
        SOFT_WARM = 5000.0  # 5k entries = full bar
        self._draw_mem_bar(self.mem_hot,  stats["hot"],  SOFT_HOT,  HOT_FG)
        self._draw_mem_bar(self.mem_warm, stats["warm"], SOFT_WARM, WARM_FG)
        # Cold is unbounded — show count only; bar is a separator.
        ratio = min(stats["cold"] / 100.0, 1.0)
        self.mem_cold["bar"].delete("all")
        w = self.mem_cold["bar"].winfo_width() or 200
        h = 14
        self.mem_cold["bar"].create_rectangle(0, 0, w * ratio, h,
                                              fill=COLD_FG, outline=BORDER)
        self.mem_cold["bar"].create_rectangle(w * ratio, 0, w, h,
                                              fill=BORDER, outline=BORDER)

    # ── Sessions (active one, in the left column) ──────────────────────
    def _paint_session(self, daemon: Dict[str, Any]) -> None:
        sess = daemon.get("session") or {}
        if not sess:
            self.sess_pid_lbl.config(text="(no session)", fg=DIM)
            self.sess_detail_lbl.config(
                text="no CLI / Claude session is running against this daemon",
                fg=DIM)
            return
        pid = sess.get("pid", "?")
        kind = sess.get("kind", "?")
        etime = sess.get("etime", "?")
        profile = sess.get("profile") or "default"
        mcp = sess.get("mcp_config") or ""
        model_alias = sess.get("model_alias") or daemon.get("model_alias") or ""
        big_alias = ""
        try:
            big = (daemon.get("big") or {})
            big_alias = big.get("alias") or ""
        except Exception:
            pass
        head = f"pid {pid}  ·  {etime}  ·  {kind}"
        self.sess_pid_lbl.config(
            text=head,
            fg=SUCCESS if kind == "cli" else ACTIVE)
        # Profile + model line
        detail_parts: List[str] = []
        detail_parts.append(f"profile: {profile}")
        if model_alias:
            detail_parts.append(f"model: {model_alias}")
        elif big_alias:
            detail_parts.append(f"model alias: {big_alias}")
        if mcp:
            short_mcp = mcp.split("/")[-1] if "/" in mcp else mcp
            detail_parts.append(f"mcp: {short_mcp}")
        self.sess_detail_lbl.config(text="  ·  ".join(detail_parts), fg=FG)

    # ── Treeview sessions table ─────────────────────────────────────────
    def _populate_sessions_table(self, daemon: Dict[str, Any]) -> None:
        # Clear and rebuild — Treeview is cheap; we keep the cap tiny (4).
        for iid in self.sess_tv.get_children():
            self.sess_tv.delete(iid)
        sessions = daemon.get("sessions") or []
        if not sessions:
            active = int(daemon.get("active_sessions", 0) or 0)
            if active == 0:
                self.sess_tv.insert("", "end", values=("—", "—", "idle", "—"))
                return
            self.sess_tv.insert("", "end", values=("?", "?", "active", "0s"))
            return
        for s in sessions[:4]:
            self.sess_tv.insert("", "end", values=(
                str(s.get("pid", "?")),
                str(s.get("profile") or "default")[:18],
                str(s.get("etime", "?"))[:12],
                str(s.get("model_alias") or s.get("comm", "?"))[:18],
            ))

    # ── Alerts ──────────────────────────────────────────────────────────
    def _paint_alerts(self, ov: Dict[str, Any]) -> None:
        events = ov.get("health_events") or []
        if not events:
            self.alerts_lbl.config(text="✅ all green", fg=SUCCESS)
            return
        last = events[-1].get("alerts") or []
        if not last:
            self.alerts_lbl.config(text="✅ all green", fg=SUCCESS)
            return
        # v0.5.3: distinguish "advisory only" from real alerts. Anything
        # containing "advisory only" gets the warn color (yellow), not red.
        # Real alerts (no advisory marker) stay red.
        has_real = any("advisory" not in a.lower() for a in last)
        if has_real:
            text = "\n".join(f"🔴 {a[:120]}" for a in last[:5])
            self.alerts_lbl.config(text=text, fg=ALERT)
        else:
            text = "\n".join(f"🟡 {a[:120]}" for a in last[:5])
            self.alerts_lbl.config(text=text, fg=WARN)

    # ── Queue / schedule ────────────────────────────────────────────────
    def _paint_queue(self, queue: List[Dict[str, Any]],
                     schedule: Optional[List[Dict[str, Any]]] = None) -> None:
        # v0.5.3: real queue + schedule arrays from the formatted bundle.
        # (Previously the caller passed queue=[] and the painter re-read the
        # schedule file; counts were always 0.)
        n_total = len(queue) if isinstance(queue, list) else 0
        n_pending = sum(1 for t in (queue or [])
                        if isinstance(t, dict) and t.get("status") == "queued")
        n_sched = len(schedule) if isinstance(schedule, list) else 0
        if n_total == 0 and n_sched == 0:
            self.q_lbl.config(text="📭 no queue, no scheduled tasks\n(add one via the CLI: cortexagent schedule add ...)",
                              fg=DIM)
            return
        text = (f"queue: {n_pending} pending / {n_total} total\n"
                f"schedule: {n_sched} entries")
        self.q_lbl.config(text=text, fg=FG)

    # ── Data freshness (top bar) ────────────────────────────────────────
    # Per-file freshness thresholds (seconds). The user wanted to see WHY
    # a panel is empty — this is the single source of truth. Mtime-based;
    # no writer changes needed in lib/overseer.py.
    _FRESHNESS_SOURCES = (
        # (relative_path, fresh_sec, must_exist)
        ("overseer_state.json",            60,  True),
        ("big_model_steps.json",          120,  True),
        ("minify_stats.json",             120,  True),
        ("overseer_queue.json",           300, False),
        ("overseer_schedule.json",        600, False),
        ("overseer_plan.json",            600, False),
        ("workflow_state.json",           600, False),
        ("state/active_model.json",        60, False),
    )

    def _check_freshness(self) -> List[Dict[str, Any]]:
        """Classify each backing file as fresh / stale / missing.

        Returns a list of dicts: {name, age, status, threshold, missing}.
        """
        now = time.time()
        rows: List[Dict[str, Any]] = []
        state_dir = STATE_DIR
        for rel, fresh_sec, must_exist in self._FRESHNESS_SOURCES:
            p = state_dir / rel
            if not p.exists():
                rows.append({"name": rel, "age": None, "threshold": fresh_sec,
                             "status": "missing", "missing": True,
                             "required": must_exist})
                continue
            try:
                mtime = p.stat().st_mtime
            except Exception:
                rows.append({"name": rel, "age": None, "threshold": fresh_sec,
                             "status": "missing", "missing": True,
                             "required": must_exist})
                continue
            age = max(0.0, now - mtime)
            rows.append({"name": rel, "age": age, "threshold": fresh_sec,
                         "status": "fresh" if age <= fresh_sec else "stale",
                         "missing": False, "required": must_exist})
        return rows

    def _paint_freshness(self) -> None:
        try:
            rows = self._check_freshness()
        except Exception:
            return
        n_fresh = sum(1 for r in rows if r["status"] == "fresh")
        n_stale = sum(1 for r in rows if r["status"] == "stale")
        n_miss = sum(1 for r in rows if r["status"] == "missing"
                     and r["required"])
        # Cache rows for the popover
        self._fresh_mtimes = {r["name"]: r["age"] for r in rows}
        if n_miss > 0:
            color, head = ALERT, f"🔴 {n_fresh} ok · {n_stale} stale · {n_miss} missing"
        elif n_stale > 0:
            color, head = WARN, f"🟡 {n_fresh} ok · {n_stale} stale"
        else:
            color, head = SUCCESS, f"🟢 {n_fresh} ok"
        try:
            self.freshness_lbl.config(text=f"data: {head}", fg=color)
        except Exception:
            pass

    def _show_freshness_popover(self) -> None:
        """Click-to-expand detail of every backing file's mtime + status."""
        if self._fresh_window is not None:
            try:
                self._fresh_window.destroy()
            except Exception:
                pass
            self._fresh_window = None
        rows = self._check_freshness()
        win = tk.Toplevel(self)
        win.title("Data Sources — freshness")
        win.configure(bg=PANEL)
        win.attributes("-topmost", True)
        # Position near the freshness label
        try:
            x = self.freshness_lbl.winfo_rootx()
            y = self.freshness_lbl.winfo_rooty() + 28
            win.geometry(f"420x{40 + 18 * len(rows)}+{x - 380}+{y}")
        except Exception:
            win.geometry(f"420x{40 + 18 * len(rows)}")
        # Header
        tk.Label(win, text="DATA SOURCES", bg=PANEL, fg=ACCENT,
                 font=self.f_label, anchor="w").pack(
            fill="x", padx=10, pady=(8, 4))
        tk.Label(win, text="mtime-based, no writes changed",
                 bg=PANEL, fg=DIM, font=self.f_mono_s, anchor="w").pack(
            fill="x", padx=10, pady=(0, 6))
        # One row per file
        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        for i, r in enumerate(rows):
            if r["status"] == "fresh":
                dot, color = "🟢", SUCCESS
            elif r["status"] == "stale":
                dot, color = "🟡", WARN
            else:
                dot, color = "🔴", ALERT
            age_s = r["age"]
            if age_s is None:
                age_str = "missing"
            elif age_s < 60:
                age_str = f"{int(age_s)}s"
            elif age_s < 3600:
                age_str = f"{int(age_s / 60)}m"
            else:
                age_str = f"{age_s / 3600:.1f}h"
            req = "" if r["required"] else "  (optional)"
            txt = f"{dot} {r['name']:<28} {age_str:>6}  / {r['threshold']}s{req}"
            tk.Label(body, text=txt, bg=PANEL, fg=color,
                     font=self.f_mono_s, anchor="w").pack(fill="x")
        # Hint
        tk.Label(win, text="click anywhere to close",
                 bg=PANEL, fg=DIM, font=self.f_mono_s, anchor="w").pack(
            fill="x", padx=10, pady=(0, 8))
        win.bind("<FocusOut>", lambda e: self._close_freshness_popover())
        win.bind("<Button-1>", lambda e: self._close_freshness_popover())
        self._fresh_window = win

    def _close_freshness_popover(self) -> None:
        if self._fresh_window is not None:
            try:
                self._fresh_window.destroy()
            except Exception:
                pass
            self._fresh_window = None

    # ── Tip ─────────────────────────────────────────────────────────────
    def _paint_tip(self, ov: Dict[str, Any], daemon: Dict[str, Any]) -> None:
        active = int(daemon.get("active_sessions", 0) or 0)
        if active == 0:
            self.tip_lbl.config(text="💡 " + _rotating_tip(), fg=DIM)
            return
        summary = (ov.get("last_llm_summary") or "").strip()
        if summary:
            self.tip_lbl.config(
                text=f"💡 last summary:\n   {summary[:180]}",
                fg=DIM)
        else:
            self.tip_lbl.config(text="💡 session in progress…", fg=DIM)


# ── Launcher helpers ──────────────────────────────────────────────────────
def open_dashboard() -> None:
    """Open the dashboard window. Safe to call from a non-tk thread? — NO: Tk
    roots must live in the calling thread. Tray callers should spawn a Thread
    that runs `open_dashboard()` directly (single-thread per Tk root)."""
    Dashboard().mainloop()


def open_in_thread() -> threading.Thread:
    t = threading.Thread(target=open_dashboard, daemon=True, name="tray-dashboard")
    t.start()
    return t


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        # Soft-fail: the tray service may still launch us on a graphical
        # session where XDG_SESSION_TYPE is set without DISPLAY.
        if not os.environ.get("XDG_SESSION_TYPE"):
            print("no display available — dashboard requires a graphical session",
                  file=sys.stderr)
            return 1
    open_dashboard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
