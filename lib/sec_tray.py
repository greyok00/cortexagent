#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path



_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


if sys.platform == "linux":
    os.environ.setdefault("PYSTRAY_BACKEND", "gtk")



import pystray                                       # noqa: E402
from PIL import Image, ImageDraw                     # noqa: E402





import lib.sec_controls as _sec                      # noqa: E402





_SEV_ORDER = ["critical", "high", "medium", "low", "info"]
_SEV_COLOR = dict(_sec.SEV_COLOR)
_STALE_COLOR = "#666666"
_CLEAR_COLOR = "#5ac8fa"
_DEFAULT_BG = "#1a1a2e"




_POLL_SEC = 2.0


_ALERT_LIMIT = 40


_popout_thread: dict[str, object] = {"t": None, "root": None, "lock": threading.Lock()}




def _make_padlock_image(fill_hex: str) -> Image.Image:

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)


    body = [10, 26, 54, 58]
    d.rounded_rectangle(body, radius=6, fill=fill_hex, outline="#ffffff",
                        width=2)



    arch_outer = [18, 6, 46, 34]
    d.arc(arch_outer, start=180, end=360, fill="#ffffff", width=4)


    cx, cy = 32, 40
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill="#ffffff")
    d.rectangle([cx - 1.5, cy, cx + 1.5, cy + 9], fill="#ffffff")
    return img




def _max_severity(alerts: list[dict]) -> str | None:

    if not alerts:
        return None
    severities = {str(a.get("severity", "info")).lower() for a in alerts}
    for sev in _SEV_ORDER:
        if sev in severities:
            return sev
    return "info"


def _pick_color(severity: str | None) -> tuple[str, str]:

    if severity is None:
        return _CLEAR_COLOR, "clear"
    if severity not in _SEV_COLOR:
        return _CLEAR_COLOR, "clear"
    return _SEV_COLOR[severity], severity




def _open_popout_singleton() -> None:

    with _popout_thread["lock"]:
        existing = _popout_thread["t"]
        root = _popout_thread["root"]
        if existing is not None and existing.is_alive() and root is not None:



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




def _action_open(icon, _item) -> None:


    _open_popout_singleton()


def _action_refresh(icon, _item) -> None:

    _update_icon_now(icon)


def _action_clear_logs(icon, _item) -> None:

    for path in (_sec.HONEYPOT_LOG, _sec.EXTRA_FEED):
        try:
            if path.exists():


                if path == _sec.EXTRA_FEED:
                    path.write_text("[]\n")
                else:
                    path.write_text("")
        except OSError:



            pass
    _update_icon_now(icon)


def _action_quit(icon, _item) -> None:


    icon.stop()




def _format_tooltip(alerts: list[dict], severity: str | None) -> str:

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

    try:
        alerts = _sec._merge_and_sort(limit=_ALERT_LIMIT)  # noqa: SLF001
    except Exception:

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



    _update_icon_now(icon)
    while not stop_event.is_set():


        if stop_event.wait(timeout=_POLL_SEC):
            break
        _update_icon_now(icon)




def _build_icon() -> pystray.Icon:



    menu = pystray.Menu(
        pystray.MenuItem("🛡  Open Security Tracker", _action_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🔄  Refresh icon", _action_refresh),
        pystray.MenuItem("🗑  Clear logs", _action_clear_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌  Quit", _action_quit),
    )


    return pystray.Icon(
        name="cortexagent-sec",
        icon=_make_padlock_image(_STALE_COLOR),
        title="Security: starting…",
        menu=menu,
    )


def main() -> int:
    icon = _build_icon()




    stop_event = threading.Event()
    poller = threading.Thread(
        target=_poll_loop, args=(icon, stop_event),
        daemon=True, name="sec-tray-poll",
    )
    poller.start()




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


        pass

    try:
        icon.run()
    finally:
        stop_event.set()
        poller.join(timeout=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
