#!/usr/bin/env python3
"""lib/sec_tray.py — Standalone Security Tracker tray icon.

A small, SEPARATE pystray-based system tray icon that:

  - Lives in its own process (and its own systemd user service,
    ``cortexagent-sec.service``) so killing the CortexAgent tray does
    NOT take the security icon down with it.
  - Visually distinguishes itself from the CA wolf head: a 64×64 PIL-drawn
    padlock whose fill color encodes the current max severity.
  - Opens the existing ``lib.sec_controls`` Tk popout on left-click.
  - Polls ``~/honeypot/alerts.log`` and
    ``~/Documents/RecordRelief/webapp/data/alerts.json`` every 2s and updates
    its icon + tooltip when the severity picture changes.

This module does NOT reimplement the alert rendering/filtering — it imports
``lib.sec_controls`` and reuses its public helpers. The popout is the same
window the user already approved.

Entry point::

    python3 -m lib.sec_tray            # run the tray (no CLI args)

Architecture::

    ┌─────────────────────────────┐
    │ Main thread (this process)  │   pystray Icon.run() blocks here.
    │   ↳ GLib main loop          │   pystray owns this thread; never call
    │     ↳ icon.icon = new_image │   Tk widgets from here.
    │     ↳ icon.update_menu()    │
    └─────────────────────────────┘
                ↕ threading.Event / .after()
    ┌─────────────────────────────┐
    │ Tk thread (spawned on click)│   Runs ``_make_window()`` from
    │   ↳ Tk mainloop             │   ``lib.sec_controls`` exactly as the
    │     ↳ canvas, scrollbar,    │   existing tray used to.
    │       filter chips, buttons │
    └─────────────────────────────┘

GTK backend only — mirrors the existing ``lib/tray.py`` choice
(``PYSTRAY_BACKEND=gtk``) so it works on MATE/XFCE/KDE/XFCE status notifiers
without the AppIndicator sandboxing that breaks MATE.

Local-only, never committed (matches ``lib/sec_controls.py`` convention).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Repo root on sys.path so `lib.sec_controls` resolves no matter how the
# process is launched (systemd runs `python3 -m lib.sec_tray`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Force GTK backend on Linux — same as the existing tray.
if sys.platform == "linux":
    os.environ.setdefault("PYSTRAY_BACKEND", "gtk")

# Lazy imports after sys.path setup so a failure here is a real, loud error
# rather than a missing-module traceback in the systemd log.
import pystray                                       # noqa: E402
from PIL import Image, ImageDraw                     # noqa: E402

# Reuse the existing popout's public symbols. NEVER reload this module — the
# popout owns live Tk threads and reloading would tear down their interpreter
# state mid-render. If the user edits sec_controls.py they restart this
# service to pick up the change.
import lib.sec_controls as _sec                      # noqa: E402

# ── Severity ordering for the at-a-glance icon ──────────────────────────────
# Same colors as ``lib/sec_controls.SEV_COLOR`` so the tray icon and the
# popout chips line up. We compute max severity over the most recent 40
# entries and pick the corresponding color.
_SEV_ORDER = ["critical", "high", "medium", "low", "info"]
_SEV_COLOR = dict(_sec.SEV_COLOR)  # copy so we don't mutate the popout's map
_STALE_COLOR = "#666666"          # grey = watcher down / files unreadable
_CLEAR_COLOR = "#5ac8fa"          # blue = no alerts in last 40
_DEFAULT_BG = "#1a1a2e"           # matches popout chrome (unused in v1 but
                                  # kept for future "icon border" work)

# Polling cadence. Matches the popout's own 2s refresh so the icon and the
# list never disagree by more than one tick.
_POLL_SEC = 2.0

# Cap on the merged alert list — same as the popout uses.
_ALERT_LIMIT = 40

# Process-local handle to the live popout thread (singleton enforcement).
_popout_thread: dict[str, object] = {"t": None, "root": None, "lock": threading.Lock()}


# ── Icon rendering ──────────────────────────────────────────────────────────

def _make_padlock_image(fill_hex: str) -> Image.Image:
    """Draw a 64×64 padlock in the given fill color (hex like '#ff3b30').

    The body is a rounded rectangle; the arch is a thick arc on top; the
    keyhole is a small white circle + slot in the center. White outline
    so the lock is visible on light AND dark panels.
    """
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Body: rounded rect filling the bottom 2/3 of the icon.
    body = [10, 26, 54, 58]
    d.rounded_rectangle(body, radius=6, fill=fill_hex, outline="#ffffff",
                        width=2)

    # Arch: thick C-shaped arc above the body. Approximated with two
    # overlapping ellipses (outer filled, inner cut out via overlay).
    arch_outer = [18, 6, 46, 34]
    d.arc(arch_outer, start=180, end=360, fill="#ffffff", width=4)

    # Keyhole: small white circle + slot.
    cx, cy = 32, 40
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill="#ffffff")
    d.rectangle([cx - 1.5, cy, cx + 1.5, cy + 9], fill="#ffffff")
    return img


# ── Severity computation ────────────────────────────────────────────────────

def _max_severity(alerts: list[dict]) -> str | None:
    """Return the most severe severity in `alerts` (None if list empty)."""
    if not alerts:
        return None
    severities = {str(a.get("severity", "info")).lower() for a in alerts}
    for sev in _SEV_ORDER:
        if sev in severities:
            return sev
    return "info"


def _pick_color(severity: str | None) -> tuple[str, str]:
    """Map severity to (color_hex, human_label) for the icon + tooltip."""
    if severity is None:
        return _CLEAR_COLOR, "clear"
    if severity not in _SEV_COLOR:
        return _CLEAR_COLOR, "clear"
    return _SEV_COLOR[severity], severity


# ── Popout lifecycle (singleton) ────────────────────────────────────────────

def _open_popout_singleton() -> None:
    """Open the popout in a background thread; raise the existing one if open.

    The popout is a top-level Tk window; we track the live ``root`` so a
    second click raises the existing window instead of stacking duplicates.
    """
    with _popout_thread["lock"]:
        existing = _popout_thread["t"]
        root = _popout_thread["root"]
        if existing is not None and existing.is_alive() and root is not None:
            # Try to raise + focus the existing window. Tk doesn't grab focus
            # by default on a dock-type window, but ``lift`` brings it to the
            # top of the stacking order so the user can see it.
            try:
                root.after(0, lambda: (
                    root.deiconify(),
                    root.lift(),
                    root.attributes("-topmost", True),
                    root.after(200, lambda: root.attributes("-topmost", True)),
                ))
            except Exception:
                pass
            return

        # Fresh popout. We can't use sec_controls._make_window directly
        # because that builds the root inline; instead we mirror it via the
        # public entry point and stash the resulting root by monkey-patching
        # the popout's own after-construction hook. Simpler: spawn a thread
        # that builds the window and we capture the root by patching Tk.
        captured: list[object] = []

        orig_init = None
        try:
            import tkinter as _tk
            orig_init = _tk.Tk.__init__

            def _capture_init(self, *a, **kw):
                orig_init(self, *a, **kw)
                captured.append(self)

            _tk.Tk.__init__ = _capture_init  # type: ignore[assignment]
            t = threading.Thread(
                target=_sec.open_in_thread,
                daemon=True, name="sec-popout",
            )
            t.start()
            # Give Tk a moment to construct the root.
            for _ in range(20):
                if captured:
                    break
                time.sleep(0.05)
            _popout_thread["t"] = t
            _popout_thread["root"] = captured[0] if captured else None
        finally:
            if orig_init is not None:
                import tkinter as _tk
                _tk.Tk.__init__ = orig_init  # type: ignore[assignment]


# ── Menu actions ────────────────────────────────────────────────────────────

def _action_open(icon, _item) -> None:
    # No pop-up notifications — user has them all in the log file. Icon
    # color + tooltip are enough confirmation; actions write to journalctl.
    _open_popout_singleton()


def _action_dashboard(icon, _item) -> None:
    """Launch the RecordRelief Security tab in the user's browser."""
    subprocess.Popen(
        ["xdg-open", _sec.RECORDRELIEF_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _action_refresh(icon, _item) -> None:
    """Force an immediate icon + tooltip refresh (skips the 2s timer)."""
    _update_icon_now(icon)


def _action_clear_logs(icon, _item) -> None:
    """Truncate both alert stores and refresh the icon immediately."""
    for path in (_sec.HONEYPOT_LOG, _sec.RECORDRELIEF_FEED):
        try:
            if path.exists():
                # Honeypot log is NDJSON — just truncate. RecordRelief feed
                # is a JSON array — write `[]\n` so JSON parsers stay happy.
                if path == _sec.RECORDRELIEF_FEED:
                    path.write_text("[]\n")
                else:
                    path.write_text("")
        except OSError:
            # Silent — failures show up on the next poll cycle via the
            # stale-grey icon. The user has the log file as the source of
            # truth; we don't need to interrupt them here.
            pass
    _update_icon_now(icon)


def _action_quit(icon, _item) -> None:
    """Tear down the tray and let systemd restart if configured to."""
    # icon.stop() requests shutdown; the main thread's icon.run() returns.
    icon.stop()


# ── Polling loop ────────────────────────────────────────────────────────────

def _format_tooltip(alerts: list[dict], severity: str | None) -> str:
    """Build the tray tooltip: 'Security: N alerts (M critical) · updated Xs ago'."""
    n = len(alerts)
    if severity is None:
        return f"Security: all clear · {n} alerts in last window"
    by_sev: dict[str, int] = {}
    for a in alerts:
        s = str(a.get("severity", "info")).lower()
        by_sev[s] = by_sev.get(s, 0) + 1
    parts = [f"{by_sev[s]} {s}" for s in _SEV_ORDER if by_sev.get(s)]
    breakdown = ", ".join(parts) if parts else "no alerts"
    return f"Security: {n} alerts ({breakdown}) · {severity.upper()}"


def _update_icon_now(icon) -> None:
    """Read the alert files, pick a color, swap the icon + tooltip."""
    try:
        alerts = _sec._merge_and_sort(limit=_ALERT_LIMIT)  # noqa: SLF001
    except Exception:
        # Files unreadable / corrupted — grey "stale" icon.
        try:
            icon.icon = _make_padlock_image(_STALE_COLOR)
            icon.title = "Security: watcher error"
        except Exception:
            pass
        return

    severity = _max_severity(alerts)
    color, _label = _pick_color(severity)
    try:
        icon.icon = _make_padlock_image(color)
        icon.title = _format_tooltip(alerts, severity)
    except Exception:
        pass


def _poll_loop(icon, stop_event: threading.Event) -> None:
    """Background poller. Runs every _POLL_SEC until the icon stops."""
    # First tick happens immediately so the user sees the right color
    # before the menu even appears.
    _update_icon_now(icon)
    while not stop_event.is_set():
        # Event.wait returns True if the event was set, False on timeout —
        # either way we just loop. This makes shutdown near-instant.
        if stop_event.wait(timeout=_POLL_SEC):
            break
        _update_icon_now(icon)


# ── Entry point ─────────────────────────────────────────────────────────────

def _build_icon() -> pystray.Icon:
    """Construct the pystray.Icon with menu + initial padlock image."""
    # Menu. ``default=True`` is what makes the GTK StatusIcon's left-click
    # fire this item (Icon.__call__ on activate → first default=True item).
    menu = pystray.Menu(
        pystray.MenuItem("🛡  Open Security Tracker", _action_open, default=True),
        pystray.MenuItem("🌐  Open dashboard", _action_dashboard),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🔄  Refresh icon", _action_refresh),
        pystray.MenuItem("🗑  Clear logs", _action_clear_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌  Quit", _action_quit),
    )
    # Start with a neutral "loading" padlock so the user sees something
    # before the first poll tick resolves.
    return pystray.Icon(
        name="cortexagent-sec",
        icon=_make_padlock_image(_STALE_COLOR),
        title="Security: starting…",
        menu=menu,
    )


def main() -> int:
    icon = _build_icon()

    # Polling thread (daemon) — separate from pystray's GLib loop so the
    # poll can call ``icon.icon = ...`` (which is @mainloop-decorated and
    # safely hops threads).
    stop_event = threading.Event()
    poller = threading.Thread(
        target=_poll_loop, args=(icon, stop_event),
        daemon=True, name="sec-tray-poll",
    )
    poller.start()

    # SIGTERM/SIGINT handler so `systemctl --user stop cortexagent-sec`
    # and pkill both cleanly remove the icon (otherwise the GTK status icon
    # sticks around as a stranded X window until the WM kills it).
    def _on_signal(signum, _frame):
        stop_event.set()
        try:
            icon.stop()
        except Exception:
            pass
    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except ValueError:
        # signal only works in main thread; we're already there but if a
        # future refactor moves this, fail soft.
        pass

    try:
        icon.run()
    finally:
        stop_event.set()
        poller.join(timeout=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
