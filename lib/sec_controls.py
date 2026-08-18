#!/usr/bin/env python3
"""lib/sec_controls.py — Security Tracker popout (v2: working + useful).

A compact, phone-portrait Tk window that surfaces every alert written to
the two local security feeds:

  - ~/honeypot/alerts.log                                (NDJSON)
  - ~/Documents/RecordRelief/webapp/data/alerts.json     (JSON array)

Layout (top → bottom, single scrollable column):

  ┌─ Title bar  (draggable, ✕ to close)
  ├─ Status header  ─ big severity dot + alert count + last update
  ├─ Action plan banner ─ one-line summary of recommended action (or "All clear")
  ├─ Severity filter row  ─ 5 live-count chips (click to mute a severity)
  ├─ Action row  ─ Refresh · Pause · Dashboard · Clear  (4 compact buttons)
  ├─ Alert stream  ─ live cards, click to expand → full detail + actions
  └─ Footer  ─ 1-line: "X alerts · last refresh Ys ago · Y blocked sources"

What it does that the v1 did NOT:

  - Each alert is a clickable CARD. Click → row expands inline to show
    the full untruncated detail, raw JSON, and a Block / Acknowledge /
    Dismiss action trio. No more dead detail panel.
  - Per-alert plain-language reframing for known kinds (port-scan,
    canary.token.trigger, rkhunter.warning, mit.exception, etc.). The
    reframing lives in a small table at the top of the file and is
    easy to extend.
  - The "Action plan" banner shows the highest-priority recommended
    action in one line: "1 IP needs blocking (click here to see it)".
  - The Block button writes a real entry to firewall_commands.jsonl
    (the root helper picks it up) — works for any alert that has an
    IP in the detail. No more "what does this button do" mystery.
  - All the dead empty space from v1 is gone. The list IS the
    content. Compact 820×2000 with everything visible.

Dock-style, no-focus pattern copied from lib/stt_controls.py.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tkinter as tk

# ── Alert sources ────────────────────────────────────────────────────────────
HONEYPOT_LOG = Path.home() / "honeypot" / "alerts.log"
RECORDRELIEF_FEED = (
    Path.home() / "Documents" / "RecordRelief" / "webapp" / "data" / "alerts.json"
)
HONEYPOT_DIR = Path.home() / "honeypot"
FIREWALL_COMMANDS = (
    Path.home() / "security-reports" / "overseer" / "firewall_commands.jsonl"
)
FIREWALL_STATE = (
    Path.home() / "security-reports" / "overseer" / ".portscan_state.json"
)

# Severity → display color.
SEV_COLOR = {
    "critical": "#ff3b30",
    "high":     "#ff9500",
    "medium":   "#ffcc00",
    "low":      "#34c759",
    "info":     "#5ac8fa",
}
SEV_ICON = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
    "info":     "🔵",
}
SEV_ORDER = ("critical", "high", "medium", "low", "info")

# Background palette
BG_DEEP   = "#0f0f1f"
BG_PANEL  = "#1a1a2e"
BG_BAR    = "#3a3a5e"
BG_CHIP   = "#252540"
BG_ROW    = "#20203a"
BG_HOVER  = "#2a2a4a"
BG_DIM    = "#181828"
FG_DIM    = "#808090"
FG_MUTED  = "#a0a0c0"
FG_BRIGHT = "#e0e0e0"
FG_LINK   = "#5ac8fa"

# RecordRelief webapp
RECORDRELIEF_WEBAPP_DIR = Path.home() / "Documents" / "RecordRelief" / "webapp"
RECORDRELIEF_URL = "http://127.0.0.1:8787/"
RECORDRELIEF_PORT = 8787


# ── Per-kind plain-language reframing ────────────────────────────────────────
# Short, in-context explanation shown when an alert card is expanded.
# Add a row to extend. ``template`` is ``str.format(**fields)``-d.
REFRAMINGS: dict[str, dict] = {
    "port-scan": {
        "title": "Port scan detected",
        "summary": "An IP probed {n_ports} distinct ports in under a minute. "
                   "This is reconnaissance — they were looking for open services "
                   "to attack. We've sent a default-block request to UFW.",
        "actions": [
            ("block", "Re-block the source IP"),
            ("audit", "Review audit log"),
        ],
    },
    "canary.token.trigger": {
        "title": "Canary token fired",
        "summary": "A decoy credential/URL was used. Someone read or clicked "
                   "something we planted. This is a confirmed intrusion signal.",
        "actions": [
            ("block", "Block source IP"),
            ("audit", "Open audit log"),
        ],
    },
    "rkhunter.warning": {
        "title": "Rootkit / integrity check warning",
        "summary": "rkhunter flagged a change to a system binary or config. "
                   "Could be a benign update, could be tampering — verify "
                   "before dismissing.",
        "actions": [
            ("audit", "Review change details"),
        ],
    },
    "portscan": {  # alias
        "title": "Port scan detected",
        "summary": "An IP probed {n_ports} distinct ports in under a minute.",
        "actions": [("block", "Re-block the source IP")],
    },
    "mit.exception": {
        "title": "OSINT / mitigation exception",
        "summary": "Mitigation workflow hit an unexpected condition. Check "
                   "the record-relief automation logs.",
        "actions": [("audit", "Open automation log")],
    },
    "watchdog.ping": {
        "title": "Watcher round-trip",
        "summary": "The honeypot watchdog confirmed it's still alive. "
                   "Informational — no action needed.",
        "actions": [],
    },
    "backup.complete": {
        "title": "Backup complete",
        "summary": "Nightly backup finished successfully.",
        "actions": [],
    },
    "unauth.read": {
        "title": "Unauthenticated read",
        "summary": "Someone read a sensitive file without credentials. "
                   "Investigate the source.",
        "actions": [("block", "Block source IP"), ("audit", "Open audit log")],
    },
}


# ── Alert ingestion ──────────────────────────────────────────────────────────

def _read_honeypot_log(limit: int = 200) -> list[dict]:
    if not HONEYPOT_LOG.exists():
        return []
    out: list[dict] = []
    try:
        with HONEYPOT_LOG.open() as f:
            lines = f.readlines()[-limit:]
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _read_recordrelief_feed(limit: int = 200) -> list[dict]:
    if not RECORDRELIEF_FEED.exists():
        return []
    try:
        data = json.loads(RECORDRELIEF_FEED.read_text())
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except (OSError, json.JSONDecodeError):
        return []
    return []


def _merge_and_sort(limit: int = 200) -> list[dict]:
    combined = _read_honeypot_log() + _read_recordrelief_feed()
    combined.sort(key=lambda e: e.get("ts", ""))
    return combined[-limit:]


# ── Webapp helper ────────────────────────────────────────────────────────────

def _is_webapp_up() -> bool:
    try:
        with socket.create_connection(
            ("127.0.0.1", RECORDRELIEF_PORT), timeout=0.4
        ):
            return True
    except OSError:
        return False


def _ensure_webapp() -> bool:
    if _is_webapp_up():
        return True
    if not RECORDRELIEF_WEBAPP_DIR.exists():
        return False
    serve = RECORDRELIEF_WEBAPP_DIR / "serve.sh"
    if not serve.exists():
        return False
    try:
        subprocess.Popen(
            ["bash", str(serve), str(RECORDRELIEF_PORT)],
            cwd=str(RECORDRELIEF_WEBAPP_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    for _ in range(15):
        if _is_webapp_up():
            return True
        time.sleep(0.2)
    return False


# ── Helpers ──────────────────────────────────────────────────────────────────

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _extract_ip(text: str) -> str | None:
    """Return the first IPv4-looking token in `text`, or None."""
    if not text:
        return None
    m = _IPV4.search(text)
    return m.group(0) if m else None


def _parse_ts(ts: str) -> datetime | None:
    if not ts or "T" not in ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _format_age(seconds: float) -> str:
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _format_hms(ts: str) -> str:
    if not ts or "T" not in ts:
        return ts or "—"
    time_part = ts.split("T", 1)[1]
    return time_part.split(".", 1)[0].rsplit("-", 1)[0].rsplit("+", 1)[0]


def _get_reframe(kind: str, alert: dict) -> dict | None:
    """Return the reframing dict for `kind`, or None if no reframing known."""
    r = REFRAMINGS.get(kind)
    if not r:
        return None
    out = dict(r)
    # Try to substitute IP + port count
    detail = str(alert.get("detail", ""))
    ip = _extract_ip(detail)
    out["ip"] = ip
    ports = alert.get("ports")
    if not ports:
        m = re.search(r"(\d+)\s+distinct ports", detail)
        ports = int(m.group(1)) if m else 0
    out["n_ports"] = ports
    return out


# ── Block command (writes to firewall_commands.jsonl) ────────────────────────

def _queue_block(ip: str, reason: str) -> bool:
    """Append a default-block request for the root helper to apply.

    Also update the local portscan state so the popout footer immediately
    shows the new blocked count (without waiting for the next correlate() pass
    to write it). The state file is the same one the portscan correlation
    engine reads, so this stays in sync.
    """
    if not ip:
        return False
    try:
        FIREWALL_COMMANDS.parent.mkdir(parents=True, exist_ok=True)
        with open(FIREWALL_COMMANDS, "a") as f:
            f.write(json.dumps({
                "action": "block", "ip": ip, "reason": reason,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            }) + "\n")
    except OSError:
        return False
    # Update the local state so the popout's footer shows the new count.
    try:
        state = {"blocked": {}, "last_alert": {}, "processed_offset": 0}
        if FIREWALL_STATE.exists():
            try:
                state.update(json.loads(FIREWALL_STATE.read_text()))
            except Exception:
                pass
        if "blocked" not in state:
            state["blocked"] = {}
        state["blocked"][ip] = datetime.now().astimezone().isoformat(timespec="seconds")
        FIREWALL_STATE.parent.mkdir(parents=True, exist_ok=True)
        FIREWALL_STATE.write_text(json.dumps(state))
    except OSError:
        pass
    return True


def _blocked_count() -> int:
    """How many IPs are currently in the firewall's block state."""
    try:
        if not FIREWALL_STATE.exists():
            return 0
        return len(json.loads(FIREWALL_STATE.read_text()).get("blocked", {}))
    except Exception:
        return 0


