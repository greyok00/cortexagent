#!/usr/bin/env python3
"""lib/stt_controls.py — Floating STT control box.

A small, always-on-top window with two big, easy-to-click buttons:

  ┌──────────────────────────────┐
  │  🎙️  STT Voice Controls     │
  │                              │
  │  ┌─────────────┐ ┌────────┐ │
  │  │  TOGGLE STT │ │ ENTER  │ │
  │  │             │ │        │ │
  │  └─────────────┘ └────────┘ │
  │                              │
  │  Status:  🔴 VAD OFF         │
  └──────────────────────────────┘

Usage:
    python3 -m lib.stt_controls   # open the window
    python3 lib/stt_controls.py   # same thing
"""
from __future__ import annotations

import sys
import threading
import time
import subprocess
import json
import socket
from pathlib import Path

# ── Socket helpers ────────────────────────────────────────────────────────────

STATE_FILE = Path.home() / ".cortexagent" / "state" / "stt_daemon.json"
SOCKET_PATH = Path.home() / ".cortexagent" / "state" / "stt.sock"


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _send_command(command: str, mode: str | None = None) -> dict:
    """Send command to the STT daemon via Unix socket."""
    payload = {"command": command}
    if mode:
        payload["mode"] = mode
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(str(SOCKET_PATH))
            s.sendall(json.dumps(payload).encode())
            resp = s.recv(4096).decode()
    except (ConnectionRefusedError, FileNotFoundError):
        return {"ok": False, "reason": "STT daemon not running"}
    return json.loads(resp) if resp else {"ok": False, "reason": "no response"}


def _start_daemon() -> bool:
    """Start the STT daemon if it's not running."""
    r = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "stt_daemon.py"), "start"],
        capture_output=True, text=True, timeout=5
    )
    return r.returncode == 0 or _read_state().get("running")


def _daemon_alive() -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(str(SOCKET_PATH))
            s.sendall(b'{"command": "ping"}')
            resp = s.recv(4096).decode()
            return '"ok": true' in resp
    except Exception:
        return False


def _is_vad_on() -> bool:
    state = _read_state()
    return state.get("modes", {}).get("vad", False)


# ── Tkinter UI ────────────────────────────────────────────────────────────────

