"""CortexAgent tray popout dashboard.

NOT the same as the :8090 webui (which is deferred). This is a small
popout window that opens from the system tray icon and shows the
overseer state + big-model step counter + a rotating idle tip.

Reads state from:
  - Daemon control socket (lib/control.send_request)
    → big/tiny/proxy health, active_sessions, idle_sec, last_request
  - ~/.cortexagent/overseer_state.json
    → last_llm_summary, alerts, health_events, scheduler entries
  - lib/overseer._task_state() (or equivalent) for big-model step counter

The dashboard polls every 1s. Window is ~420×340, dark themed to match
the brand. Closes with the window-manager X or the Esc key.

Implementation notes:
  - Pure stdlib (tkinter). No new deps.
  - The "step 3 of 5" big-model counter is read from a small JSON file
    the big model writes via lib/grammar_proxy.py thinking-bottom-line
    (R3) — see STATE_FILE below. If the file is missing, the counter
    shows "—" / "no active step".
  - Rotating tip cycles every 15s while overseer is idle. Picks from
    _TIPS pool deterministically by (time // 15) % len.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Any, Dict, List, Optional

# ── Paths ────────────────────────────────────────────────────────────────────
HOME = Path.home()
STATE_DIR = HOME / ".cortexagent"
OVERSEER_STATE = STATE_DIR / "overseer_state.json"
BIG_STEP_STATE = STATE_DIR / "big_model_steps.json"

# ── Color palette (matches brand: gold accent, dark glass) ──────────────────
BG = "#0d0d12"
PANEL = "#15151c"
BORDER = "#2a2a36"
FG = "#e8e8f0"
DIM = "#7a7a8c"
ACCENT = "#c9a84c"  # gold
SUCCESS = "#5ec47a"
WARN = "#e0a23a"
ALERT = "#d65a5a"
ACTIVE = "#5aa8e0"

# ── Idle-tip rotation pool ──────────────────────────────────────────────────
# Deterministic cycle — same tip at the same time across refreshes. Caps at 30.
_TIPS: List[str] = [
    "Tip: type 'show code' in any prompt to reveal hidden code blocks.",
    "Tip: R3 thinking line appears under each response — it's the model's tool trail.",
    "Tip: Big model stays loaded by default — set idle_unload_sec to free VRAM.",
    "Tip: 'bin/cortexagent' launches the CLI; the daemon owns the model slot.",
    "Tip: tray icon 🐺 → right-click for status, double-click for this dashboard.",
    "Tip: :8090 webui is deferred — use this dashboard for live overseer state.",
    "Tip: fallback_model = '' means no swap; big must fit VRAM or chat fails.",
    "Tip: press Ctrl+C in the CLI for graceful session-end (no idle-unload race).",
    "Tip: edits to ~/.cortexagent/cortexagent.conf take effect on next session-start.",
    "Tip: overseer watchdog won't unload big if idle < 300s with active sessions.",
    "Tip: cortexllm memory is shared across all platforms — Claude, OpenClaw, webchat.",
    "Tip: cold memory rules auto-load at session start — see agent_critical_rules.",
    "Tip: hot memory is platform-specific; warm is consolidated; cold is curated.",
    "Tip: lib/minify + slimtoken dedup → typical 30-50% prompt-token savings.",
    "Tip: --kv-unified lets the 35B fit 128K ctx in ~14.7 GB VRAM on a 16 GB card.",
    "Tip: image / video gen runs in-process via lib/diffusion_backend.py — no swap.",
    "Tip: tray icon shows green dot when big is loaded, gray when idle.",
    "Tip: 'Reload models' in the tray menu reloads big + reloads config.",
    "Tip: 'Reload config' re-reads cortexagent.conf without restarting the daemon.",
    "Tip: 'Restart overseer' kills and restarts the overseer service.",
    "Tip: double-click the tray icon to toggle this dashboard.",
    "Tip: pressing Esc closes this window. The tray icon stays.",
    "Tip: live install uses the UD fine-tune; github copy uses base IQ3_S.",
    "Tip: PII scrub runs on every commit via tests/run_smoke.py PII detector.",
    "Tip: bin/cortexagent is a thin wrapper — the daemon owns the model slot.",
    "Tip: lib/grammar_proxy.py emits R3 thinking-bottom-line to stderr after stream.",
    "Tip: idle_unload_sec=0 disables the idle watcher entirely (shipped default).",
    "Tip: 'session-reset' from the overseer forces daemon to release leaked sessions.",
    "Tip: ctx-fill bar at the top shows % of 128K context used by the big model.",
    "Tip: this tip will rotate in 15 seconds — different tip, same window.",
]


def _rotating_tip() -> str:
    bucket = int(time.time() // 15)
    return _TIPS[bucket % len(_TIPS)]


# ── State readers ──────────────────────────────────────────────────────────
def _read_overseer_state() -> Dict[str, Any]:
    try:
        with OVERSEER_STATE.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _read_big_steps() -> Dict[str, Any]:
    try:
        with BIG_STEP_STATE.open() as f:
            return json.load(f)
    except Exception:
        return {}


def _read_daemon_status() -> Dict[str, Any]:
    try:
        # Ensure repo is on sys.path so we can import lib.control
        repo = Path(__file__).resolve().parent.parent
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from lib import control
        return control.send_request("status", timeout=2)
    except Exception:
        return {}


# ── Main dashboard window ───────────────────────────────────────────────────
class Dashboard(tk.Tk):
    """Popout tray dashboard. Tkinter Toplevel-style but as a Tk root so it's
    independent and doesn't fight with any existing main loop."""

    POLL_MS = 1000  # refresh cadence

    def __init__(self) -> None:
        super().__init__()
        self.title("CortexAgent — Overseer")
        self.configure(bg=BG)
        self.geometry("440x360")
        self.minsize(420, 320)
        self.resizable(False, False)

        # Try to round the window corners / set transparency on supported WMs
        try:
            self.attributes("-type", "dialog")
        except Exception:
            pass

        # Bind Esc to close
        self.bind("<Escape>", lambda e: self.destroy())

        # Fonts
        self.f_mono = tkfont.Font(family="DejaVu Sans Mono", size=9)
        self.f_mono_b = tkfont.Font(family="DejaVu Sans Mono", size=9, weight="bold")
        self.f_label = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.f_tip = tkfont.Font(family="DejaVu Sans", size=9, slant="italic")

        # Layout: top panel (overseer) + middle panel (big model) + bottom tip
        self._build_overseer_panel()
        self._build_big_model_panel()
        self._build_tip_panel()

        # First paint + schedule refresh
        self._refresh()
        self.after(self.POLL_MS, self._tick)

    # ── UI construction ──────────────────────────────────────────────────
    def _panel(self, parent: tk.Widget, title: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        title_lbl = tk.Label(frame, text=title, bg=PANEL, fg=ACCENT,
                              font=self.f_label, anchor="w")
        title_lbl.pack(fill="x", padx=10, pady=(8, 4))
        return frame

    def _build_overseer_panel(self) -> None:
        self.ov_frame = self._panel(self, "OVERSEER")
        self.ov_frame.pack(fill="x", padx=10, pady=(10, 6))

        # State row: ● idle / thinking / switching + plain-language description
        row1 = tk.Frame(self.ov_frame, bg=PANEL)
        row1.pack(fill="x", padx=10, pady=(0, 2))
        self.ov_dot = tk.Label(row1, text="●", bg=PANEL, fg=DIM,
                                font=self.f_mono_b, width=2)
        self.ov_dot.pack(side="left")
        self.ov_state = tk.Label(row1, text="idle", bg=PANEL, fg=DIM,
                                  font=self.f_mono_b, width=10, anchor="w")
        self.ov_state.pack(side="left")
        self.ov_desc = tk.Label(row1, text="starting up…", bg=PANEL, fg=FG,
                                 font=self.f_mono, anchor="w")
        self.ov_desc.pack(side="left", fill="x", expand=True)

        # Stats row: small numbers as plain text (no MiB / port numerals)
        self.ov_stats = tk.Label(self.ov_frame, text="", bg=PANEL, fg=DIM,
                                  font=self.f_mono, anchor="w", justify="left")
        self.ov_stats.pack(fill="x", padx=10, pady=(4, 8))

    def _build_big_model_panel(self) -> None:
        self.big_frame = self._panel(self, "BIG MODEL (reasoning)")
        self.big_frame.pack(fill="x", padx=10, pady=6)

        # Progress bar (▓▓▓▓░░ style)
        self.big_bar = tk.Label(self.big_frame, text="", bg=PANEL, fg=ACCENT,
                                 font=self.f_mono, anchor="w")
        self.big_bar.pack(fill="x", padx=10, pady=(0, 4))

        # Step list
        self.big_steps = tk.Label(self.big_frame, text="(no active task)",
                                   bg=PANEL, fg=FG, font=self.f_mono,
                                   anchor="w", justify="left")
        self.big_steps.pack(fill="x", padx=10, pady=(0, 8))

    def _build_tip_panel(self) -> None:
        self.tip_frame = tk.Frame(self, bg=BG)
        self.tip_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tip_lbl = tk.Label(self.tip_frame, text="", bg=BG, fg=DIM,
                                 font=self.f_tip, anchor="w", justify="left",
                                 wraplength=400)
        self.tip_lbl.pack(fill="both", expand=True)

    # ── Refresh tick ─────────────────────────────────────────────────────
    def _tick(self) -> None:
        self._refresh()
        self.after(self.POLL_MS, self._tick)

    def _refresh(self) -> None:
        try:
            overseer = _read_overseer_state()
            steps = _read_big_steps()
            daemon = _read_daemon_status()

            self._paint_overseer(overseer, daemon)
            self._paint_big_model(steps, daemon)
            self._paint_tip(overseer, daemon)
        except Exception:
            # Never crash the dashboard on a bad poll
            pass

    # ── Overseer panel ──────────────────────────────────────────────────
    def _paint_overseer(self, ov: Dict[str, Any], daemon: Dict[str, Any]) -> None:
        big = (daemon.get("big") or {})
        tiny = (daemon.get("tiny") or {})
        proxy = (daemon.get("proxy") or {})
        big_loaded = bool(big.get("running")) and bool(big.get("healthy"))
        tiny_loaded = bool(tiny.get("running")) or bool(tiny.get("healthy"))
        proxy_up = bool(proxy.get("running"))
        active = int(daemon.get("active_sessions", 0) or 0)
        idle = daemon.get("idle_sec")

        # Dot + state label
        if not big_loaded and not tiny_loaded:
            self.ov_dot.config(fg=DIM)
            self.ov_state.config(text="offline", fg=DIM)
            desc = "all models down"
        elif active > 0:
            self.ov_dot.config(fg=ACTIVE)
            self.ov_state.config(text="thinking", fg=ACTIVE)
            desc = f"coordinating the reasoning model — session active"
        elif big_loaded:
            self.ov_dot.config(fg=SUCCESS)
            self.ov_state.config(text="idle", fg=SUCCESS)
            desc = "big model loaded, ready for chat"
        elif tiny_loaded:
            self.ov_dot.config(fg=WARN)
            self.ov_state.config(text="loading", fg=WARN)
            desc = "warming up the big model"
        else:
            self.ov_dot.config(fg=DIM)
            self.ov_state.config(text="idle", fg=DIM)
            desc = "daemon up, no model loaded"

        self.ov_desc.config(text=desc)

        # Stats line — plain language, no raw numerals
        parts: List[str] = []
        if big_loaded:
            parts.append("big: ready")
        else:
            parts.append("big: stopped")
        if tiny_loaded:
            parts.append("tiny: ready")
        else:
            parts.append("tiny: stopped")
        if proxy_up:
            parts.append("proxy: up")
        if isinstance(idle, (int, float)) and active > 0:
            parts.append(f"last request {int(idle)}s ago")
        alerts = (ov.get("health_events") or [])
        if alerts:
            last_alerts = alerts[-1].get("alerts") or []
            for a in last_alerts[:1]:
                parts.append(f"⚠ {a[:60]}")
        self.ov_stats.config(text="  ·  ".join(parts) if parts else "")

    # ── Big-model panel ─────────────────────────────────────────────────
    def _paint_big_model(self, steps: Dict[str, Any], daemon: Dict[str, Any]) -> None:
        big_running = bool((daemon.get("big") or {}).get("running"))
        step_list: List[Dict[str, str]] = steps.get("steps") or []
        step_idx = int(steps.get("current", 0) or 0)
        total = len(step_list)

        if not big_running:
            self.big_bar.config(text="big model: stopped", fg=DIM)
            self.big_steps.config(text="(big not loaded — start a chat to load)",
                                   fg=DIM)
            return

        if total == 0:
            self.big_bar.config(text="big model: ready · no active task", fg=SUCCESS)
            self.big_steps.config(text="(waiting for next request)", fg=DIM)
            return

        # Progress bar: ▓ for done/current, ░ for pending
        bar_chars: List[str] = []
        for i in range(total):
            if i < step_idx:
                bar_chars.append("▓")
            elif i == step_idx:
                bar_chars.append("▓")
            else:
                bar_chars.append("░")
        bar = "".join(bar_chars)
        pct = int((step_idx + 1) / max(total, 1) * 100)
        self.big_bar.config(
            text=f"{bar}  Step {step_idx + 1} of {total}  ({pct}%)",
            fg=ACCENT,
        )

        # Step list with status markers
        rows: List[str] = []
        for i, s in enumerate(step_list[:7]):  # cap at 7
            label = s.get("label", f"step {i+1}")
            if i < step_idx:
                mark = "✓"
                color_indicator = "✓"
            elif i == step_idx:
                mark = "●"
                color_indicator = "●"
            else:
                mark = "○"
                color_indicator = "○"
            rows.append(f"  {mark} {label}")
        text = "\n".join(rows) if rows else "(no active task)"
        self.big_steps.config(text=text, fg=FG)

    # ── Tip panel ───────────────────────────────────────────────────────
    def _paint_tip(self, ov: Dict[str, Any], daemon: Dict[str, Any]) -> None:
        active = int(daemon.get("active_sessions", 0) or 0)
        if active == 0:
            # Idle: show rotating tip
            self.tip_lbl.config(text="💡 " + _rotating_tip(), fg=DIM)
        else:
            # Active: show last summary from overseer if any
            summary = (ov.get("last_llm_summary") or "").strip()
            if summary:
                self.tip_lbl.config(
                    text=f"💡 last overseer summary:\n   {summary[:180]}",
                    fg=DIM,
                )
            else:
                self.tip_lbl.config(text="💡 session in progress…", fg=DIM)


# ── Launcher helpers ──────────────────────────────────────────────────────
def open_dashboard() -> None:
    """Open the dashboard window. Safe to call from a non-tk thread (creates
    a Tk root in the calling thread)."""
    Dashboard().mainloop()


def open_in_thread() -> threading.Thread:
    """Open the dashboard in a background thread (Tk isn't thread-safe across
    roots, so callers from the tray thread should use open_dashboard() directly)."""
    t = threading.Thread(target=open_dashboard, daemon=True)
    t.start()
    return t


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    """Open the dashboard directly: `python -m lib.tray_dashboard`"""
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("no display available — dashboard requires a graphical session",
              file=sys.stderr)
        return 1
    open_dashboard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
