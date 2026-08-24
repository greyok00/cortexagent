#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk


HONEYPOT_LOG = Path.home() / "security-console" / "honeypot" / "alerts.log"
EXTRA_FEED = Path(
    os.environ.get(
        "CORTEXAGENT_ALERTS_JSON",
        str(Path.home() / "security-console" / "alerts.json"),
    )
)
FIREWALL_COMMANDS = (
    Path.home() / "security-console" / "overseer" / "firewall_commands.jsonl"
)
FIREWALL_STATE = (
    Path.home() / "security-console" / "overseer" / ".portscan_state.json"
)


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


BG_DEEP   = "#0f0f1f"
BG_PANEL  = "#1a1a2e"
BG_BAR    = "#3a3a5e"
BG_ROW    = "#20203a"

FG_DIM    = "#a8aabe"
FG_MUTED  = "#a0a0c0"
FG_BRIGHT = "#e0e0e0"







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
    "portscan": {
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
    "cve.critical": {
        "title": "Critical CVE published",
        "summary": "A new CVE with CVSS ≥ 9.0 was published. "
                   "Confirm whether any local system matches the CPE list, "
                   "and apply the vendor patch immediately.",
        "actions": [
            ("audit", "Open NVD record"),
            ("investigate", "Check local exposure"),
        ],
    },
    "cve.kev": {
        "title": "CISA KEV — actively exploited",
        "summary": "This CVE is in CISA's Known Exploited Vulnerabilities "
                   "catalog. Active exploitation has been observed — patch "
                   "per the BOD 22-01 due date if you host the affected "
                   "software.",
        "actions": [
            ("audit", "Open NVD record"),
            ("investigate", "Check local exposure"),
        ],
    },
    "cve.high_epss": {
        "title": "High EPSS — likely exploited soon",
        "summary": "EPSS score is high — exploit probability in the top 10%. "
                   "Pre-emptively patch if we run the affected component.",
        "actions": [
            ("audit", "Open NVD record"),
            ("investigate", "Check local exposure"),
        ],
    },
}




def _read_honeypot_log(limit: int = 200) -> list[dict]:
    if not HONEYPOT_LOG.exists():
        return []
    out: list[dict] = []
    try:
        with HONEYPOT_LOG.open(encoding="utf-8") as f:
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


def _read_extra_feed(limit: int = 200) -> list[dict]:
    if not EXTRA_FEED.exists():
        return []
    try:
        data = json.loads(EXTRA_FEED.read_text())
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except (OSError, json.JSONDecodeError):
        return []


CVE_INTEL_FILE = Path.home() / "security-console" / "cve" / "intel.jsonl"


def _read_cve_feed(limit: int = 50) -> list[dict]:

    if not CVE_INTEL_FILE.exists():
        return []
    out: list[dict] = []
    try:
        with CVE_INTEL_FILE.open(encoding="utf-8") as f:
            lines = f.readlines()[-limit * 2:]
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                entry = json.loads(ln)
            except json.JSONDecodeError:
                continue
            cid = entry.get("cve_id") or "CVE-?"
            cvss = float(entry.get("cvss_v3") or 0.0)
            epss = float(entry.get("epss_score") or 0.0)
            kev = bool(entry.get("kev"))
            if kev:
                kind, severity = "cve.kev", "critical"
            elif cvss >= 9.0 or entry.get("severity") == "critical":
                kind, severity = "cve.critical", "critical"
            elif epss >= 0.5:
                kind, severity = "cve.high_epss", "high"
            else:
                continue
            summary = entry.get("summary") or "(no summary)"
            techniques = entry.get("mitre_techniques") or []
            tech_str = f"  TIDs: {', '.join(techniques)}" if techniques else ""
            out.append({
                "ts": entry.get("published") or entry.get("last_modified") or "",
                "source": "cve_intel",
                "kind": kind,
                "severity": severity,
                "title": f"{cid} (CVSS {cvss:.1f}{', KEV' if kev else ''}{', EPSS '+f'{epss:.2f}' if epss else ''})",
                "detail": f"{summary[:240]}{tech_str}",
                "cve_id": cid,
                "refs": entry.get("refs") or [],
                "mitre_techniques": techniques,
            })
    except OSError:
        return []
    return out[-limit:]


def _merge_and_sort(limit: int = 200) -> list[dict]:
    combined = _read_honeypot_log() + _read_extra_feed() + _read_cve_feed()
    combined.sort(key=lambda e: e.get("ts", ""))
    return combined[-limit:]




_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _extract_ip(text: str) -> str | None:

    if not text:
        return None
    m = _IPV4.search(text)
    return m.group(0) if m else None


def _format_hms(ts: str) -> str:
    if not ts or "T" not in ts:
        return ts or "—"
    time_part = ts.split("T", 1)[1]
    return time_part.split(".", 1)[0].rsplit("-", 1)[0].rsplit("+", 1)[0]