def _make_window() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("⚠️ Tkinter not available")
        return

    root = tk.Tk()
    root.title("CortexAgent STT")
    root.resizable(False, False)
    # ── Focus suppression ──────────────────────────────────────────────────
    # Goal: the window is ALWAYS-ON-TOP (visible above the terminal) but
    # NEVER takes keyboard focus. The user's terminal stays active so
    # pressing Enter there submits prompts; mouse clicks on this window
    # still fire on its inner widgets because Tk processes events on
    # any visible window regardless of focus.
    #
    # The reliable approach on MATE/Marco (and most EWMH WMs):
    #   1. Set _NET_WM_WINDOW_TYPE = DOCK. Dock windows are guaranteed
    #      by the spec to never take focus. Marco respects this.
    #   2. Set _NET_WM_STATE_ABOVE explicitly so we stay on top.
    #   3. Override WM_TAKE_FOCUS protocol with a no-op so even if the
    #      WM sends the message, Tk does not accept the focus.
    #   4. NEVER call lift(), focus_set(), or focus_force().
    #   5. As a final safety net, push focus back to the previously
    #      active window via xdotool after the window is mapped. This
    #      defeats any WM that ignores the DOCK type hint.
    #
    # Note: the trade-off of DOCK over UTILITY is that dock windows
    # don't get a taskbar entry. That's exactly what we want — the
    # STT window is a utility surface, not a primary app.
    root.wm_attributes("-type", "dock")
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.99)
    root.configure(bg="#1a1a2e")
    # Larger so the buttons are easy to hit on a 4K screen. Pinned to
    # the bottom-right corner of the workarea with a clear margin so
    # the window doesn't fight with the panel/taskbar. The window is
    # draggable via the custom title bar (see below) so the user can
    # move it if needed. The geometry is set AFTER the type/topmost
    # attributes — DOCK windows sometimes have their initial position
    # overridden by the WM if the geometry is set before the type
    # attribute is applied.
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win_w, win_h = 360, 220
    margin = 16
    x = sw - win_w - margin
    y = sh - win_h - margin
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.update_idletasks()
    # Capture the previously-active window BEFORE we map.
    try:
        import subprocess
        prev_active = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=1,
        ).stdout.strip()
    except Exception:
        prev_active = ""
    # Reject WM_TAKE_FOCUS. The WM will still send the message but
    # Tk no longer accepts it as a focus grant.
    root.protocol("WM_TAKE_FOCUS", lambda: None)
    # If focus arrives anyway (some WMs ignore DOCK), bind <FocusIn>
    # to push it back to the previous window after the event loop is
    # idle. This reverts the focus steal before Tk has a chance to
    # propagate it to child widgets.
    def _restore_focus(wid):
        try:
            if not wid or not wid.isdigit():
                return
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", wid],
                capture_output=True, timeout=1,
            )
        except Exception:
            pass
    root.bind("<FocusIn>", lambda _e: root.after_idle(
        lambda: _restore_focus(prev_active)))
    # Push focus back over the first few seconds as a final safety net.
    # Marco's "focus the new topmost window" behaviour happens on map
    # and a few subsequent events; the spam ends quickly.
    def _spam_then_quiet(steps_left: int):
        if prev_active:
            _restore_focus(prev_active)
        if steps_left > 0:
            root.after(120, _spam_then_quiet, steps_left - 1)
        else:
            # Hand control to the long-running topmost refresh so the
            # window stays above the rest of the desktop.
            def _stay_topmost():
                try:
                    root.attributes("-topmost", True)
                except Exception:
                    pass
                root.after(3000, _stay_topmost)
            root.after(0, _stay_topmost)
    root.after(80, _spam_then_quiet, 25)

    # ── Title bar (drag handle + close button) ─────────────────────────
    # The WM is set to DOCK type with no decorations, so the title bar
    # is a custom Tk frame. We bind <Button-1> + <B1-Motion> to make the
    # entire bar a drag handle so the user can reposition the window.
    # The X button at the right corner actually closes the window.
    def _on_title_click(event):
        # Only start a drag if the click is on the title bar itself,
        # not on the close button (which has its own <Button-1> binding).
        # Use event.widget to test: the title_bar frame and the title
        # label both have the drag bindings; the close button does not.
        if event.widget is close_btn:
            return
        _drag_data["x"] = event.x_root
        _drag_data["y"] = event.y_root

    def _on_title_drag(event):
        dx = event.x_root - _drag_data["x"]
        dy = event.y_root - _drag_data["y"]
        _drag_data["x"] = event.x_root
        _drag_data["y"] = event.y_root
        try:
            x = root.winfo_x() + dx
            y = root.winfo_y() + dy
            root.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _on_title_release(_event):
        # Clamp the final position so the window can't be dragged off-screen.
        try:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = max(0, min(root.winfo_x(), sw - root.winfo_width()))
            y = max(0, min(root.winfo_y(), sh - root.winfo_height()))
            root.geometry(f"+{x}+{y}")
        except Exception:
            pass

    _drag_data = {"x": 0, "y": 0}

    title_bar = tk.Frame(root, bg="#3a3a5e", height=36)
    title_bar.pack(fill="x", padx=0, pady=(0, 0))
    title_bar.pack_propagate(False)
    title_bar.bind("<Button-1>", _on_title_click)
    title_bar.bind("<B1-Motion>", _on_title_drag)
    title_bar.bind("<ButtonRelease-1>", _on_title_release)

    # Close button (X) on the right — has its own binding that overrides
    # the drag bindings via the widget-identity check in _on_title_click.
    def _on_close_click(_event=None):
        root.destroy()

    close_btn = tk.Label(title_bar, text="✕", bg="#3a3a5e", fg="#ff5252",
                         font=("TkDefaultFont", 14, "bold"),
                         cursor="hand2", padx=10)
    close_btn.pack(side="right", padx=(0, 6), pady=4)
    close_btn.bind("<Button-1>", _on_close_click)
    close_btn.bind("<Enter>", lambda _e: close_btn.configure(bg="#5a1a1a"))
    close_btn.bind("<Leave>", lambda _e: close_btn.configure(bg="#3a3a5e"))

    # Title label — drag handle, also a visual marker. Different cursor
    # so the user knows it's draggable.
    title = tk.Label(title_bar, text="🎙  STT  ·  drag to move",
                     bg="#3a3a5e", fg="#e0e0e0",
                     font=("-size", 13, "-weight", "bold"),
                     cursor="fleur")
    title.pack(side="left", padx=16, pady=4, fill="x", expand=True)
    title.bind("<Button-1>", _on_title_click)
    title.bind("<B1-Motion>", _on_title_drag)
    title.bind("<ButtonRelease-1>", _on_title_release)
    title.bind("<Enter>", lambda _e: title.configure(bg="#4a4a6e"))
    title.bind("<Leave>", lambda _e: title.configure(bg="#3a3a5e"))

    # ── Buttons frame ──
    btn_frame = tk.Frame(root, bg="#1a1a2e")
    btn_frame.pack(pady=12, padx=20, fill="x")

    # STT Toggle button
    stt_btn = tk.Button(btn_frame, text="TOGGLE STT",
                        bg="#0d47a1", fg="white",
                        font=("-size", 18, "-weight", "bold"),
                        activebackground="#1565c0", activeforeground="white",
                        relief="flat", bd=0, padx=24, pady=18,
                        cursor="hand2")
    stt_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

    # Enter button
    enter_btn = tk.Button(btn_frame, text="ENTER ↵",
                          bg="#2e7d32", fg="white",
                          font=("-size", 18, "-weight", "bold"),
                          activebackground="#388e3c", activeforeground="white",
                          relief="flat", bd=0, padx=20, pady=18,
                          cursor="hand2")
    enter_btn.pack(side="right", fill="x", expand=True, padx=(6, 0))

    # ── Status label ──
    status_label = tk.Label(root, text="Status:  🔴 VAD OFF",
                            bg="#1a1a2e", fg="#e0e0e0",
                            font=("-size", 11))
    status_label.pack(pady=(6, 0), padx=20, fill="x")

    # ── Error label (for feedback) ──
    error_label = tk.Label(root, text="",
                           bg="#1a1a2e", fg="#ff5252",
                           font=("-size", 10))
    error_label.pack(pady=(4, 0), padx=20, fill="x")

    # ── Actions ──
    def on_toggle():
        """Toggle STT VAD on/off."""
        try:
            # Start daemon if needed
            if not _daemon_alive():
                _start_daemon()
                time.sleep(0.5)

            vad_on = _is_vad_on()
            target = "vad" if not vad_on else "off"
            resp = _send_command("set-mode", target)

            if resp.get("ok"):
                status_label.config(
                    text=f"Status:  {'🟢 VAD ON' if target == 'vad' else '🔴 VAD OFF'}"
                )
                stt_btn.config(text="TOGGLE STT", bg="#0d47a1")
            else:
                status_label.config(text=f"Status:  ⚠️ {resp.get('reason', 'error')}")

            error_label.config(text="")
        except Exception as e:
            error_label.config(text=f"⚠️ toggle error: {e}")
        finally:
            stt_btn.config(state="disabled")
            root.after(800, lambda: stt_btn.config(state="normal"))

    def on_enter():
        """Send Enter key via xdotool."""
        try:
            subprocess.run(["xdotool", "key", "Return"], check=True, timeout=5)
        except Exception as e:
            error_label.config(text=f"⚠️ xdotool failed: {e}")
            return
        enter_btn.config(state="disabled")
        root.after(300, lambda: enter_btn.config(state="normal"))

    stt_btn.config(command=on_toggle)
    enter_btn.config(command=on_enter)

    # ── Periodic status refresh ──
    def refresh_status():
        """Update status label periodically."""
        if _is_vad_on():
            status_label.config(text="Status:  🟢 VAD ON")
        else:
            status_label.config(text="Status:  🔴 VAD OFF")
        root.after(2000, refresh_status)

    refresh_status()

    # ── Run ──
    root.mainloop()


def open_in_thread() -> threading.Thread:
    """Open the STT controls window in a background thread."""
    t = threading.Thread(target=_make_window, daemon=True, name="stt-controls")
    t.start()
    return t


def main() -> int:
    _make_window()
    return 0


if __name__ == "__main__":
    sys.exit(main())