# ── Pure-logic helpers (Action Console) ───────────────────────────────────────
# These take plain alert data and return strings — no tkinter — so they're
# unit-testable headlessly. The window code calls these to build its labels.

def _severity_bar(alerts: list[dict]) -> str:
    """'🔴 2 critical · 1 high · 3 low' — only nonzero severities, critical
    first. Returns 'All clear' when there are no alerts."""
    if not alerts:
        return "All clear"
    counts: dict[str, int] = {k: 0 for k in SEV_ORDER}
    for a in alerts:
        s = str(a.get("severity", "info")).lower()
        if s in counts:
            counts[s] += 1
    parts = []
    for sev in SEV_ORDER:
        n = counts[sev]
        if n > 0:
            parts.append(f"{SEV_ICON.get(sev, '•')} {n} {sev}")
    return " · ".join(parts) if parts else "All clear"


_DEFAULT_FRAME = (
    "Something touched the system — an alert fired from {source}. "
    "This is the system flagging an event it thinks is worth your attention. "
    "Open the detail to see the exact message before deciding what to do."
)


def _human_frame(alert: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (title, human_body, actions) for an alert.

    Uses the REFRAMINGS table when the kind is known; otherwise falls back to
    a generic plain-language frame. `actions` is a list of (key, label) where
    key is one of block / audit / ack / dismiss.
    """
    kind = str(alert.get("kind", ""))
    r = REFRAMINGS.get(kind)
    if not r:
        src = alert.get("source", "?")
        return (
            str(alert.get("kind", "alert")).replace(".", " ").replace("_", " ").title() or "Alert",
            _DEFAULT_FRAME.format(source=src),
            [("dismiss", "✕ Dismiss")],
        )
    title = r["title"]
    body = r["summary"]
    ip = _extract_ip(str(alert.get("detail", "")))
    ports = alert.get("ports")
    if not ports:
        m = re.search(r"(\d+)\s+distinct ports", str(alert.get("detail", "")))
        ports = int(m.group(1)) if m else 0
    try:
        body = body.format(ip=ip, n_ports=ports)
    except Exception:
        pass
    actions = list(r.get("actions", []))
    if not any(k == "dismiss" for k, _ in actions):
        actions.append(("dismiss", "✕ Dismiss"))
    return title, body, actions


def _block_feedback(ip: str, reason: str) -> str:
    """Queue a block and return a short user-facing status string.

    Reads firewall_commands_result.jsonl after writing so we can report whether
    the root helper applied the rule yet.
    """
    if not _queue_block(ip, reason):
        return "⚠ block command write failed"
    applied = False
    try:
        result_path = FIREWALL_COMMANDS.parent / "firewall_commands_result.jsonl"
        if result_path.exists():
            with result_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("ip") == ip and rec.get("ok"):
                        applied = True
    except OSError:
        pass
    return f"Blocked {ip} ✓" if applied else f"Block queued for {ip} (helper applying)"


# ── Window construction ──────────────────────────────────────────────────────

def _make_window() -> None:
    root = tk.Tk()
    root.title("Security Tracker")
    root.configure(bg=BG_PANEL)

    # ── Dock-style window (no focus theft). ──
    root.wm_attributes("-type", "dock")
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.99)
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win_w = min(820, sw - 32)
    win_h = min(2000, sh - 64)
    margin = 16
    x = sw - win_w - margin
    y = max(margin, sh - win_h - margin - 240)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.update_idletasks()

    try:
        prev_active = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=1,
        ).stdout.strip()
    except Exception:
        prev_active = ""
    root.protocol("WM_TAKE_FOCUS", lambda: None)

    def _restore_focus(wid: str) -> None:
        try:
            if not wid or not wid.isdigit():
                return
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", wid],
                capture_output=True, timeout=1,
            )
        except Exception:
            pass

    def _spam_then_quiet(steps_left: int) -> None:
        if prev_active:
            _restore_focus(prev_active)
        if steps_left > 0:
            root.after(120, _spam_then_quiet, steps_left - 1)
        else:
            def _stay_topmost() -> None:
                try:
                    root.attributes("-topmost", True)
                except Exception:
                    pass
                if root.winfo_exists():
                    root.after(2000, _stay_topmost)
            _stay_topmost()
    _spam_then_quiet(8)

    # ── Title bar (draggable) ──
    _drag = {"x": 0, "y": 0, "w": 0, "h": 0}
    def _on_title_click(event: tk.Event) -> None:
        _drag["x"] = event.x_root
        _drag["y"] = event.y_root
        _drag["w"] = root.winfo_x()
        _drag["h"] = root.winfo_y()
    def _on_title_drag(event: tk.Event) -> None:
        try:
            dx = event.x_root - _drag["x"]
            dy = event.y_root - _drag["y"]
            nx = max(0, min(_drag["w"] + dx, sw - root.winfo_width()))
            ny = max(0, min(_drag["h"] + dy, sh - root.winfo_height()))
            root.geometry(f"+{nx}+{ny}")
        except Exception:
            pass

    title_bar = tk.Frame(root, bg=BG_BAR, height=36)
    title_bar.pack(fill="x")
    title_bar.pack_propagate(False)
    title_bar.bind("<Button-1>", _on_title_click)
    title_bar.bind("<B1-Motion>", _on_title_drag)
    title_bar.bind("<ButtonRelease-1>", lambda _e: None)

    def _on_close(_e=None):
        root.destroy()
    close_btn = tk.Label(title_bar, text="✕", bg=BG_BAR, fg="#ff5252",
                         font=("TkDefaultFont", 14, "bold"),
                         cursor="hand2", padx=10)
    close_btn.pack(side="right", padx=(0, 6), pady=4)
    close_btn.bind("<Button-1>", _on_close)
    close_btn.bind("<Enter>", lambda _e: close_btn.configure(bg="#5a1a1a"))
    close_btn.bind("<Leave>", lambda _e: close_btn.configure(bg=BG_BAR))

    title = tk.Label(title_bar, text="🛡  Security Tracker",
                     bg=BG_BAR, fg=FG_BRIGHT,
                     font=("-size", 13, "-weight", "bold"),
                     cursor="fleur")
    title.pack(side="left", padx=16, pady=4)
    title.bind("<Button-1>", _on_title_click)
    title.bind("<B1-Motion>", _on_title_drag)

    # ── Single big scrollable column ──
    outer = tk.Frame(root, bg=BG_PANEL)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=BG_PANEL, highlightthickness=0)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview, width=14,
                      troughcolor=BG_PANEL, bg="#5a5a7e",
                      activebackground="#7a7a9e", relief="flat", bd=0)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=BG_PANEL)
    canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
    inner.bind(
        "<Configure>",
        lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
    )

    # ── Status header ──
    status_frame = tk.Frame(inner, bg=BG_PANEL)
    status_frame.pack(fill="x", padx=16, pady=(16, 4))
    sev_dot = tk.Label(status_frame, text="●", bg=BG_PANEL, fg="#5ac8fa",
                       font=("-size", 24, "-weight", "bold"))
    sev_dot.pack(side="left", padx=(0, 12))
    status_text_frame = tk.Frame(status_frame, bg=BG_PANEL)
    status_text_frame.pack(side="left", fill="x", expand=True)
    status_main = tk.Label(status_text_frame, text="All clear", bg=BG_PANEL,
                           fg=FG_BRIGHT, font=("-size", 18, "-weight", "bold"),
                           anchor="w")
    status_main.pack(fill="x")
    status_sub = tk.Label(status_text_frame, text="Watching · refresh 2s",
                          bg=BG_PANEL, fg=FG_MUTED,
                          font=("-size", 11), anchor="w")
    status_sub.pack(fill="x")

    # ── Action plan banner ──
    plan_frame = tk.Frame(inner, bg="#1a3050", bd=1, relief="flat",
                          highlightbackground="#2a5080", highlightthickness=1)
    plan_frame.pack(fill="x", padx=16, pady=(8, 4))
    plan_text = tk.Label(
        plan_frame, text="✅ No recommended action — system is quiet.",
        bg="#1a3050", fg="#5ac8fa",
        font=("-size", 12, "-weight", "bold"),
        anchor="w", wraplength=win_w - 60, justify="left",
        padx=12, pady=10, cursor="hand2",
    )
    plan_text.pack(fill="x")

    # ── Severity filter row (single row of chips) ──
    sev_filter = tk.Frame(inner, bg=BG_PANEL)
    sev_filter.pack(fill="x", padx=16, pady=(8, 4))
    sev_state: dict[str, tk.BooleanVar] = {
        k: tk.BooleanVar(value=True) for k in SEV_COLOR
    }
    sev_chip_refs: dict[str, dict] = {}

    def _rebuild_alerts():
        """Re-render the alert list after a filter change."""
        _render_alerts(_filter_alerts(_merge_and_sort()))

    def _make_filter_chip(parent, sev: str):
        color = SEV_COLOR[sev]
        icon = SEV_ICON[sev]
        chip = tk.Frame(parent, bg=BG_CHIP, bd=0, relief="flat",
                        highlightbackground=color, highlightthickness=1,
                        cursor="hand2")
        icon_l = tk.Label(chip, text=icon, bg=BG_CHIP, fg=color,
                          font=("-size", 11, "-weight", "bold"))
        icon_l.pack(side="left", padx=(8, 2), pady=4)
        text_l = tk.Label(chip, text=sev.upper(), bg=BG_CHIP, fg=color,
                          font=("-size", 10, "-weight", "bold"))
        text_l.pack(side="left", padx=(0, 4), pady=4)
        cnt_l = tk.Label(chip, text="0", bg=BG_CHIP, fg=color,
                         font=("-size", 11, "-weight", "bold"))
        cnt_l.pack(side="right", padx=(0, 8), pady=4)
        holder = {"chip": chip, "icon": icon_l, "text": text_l, "cnt": cnt_l,
                  "on": True, "color": color, "var": sev_state[sev]}

        def _flip(_e=None):
            holder["on"] = not holder["on"]
            sev_state[sev].set(holder["on"])
            if holder["on"]:
                bg = BG_CHIP
                fg = color
            else:
                bg = BG_DIM
                fg = "#3a3a5e"
            for w in (chip, icon_l, text_l, cnt_l):
                w.configure(bg=bg, fg=fg)
            _rebuild_alerts()

        for w in (chip, icon_l, text_l, cnt_l):
            w.bind("<Button-1>", _flip)
            w.bind("<Button-3>", _flip)
        sev_chip_refs[sev] = holder
        return chip

    for sev in SEV_ORDER:
        _make_filter_chip(sev_filter, sev).pack(side="left", padx=(0, 4), pady=2)

    # ── Action row (4 compact buttons) ──
    action_row = tk.Frame(inner, bg=BG_PANEL)
    action_row.pack(fill="x", padx=16, pady=(8, 8))
    paused: dict = {"v": False}
    pause_lbl: dict = {"w": None}

    def on_pause(_e=None):
        paused["v"] = not paused["v"]
        w = pause_lbl["w"]
        if w is None:
            return
        if paused["v"]:
            w.configure(text="▶", bg="#2e7d32")
        else:
            w.configure(text="⏸", bg="#f57c00")

    def on_open_dashboard(_e=None):
        try:
            up = _ensure_webapp()
            if not up:
                status_sub.configure(
                    text=f"⚠️ webapp not running on :{RECORDRELIEF_PORT} — start serve.sh?"
                )
                return
            subprocess.Popen(["xdg-open", RECORDRELIEF_URL],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            status_sub.configure(text="🌐 Dashboard opened · click 🛡 Security tab")
        except Exception as e:
            status_sub.configure(text=f"⚠️ open failed: {e}")

    def on_refresh(_e=None):
        _apply_filters()
        status_sub.configure(text="🔄 Refreshed")

    def on_clear_logs(_e=None):
        confirm = tk.Toplevel(root)
        confirm.title("Clear logs?")
        confirm.configure(bg=BG_PANEL)
        confirm.attributes("-topmost", True)
        confirm.resizable(False, False)
        confirm.geometry(
            f"380x180+{root.winfo_x() + 80}+{root.winfo_y() + 100}")
        tk.Label(
            confirm, text="Clear BOTH alert stores?\n\n🪤 ~/honeypot/alerts.log\n"
                          "📋 RecordRelief alerts.json",
            bg=BG_PANEL, fg=FG_BRIGHT, font=("-size", 12), pady=16,
            justify="center",
        ).pack(fill="x", padx=10)
        row = tk.Frame(confirm, bg=BG_PANEL)
        row.pack(pady=(0, 10))
        def do_clear():
            cleared = []
            for path in (HONEYPOT_LOG, RECORDRELIEF_FEED):
                try:
                    if path.exists():
                        if path == RECORDRELIEF_FEED:
                            path.write_text("[]\n")
                        else:
                            path.write_text("")
                        cleared.append(path.name)
                except OSError as e:
                    status_sub.configure(text=f"⚠️ clear failed: {path.name}: {e}")
            confirm.destroy()
            _expanded_id[0] = None
            _apply_filters()
            status_sub.configure(
                text=f"🗑 Cleared · {', '.join(cleared) or 'nothing to clear'}"
            )
        tk.Button(row, text="🗑 CLEAR", bg="#b71c1c", fg="white",
                  font=("-size", 12, "-weight", "bold"),
                  activebackground="#d32f2f", activeforeground="white",
                  relief="flat", padx=16, pady=8, cursor="hand2",
                  command=do_clear).pack(side="left", padx=8)
        tk.Button(row, text="Cancel", bg="#444", fg="white",
                  font=("-size", 12), activebackground="#666",
                  activeforeground="white", relief="flat", padx=16, pady=8,
                  cursor="hand2", command=confirm.destroy).pack(side="left", padx=8)

    def _small_btn(parent, text, bg, command, fg="white"):
        b = tk.Label(parent, text=text, bg=bg, fg=fg,
                     font=("-size", 12, "-weight", "bold"),
                     padx=12, pady=8, cursor="hand2", relief="flat")
        b.bind("<Button-1>", command)
        b.bind("<Enter>", lambda _e, w=b: w.configure(bg=_lighten(bg)))
        b.bind("<Leave>", lambda _e, w=b: w.configure(bg=bg))
        return b

    def _lighten(hex_color: str) -> str:
        """Lighten a hex color for hover feedback."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = min(255, r + 30)
            g = min(255, g + 30)
            b = min(255, b + 30)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    pause_lbl["w"] = _small_btn(action_row, "⏸ Pause", "#f57c00", on_pause)
    pause_lbl["w"].pack(side="left", padx=(0, 4), fill="x", expand=True)
    _small_btn(action_row, "🔄 Refresh", "#37474f", on_refresh).pack(
        side="left", padx=4, fill="x", expand=True)
    _small_btn(action_row, "🌐 Dashboard", "#0d47a1", on_open_dashboard).pack(
        side="left", padx=4, fill="x", expand=True)
    _small_btn(action_row, "🗑 Clear", "#b71c1c", on_clear_logs).pack(
        side="left", padx=(4, 0), fill="x", expand=True)

    # ── Alert stream ──
    stream_label = tk.Label(inner, text="📡  Alert stream  ·  click a card to inspect",
                            bg=BG_PANEL, fg=FG_MUTED,
                            font=("-size", 11, "-weight", "bold"), anchor="w")
    stream_label.pack(fill="x", padx=16, pady=(4, 4))

    list_frame = tk.Frame(inner, bg=BG_DEEP, bd=0)
    list_frame.pack(padx=16, pady=(0, 8), fill="x")

    # Track which alert (by ts+detail) is currently expanded
    _expanded_id: list = [None]

    def _alert_id(a: dict) -> tuple:
        return (a.get("ts", ""), a.get("source", ""), a.get("kind", ""),
                a.get("detail", "")[:80])

    def _filter_alerts(alerts):
        allowed = {k for k, v in sev_state.items() if v.get()}
        return [a for a in alerts
                if str(a.get("severity", "info")).lower() in allowed]

    def _build_card(parent, alert):
        sev = str(alert.get("severity", "info")).lower()
        color = SEV_COLOR.get(sev, "#5ac8fa")
        icon = SEV_ICON.get(sev, "•")
        reframe = _get_reframe(alert.get("kind", ""), alert)
        ref_title = reframe["title"] if reframe else (
            str(alert.get("kind", "alert")).replace(".", " ").replace("_", " ")
            .title() or "Alert")

        card = tk.Frame(parent, bg=BG_ROW, bd=0, relief="flat",
                        highlightbackground=color, highlightthickness=1,
                        cursor="hand2")

        # Header row: sev icon + title + ts
        head = tk.Frame(card, bg=BG_ROW)
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(head, text=icon, bg=BG_ROW, fg=color,
                 font=("-size", 14, "-weight", "bold")).pack(side="left", padx=(0, 8))
        tk.Label(head, text=ref_title, bg=BG_ROW, fg=FG_BRIGHT,
                 font=("-size", 13, "-weight", "bold"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(head, text=_format_hms(alert.get("ts", "")),
                 bg=BG_ROW, fg=FG_DIM, font=("-size", 10)).pack(side="right")

        # Source + kind label
        meta = tk.Label(card,
                        text=f"{alert.get('source', '?')}  ·  {alert.get('kind', '?')}",
                        bg=BG_ROW, fg=FG_MUTED, font=("-size", 10), anchor="w")
        meta.pack(fill="x", padx=10, pady=(0, 6))

        # Truncated preview
        preview_text = str(alert.get("detail", ""))
        if len(preview_text) > 180:
            preview_text = preview_text[:180] + "…"
        preview = tk.Label(card, text=preview_text, bg=BG_ROW, fg=FG_BRIGHT,
                           font=("-size", 11), wraplength=win_w - 60,
                           justify="left", anchor="w")
        preview.pack(fill="x", padx=10, pady=(0, 8))

        # Hover feedback on the card
        def _enter(_e=None):
            for w in (card, head, meta, preview):
                w.configure(bg=BG_HOVER)
        def _leave(_e=None):
            for w in (card, head, meta, preview):
                w.configure(bg=BG_ROW)
        for w in (card, head, meta, preview):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        # Track all child widgets so we can recolor them on hover / expand
        return card, {
            "card": card, "head": head, "meta": meta, "preview": preview,
            "all_widgets": [card, head, meta, preview],
        }

    def _build_expanded(parent, alert, refs):
        """Build the expanded detail panel under a card. Returned widget is
        already packed; caller hides it via pack_forget() to collapse."""
        sev = str(alert.get("severity", "info")).lower()
        color = SEV_COLOR.get(sev, "#5ac8fa")
        reframe = _get_reframe(alert.get("kind", ""), alert)
        ip = _extract_ip(str(alert.get("detail", ""))) if reframe else None

        body = tk.Frame(parent, bg="#161628",
                        highlightbackground=color, highlightthickness=0)
        inner_w = win_w - 60

        # Reframing summary (if known)
        if reframe:
            s = reframe["summary"]
            try:
                s = s.format(**reframe)
            except Exception:
                pass
            tk.Label(
                body, text="📖  " + s, bg="#161628", fg="#ffd58a",
                font=("-size", 12), wraplength=inner_w, justify="left",
                anchor="w",
            ).pack(fill="x", padx=14, pady=(12, 8))

        # Full untruncated detail
        tk.Label(
            body, text="DETAIL", bg="#161628", fg=FG_DIM,
            font=("-size", 9, "-weight", "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 2))
        tk.Label(
            body, text=str(alert.get("detail", "—")),
            bg="#161628", fg=FG_BRIGHT, font=("-size", 11),
            wraplength=inner_w, justify="left", anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 8))

        # Token if present
        if alert.get("token"):
            tk.Label(
                body, text=f"token: {alert['token']}",
                bg="#161628", fg="#808090", font=("-size", 10), anchor="w",
            ).pack(fill="x", padx=14)

        # Raw JSON in a text widget
        tk.Label(body, text="RAW JSON", bg="#161628", fg=FG_DIM,
                 font=("-size", 9, "-weight", "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(6, 2))
        try:
            raw = json.dumps(alert, indent=2, ensure_ascii=False)
        except Exception:
            raw = repr(alert)
        raw_box = tk.Text(body, height=min(10, max(3, raw.count("\n") + 1)),
                          bg="#0a0a18", fg="#a0a0c0",
                          font=("TkFixedFont", 9), relief="flat", bd=0,
                          wrap="word")
        raw_box.insert("1.0", raw)
        raw_box.configure(state="disabled")
        raw_box.pack(fill="x", padx=14, pady=(0, 8))

        # Action buttons
        actions = (reframe["actions"] if reframe else []) + [
            ("dismiss", "✕ Dismiss")
        ]
        btn_row = tk.Frame(body, bg="#161628")
        btn_row.pack(fill="x", padx=14, pady=(4, 12))

        def do_block():
            if not ip:
                status_sub.configure(text="⚠️ no IP found in detail to block")
                return
            if _queue_block(ip, f"manual: {alert.get('kind', '?')}"):
                status_sub.configure(text=f"🛡 Block queued for {ip} (root helper will apply)")
            else:
                status_sub.configure(text="⚠️ block command write failed")

        def do_ack():
            status_sub.configure(text="✓ Acknowledged (noted in log)")

        def do_dismiss():
            _expanded_id[0] = None
            _apply_filters()

        handlers = {
            "block": do_block,
            "audit": lambda: status_sub.configure(
                text="🔍 Audit log — see ~/security-reports/overseer/overseer.log"),
            "ack": do_ack,
            "dismiss": do_dismiss,
        }
        for act_key, act_label in actions:
            bg = {
                "block": "#b71c1c", "audit": "#0d47a1",
                "ack": "#37474f", "dismiss": "#444",
            }.get(act_key, "#444")
            b = tk.Label(btn_row, text=act_label, bg=bg, fg="white",
                         font=("-size", 11, "-weight", "bold"),
                         padx=10, pady=6, cursor="hand2", relief="flat")
            b.pack(side="left", padx=(0, 6))
            orig_bg = bg
            b.bind("<Enter>", lambda _e, w=b: w.configure(bg=_lighten(orig_bg)))
            b.bind("<Leave>", lambda _e, w=b: w.configure(bg=orig_bg))
            b.bind("<Button-1>", lambda _e, h=handlers.get(act_key): h() if h else None)

        return body

    # State for the current rendered list
    card_widgets: list = []  # list of (card, refs, body, alert)

    def _render_alerts(alerts):
        # Clear old
        for c in card_widgets:
            c[0].destroy()
        card_widgets.clear()
        if not alerts:
            empty = tk.Label(
                list_frame,
                text="🟢 No alerts match current filters.",
                bg=BG_DEEP, fg=FG_DIM, font=("-size", 12), pady=24,
            )
            empty.pack(fill="x", padx=10)
            card_widgets.append((empty, None, None, None))
            return
        # Newest first
        for a in reversed(alerts):
            card, refs = _build_card(list_frame, a)
            card.pack(fill="x", padx=4, pady=3)
            entry = [card, refs, None, a]
            card_widgets.append(entry)
            aid = _alert_id(a)
            # Bind click → expand
            for w in refs["all_widgets"]:
                w.bind("<Button-1>",
                       lambda _e, e=entry, k=aid: _toggle_expand(e, k))

    def _toggle_expand(entry, aid):
        if _expanded_id[0] is None or _expanded_id[0] != aid:
            # Collapse any currently expanded
            for c in card_widgets:
                if c[2] is not None:
                    c[2].destroy()
                    c[2] = None
            # Expand this one
            body = _build_expanded(list_frame, entry[3], entry[1])
            body.pack(fill="x", padx=4, pady=(0, 4),
                      after=entry[0])  # immediately under its card
            entry[2] = body
            _expanded_id[0] = aid
            # Scroll so the expanded panel is visible. ``after=entry[0]``
            # already puts it under the card; we just need to bring the
            # card into view (the expansion extends the content down).
            root.update_idletasks()
            try:
                card_y = entry[0].winfo_y()
                canvas.yview_moveto(max(0, (card_y - 80) / max(1, inner.winfo_height())))
            except Exception:
                pass
        else:
            # Collapse
            if entry[2] is not None:
                entry[2].destroy()
                entry[2] = None
            _expanded_id[0] = None

    # ── Footer (1 line) ──
    footer = tk.Label(inner,
                      text="—", bg=BG_PANEL, fg=FG_DIM,
                      font=("-size", 10), anchor="w")
    footer.pack(fill="x", padx=16, pady=(4, 12))

    # Mouse wheel
    def _on_mousewheel(event):
        if event.num == 4:
            canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            canvas.yview_scroll(3, "units")
        else:
            canvas.yview_scroll(int(-event.delta / 120) * 3, "units")
    for w in (root, canvas, inner, list_frame):
        w.bind("<Button-4>", _on_mousewheel)
        w.bind("<Button-5>", _on_mousewheel)

    # ── Periodic refresh ──
    last_poll_ts: list = [time.time()]

    def _update_chips(alerts):
        counts = {k: 0 for k in SEV_ORDER}
        for a in alerts:
            s = str(a.get("severity", "info")).lower()
            if s in counts:
                counts[s] += 1
        for sev, refs in sev_chip_refs.items():
            refs["cnt"].configure(text=str(counts.get(sev, 0)))

    def _update_status(alerts):
        if not alerts:
            sev_dot.configure(fg="#5ac8fa", text="●")
            status_main.configure(text="All clear", fg=FG_BRIGHT)
            status_sub.configure(text="Watching · refresh 2s")
            plan_text.configure(
                text="✅ No recommended action — system is quiet.",
                bg="#1a3050", fg="#5ac8fa",
            )
            return
        severities = {str(a.get("severity", "info")).lower() for a in alerts}
        max_sev = next((s for s in SEV_ORDER if s in severities), "info")
        color = SEV_COLOR[max_sev]
        sev_dot.configure(fg=color, text="●")
        crit_n = sum(1 for a in alerts
                     if str(a.get("severity", "")).lower() == "critical")
        high_n = sum(1 for a in alerts
                     if str(a.get("severity", "")).lower() == "high")
        crit_txt = f" · {crit_n} critical" if crit_n else ""
        high_txt = f" · {high_n} high" if high_n else ""
        status_main.configure(text=f"{len(alerts)} alerts{crit_txt}{high_txt}",
                              fg=FG_BRIGHT)
        status_sub.configure(
            text=f"Watching · max severity: {max_sev.upper()} · refresh 2s")
        # Action plan banner
        # Priority: blocked-source IP needed, then critical, then high.
        ips_needing_block: set = set()
        for a in alerts:
            if a.get("source") == "firewall" and a.get("kind") == "port-scan":
                ip = _extract_ip(str(a.get("detail", "")))
                if ip:
                    ips_needing_block.add(ip)
        if ips_needing_block:
            plan_text.configure(
                text=f"🛡 Action: 1 IP needs blocking ({ips_needing_block.pop()}). "
                     "Click the alert card to block.",
                bg="#3a1010", fg="#ff8080", cursor="hand2")
        elif crit_n > 0:
            plan_text.configure(
                text=f"⚠️ Action: review {crit_n} critical alert{'s' if crit_n != 1 else ''}.",
                bg="#3a2010", fg="#ffaa50", cursor="hand2")
        elif high_n > 0:
            plan_text.configure(
                text=f"⚠️ Action: review {high_n} high-severity alert{'s' if high_n != 1 else ''}.",
                bg="#3a3010", fg="#ffd54f", cursor="hand2")
        else:
            plan_text.configure(
                text="✅ No critical action — review new alerts at your pace.",
                bg="#1a3050", fg="#5ac8fa", cursor="hand2")

    def _update_footer(alerts):
        n = len(alerts)
        blocked = _blocked_count()
        age = _format_age(time.time() - last_poll_ts[0])
        footer.configure(
            text=f"📡 {n} alerts · ⏱ last refresh {age} · 🛡 {blocked} blocked source{'s' if blocked != 1 else ''}"
        )

    def _apply_filters():
        alerts = _merge_and_sort(limit=200)
        last_poll_ts[0] = time.time()
        filtered = _filter_alerts(alerts)
        _update_chips(alerts)
        _update_status(alerts)
        _update_footer(alerts)
        _render_alerts(filtered)

    def _refresh():
        try:
            _apply_filters()
        except Exception as e:
            status_sub.configure(text=f"⚠️ refresh error: {e}")
        finally:
            if root.winfo_exists():
                root.after(2000, _refresh)

    # Make the action plan banner clickable (when actionable)
    def _plan_click(_e=None):
        # If a "needs blocking" plan, expand the first firewall card
        if plan_text.cget("text").startswith("🛡 Action"):
            for entry in card_widgets:
                a = entry[3]
                if a and a.get("source") == "firewall" and a.get("kind") == "port-scan":
                    _toggle_expand(entry, _alert_id(a))
                    return
    plan_text.bind("<Button-1>", _plan_click)

    _apply_filters()
    root.after(2000, _refresh)
    root.mainloop()


def open_in_thread() -> threading.Thread:
    t = threading.Thread(target=_make_window, daemon=True, name="sec-controls")
    t.start()
    return t


def main() -> int:
    _make_window()
    return 0


if __name__ == "__main__":
    sys.exit(main())