def _queue_block(ip: str, reason: str) -> bool:

    if not ip:
        return False
    try:
        FIREWALL_COMMANDS.parent.mkdir(parents=True, exist_ok=True)
        with open(FIREWALL_COMMANDS, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "action": "block", "ip": ip, "reason": reason,
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            }, ensure_ascii=False) + "\n")
    except OSError:
        return False

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






def _severity_bar(alerts: list[dict]) -> str:

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

    if not _queue_block(ip, reason):
        return "⚠ block command write failed"
    applied = False
    try:
        result_path = FIREWALL_COMMANDS.parent / "firewall_commands_result.jsonl"
        if result_path.exists():
            with result_path.open(encoding="utf-8") as f:
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




def _make_window() -> None:
    root = tk.Tk()
    root.title("Security Tracker")
    root.configure(bg=BG_PANEL)


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
                          "📋 alerts.json",
            bg=BG_PANEL, fg=FG_BRIGHT, font=("-size", 12), pady=16,
            justify="center",
        ).pack(fill="x", padx=10)
        row = tk.Frame(confirm, bg=BG_PANEL)
        row.pack(pady=(0, 10))
        def do_clear():
            cleared = []
            for path in (HONEYPOT_LOG, EXTRA_FEED):
                try:
                    if path.exists():
                        if path == EXTRA_FEED:
                            path.write_text("[]\n")
                        else:
                            path.write_text("")
                        cleared.append(path.name)
                except OSError as e:
                    status_sub.configure(text=f"⚠️ clear failed: {path.name}: {e}")
            confirm.destroy()
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
    _small_btn(action_row, "🗑 Clear", "#b71c1c", on_clear_logs).pack(
        side="left", padx=(4, 0), fill="x", expand=True)


    stream_label = tk.Label(inner, text="📡  Alert stream",
                            bg=BG_PANEL, fg=FG_MUTED,
                            font=("-size", 11, "-weight", "bold"), anchor="w")
    stream_label.pack(fill="x", padx=16, pady=(4, 4))

    list_frame = tk.Frame(inner, bg=BG_DEEP, bd=0)
    list_frame.pack(padx=16, pady=(0, 8), fill="x")

    def _alert_id(a: dict) -> tuple:
        return (a.get("ts", ""), a.get("source", ""), a.get("kind", ""),
                a.get("detail", "")[:80])

    def _build_card(parent, alert):
        sev = str(alert.get("severity", "info")).lower()
        color = SEV_COLOR.get(sev, "#5ac8fa")
        icon = SEV_ICON.get(sev, "•")
        title, body, actions = _human_frame(alert)

        card = tk.Frame(parent, bg=BG_ROW, bd=0, relief="flat",
                        highlightbackground=color, highlightthickness=1)
        head = tk.Frame(card, bg=BG_ROW)
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(head, text=icon, bg=BG_ROW, fg=color,
                 font=("-size", 15, "-weight", "bold")).pack(side="left", padx=(0, 8))
        title_l = tk.Label(head, text=title, bg=BG_ROW, fg=FG_BRIGHT,
                           font=("-size", 15, "-weight", "bold"), anchor="w")
        title_l.pack(side="left", fill="x", expand=True)
        tk.Label(head, text=_format_hms(alert.get("ts", "")),
                 bg=BG_ROW, fg=FG_DIM, font=("-size", 11)).pack(side="right")

        preview_l = tk.Label(card, text=body, bg=BG_ROW, fg=FG_BRIGHT,
                             font=("-size", 13), wraplength=win_w - 60,
                             justify="left", anchor="w")
        preview_l.pack(fill="x", padx=10, pady=(6, 6))


        btn_row = tk.Frame(card, bg=BG_ROW)
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        for act_key, act_label in actions:
            if act_key not in ("block", "audit", "ack", "dismiss"):
                continue
            if act_key == "block" and not _extract_ip(str(alert.get("detail", ""))):
                continue
            bg = {"block": "#b71c1c", "audit": "#0d47a1",
                  "ack": "#37474f", "dismiss": "#444"}.get(act_key, "#444")
            b = _small_btn(btn_row, act_label, bg,
                           lambda _e, k=act_key, a=alert: _on_action(k, a))
            b.pack(side="left", padx=(0, 6), fill="x", expand=True)

        return card, {
            "card": card, "head": head, "title_l": title_l, "preview_l": preview_l,
            "all_widgets": [card, head, title_l, preview_l],
        }


    card_widgets: list = []
    dismissed_ids: set = set()

    def _render_alerts(alerts, in_place=True):

        if not alerts:
            for c in list(card_widgets):
                c[0].destroy()
            card_widgets.clear()
            empty = tk.Label(
                list_frame,
                text="🟢 No alerts match current filters.",
                bg=BG_DEEP, fg=FG_DIM, font=("-size", 12), pady=24,
            )
            empty.pack(fill="x", padx=10)
            card_widgets.append((empty, None, None, None))
            return

        for c in list(card_widgets):
            if c[3] is None:
                c[0].destroy()
                card_widgets.remove(c)

        by_id = {}
        for c in list(card_widgets):
            if c[2] is not None and c[3] is not None:
                by_id[_alert_id(c[3])] = c
        seen: set = set()
        for a in reversed(alerts):
            aid = _alert_id(a)
            seen.add(aid)
            if aid in by_id:
                card, refs, _body, old = by_id[aid]
                sev = str(a.get("severity", "info")).lower()
                color = SEV_COLOR.get(sev, "#5ac8fa")
                title, body, _actions = _human_frame(a)
                refs["title_l"].configure(text=title, fg=FG_BRIGHT)
                refs["preview_l"].configure(text=body)
                for w in (refs["card"], refs["head"], refs["title_l"], refs["preview_l"]):
                    w.configure(highlightbackground=color)
                entry = [card, refs, _body, a]
                card_widgets[card_widgets.index(by_id[aid])] = entry
            else:
                card, refs = _build_card(list_frame, a)
                card.pack(fill="x", padx=4, pady=3)
                card_widgets.append([card, refs, None, a])

        for c in list(card_widgets):
            if c[3] is not None and _alert_id(c[3]) not in seen:
                c[0].destroy()
                card_widgets.remove(c)

    def _on_action(key, alert):
        if key == "block":
            ip = _extract_ip(str(alert.get("detail", "")))
            if not ip:
                _set_feedback("⚠ no IP found in detail to block")
                return
            _set_feedback(_block_feedback(ip, f"manual: {alert.get('kind', '?')}"))
        elif key == "audit":
            _open_log()
        elif key == "ack":
            _set_feedback("✓ Acknowledged (noted in session)")
        elif key == "dismiss":
            _dismiss(alert)

    def _dismiss(alert):

        dismissed_ids.add(_alert_id(alert))
        _apply_filters()

    def _open_log(_e=None):
        log_candidates = [
            Path.home() / ".cortexagent" / "logs" / "overseer.log",
            Path.home() / "security-console" / "overseer" / "overseer.log",
            HONEYPOT_LOG,
            EXTRA_FEED,
        ]
        target = next((p for p in log_candidates if p.exists()), None)
        if not target:
            _set_feedback("⚠ no log file found to open")
            return
        try:
            subprocess.Popen(
                ["xdg-open", str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _set_feedback(f"📄 Opened {target.name}")
        except Exception as e:
            _set_feedback(f"⚠ could not open log: {e}")


    last_action: list = ["Ready"]

    def _set_feedback(text: str) -> None:

        last_action[0] = text
        footer.configure(text=text, fg=FG_BRIGHT)

    footer = tk.Label(inner,
                      text="Ready", bg=BG_PANEL, fg=FG_BRIGHT,
                      font=("-size", 11), anchor="w")
    footer.pack(fill="x", padx=16, pady=(4, 12))


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


    last_poll_ts: list = [time.time()]

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
        status_main.configure(text=_severity_bar(alerts), fg=FG_BRIGHT)
        status_sub.configure(
            text=f"Watching · max {max_sev.upper()} · refresh 2s")

        crit_n = sum(1 for a in alerts
                     if str(a.get("severity", "")).lower() == "critical")
        high_n = sum(1 for a in alerts
                     if str(a.get("severity", "")).lower() == "high")
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
                bg="#3a1010", fg="#ff8080")
        elif crit_n > 0:
            plan_text.configure(
                text=f"⚠️ Action: review {crit_n} critical alert{'s' if crit_n != 1 else ''}.",
                bg="#3a2010", fg="#ffaa50")
        elif high_n > 0:
            plan_text.configure(
                text=f"⚠️ Action: review {high_n} high-severity alert{'s' if high_n != 1 else ''}.",
                bg="#3a3010", fg="#ffd54f")
        else:
            plan_text.configure(
                text="✅ No critical action — review new alerts at your pace.",
                bg="#1a3050", fg="#5ac8fa")

    def _update_footer(alerts):
        footer.configure(text=last_action[0], fg=FG_BRIGHT)

    def _apply_filters():
        alerts = _merge_and_sort(limit=200)
        last_poll_ts[0] = time.time()


        filtered = [a for a in alerts if _alert_id(a) not in dismissed_ids]
        _update_status(filtered)
        _update_footer(filtered)
        _render_alerts(filtered, in_place=True)

    def _refresh():
        try:
            _apply_filters()
        except Exception as e:
            status_sub.configure(text=f"⚠️ refresh error: {e}")
        finally:
            if root.winfo_exists():
                root.after(2000, _refresh)

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
