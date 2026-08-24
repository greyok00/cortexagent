
from __future__ import annotations

import datetime
import os
import subprocess
import threading
from typing import Callable, Sequence


_SEV = {
    "critical": "#c0392b",
    "high":     "#d35400",
    "warning":  "#e67e22",
    "medium":   "#e67e22",
    "info":     "#2e86c1",
    "normal":   "#1f6f5f",
    "ok":       "#1e8449",
}
_DEFAULT = "#34495e"
_AUTO_MS = 6000


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _notify_send_fallback(title: str, message: str, severity: str,
                          timeout_ms: int) -> None:

    urgency = {"critical": "critical", "high": "critical",
               "medium": "normal", "info": "normal"}.get(severity.lower(), "normal")
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-t", str(timeout_ms), title, message],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


def _run_callback(fn: Callable) -> None:

    try:
        fn()
    except Exception:
        pass


def _build_window(title: str, message: str, severity: str,
                  actions: Sequence[tuple[str, Callable]]) -> None:

    import tkinter as tk
    from tkinter import font as tkfont

    accent = _SEV.get(severity.lower(), _DEFAULT)
    sev_label = (severity.upper() if severity else "ALERT")

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)

    W, H = 460, 300
    root.geometry(f"{W}x{H}+{root.winfo_screenwidth() - W - 24}+24")
    root.configure(bg="#f4f6f7")
    root.attributes("-topmost", True)
    f = tkfont.Font


    tk.Frame(root, bg=accent, height=6).pack(fill="x")
    head = tk.Frame(root, bg=accent, padx=14, pady=8)
    head.pack(fill="x")
    tk.Label(head, text=sev_label, bg=accent, fg="#ffffff",
             font=f(size=11, weight="bold")).pack(side="left")
    tk.Label(head, text=title, bg=accent, fg="#ffffff",
             font=f(size=11, weight="bold"), anchor="w").pack(side="left", padx=10)


    body = tk.Frame(root, bg="#f4f6f7", padx=14, pady=10)
    body.pack(fill="both", expand=True)
    tk.Label(body, text=message, bg="#f4f6f7", fg="#22272b",
             font=f(size=12), justify="left", anchor="nw",
             wraplength=W - 40).pack(fill="both", expand=True)


    ts = datetime.datetime.now().strftime("%H:%M:%S")
    foot = tk.Frame(root, bg="#eef1ee", padx=10, pady=8)
    foot.pack(fill="x", side="bottom")
    tk.Label(foot, text=ts, bg="#eef1ee", fg="#7f8c8d",
             font=f(size=10)).pack(side="left")
    btns = tk.Frame(foot, bg="#eef1ee")
    btns.pack(side="right")

    def close():
        try:
            root.destroy()
        except Exception:
            pass

    tk.Button(btns, text="Acknowledge", command=close, bg=accent, fg="#ffffff",
              relief="flat", padx=12, pady=4,
              font=f(size=10, weight="bold")).pack(side="left", padx=4)
    for label, fn in actions:
        tk.Button(btns, text=label, command=lambda fn=fn: (_run_callback(fn), close()),
                  bg="#ffffff", fg="#22272b", relief="flat", padx=12, pady=4,
                  font=f(size=10)).pack(side="left", padx=4)

    root.after(_AUTO_MS, close)
    root.mainloop()


def show_alert(title: str, message: str, severity: str = "info",
               timeout_ms: int = 8000,
               actions: Sequence[tuple[str, Callable]] = ()) -> None:

    if not _has_display():
        _notify_send_fallback(title, message, severity, timeout_ms)
        return
    try:
        threading.Thread(
            target=_build_window,
            args=(title, message, severity, list(actions)),
            daemon=True,
        ).start()
    except Exception:
        _notify_send_fallback(title, message, severity, timeout_ms)
