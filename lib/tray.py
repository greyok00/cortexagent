#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



if sys.platform == "linux":
    os.environ.setdefault("PYSTRAY_BACKEND", "gtk")

from lib.config import CFG  # noqa: E402

CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
    "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
if not sys.stderr.isatty():
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""

_OVERSEER = _REPO_ROOT / "lib" / "overseer.py"
_CLI = _REPO_ROOT / "engine" / "cli.py"
_LAUNCHER = _REPO_ROOT / "bin" / "cortexagent"




_LABEL_START = "Start Model"
_LABEL_STOP = "Stop Model"




_ICON = None


def _log(msg: str, emoji: str = "", color: str = "") -> None:
    print(f"{color}{emoji} {BOLD}tray{RST} {msg}{RST}", file=sys.stderr, flush=True)




def _overseer_pid() -> Optional[int]:
    pid_file = CFG.state_dir / "overseer.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        return None


def _overseer_start() -> bool:
    if _overseer_pid():
        _log("overseer already running", "🟢", GREEN)
        return True
    _log("starting overseer…", "🔄", CYAN)
    r = subprocess.run([sys.executable, str(_OVERSEER), "start"],
                       capture_output=True, text=True, timeout=30)
    ok = _overseer_pid() is not None
    _log(("overseer up" if ok else "overseer FAILED to start"),
         "✅" if ok else "❌", GREEN if ok else RED)
    if not ok and r.stderr:
        _log(r.stderr.strip()[:300], "", RED)
    return ok


def _overseer_stop() -> bool:
    _log("stopping overseer…", "🛑", YELLOW)
    r = subprocess.run([sys.executable, str(_OVERSEER), "stop"],
                       capture_output=True, text=True, timeout=40)

    stopped = _overseer_pid() is None
    _log(("overseer stopped" if stopped else "overseer stop incomplete"),
         "✅" if stopped else "⚠️", GREEN if stopped else YELLOW)
    return stopped


def _overseer_restart() -> bool:
    _overseer_stop()
    time.sleep(1)
    return _overseer_start()




def _run_cli(*args: str, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run([sys.executable, str(_CLI), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _status_text() -> str:
    rc, out = _run_cli("status", timeout=10)
    ov = _overseer_pid()
    ov_line = f"overseer: {'🟢 up (pid %d)' % ov if ov else '🔴 down'}"
    if rc == 0:
        return f"{out}\n{ov_line}"
    return f"{RED}daemon down — start with `cortexagent daemon start`{RST}\n{ov_line}"


def _stop_big() -> str:

    _log("stopping model…", "🛑", YELLOW)
    try:
        from lib import control
        r = control.send_request("unload", which="big", timeout=30)
        return "Model stopped" if r.get("ok") else f"stop failed: {r}"
    except Exception as e:
        return f"stop failed: {e}"


def _start_big() -> str:

    _log("starting model…", "🔄", CYAN)
    try:
        from lib import control
        r = control.send_request("load", which="big", timeout=320)
        return "Model started" if r.get("ok") else f"start failed: {r}"
    except Exception as e:
        return f"start failed: {e}"


def _is_big_running() -> bool:

    try:
        from lib import control
        r = control.send_request("status", timeout=5)
        if r.get("ok"):
            big = r.get("big") or {}
            return bool(big.get("running"))
    except Exception:
        pass
    return False


def _toggle_big() -> str:

    if _is_big_running():
        return _stop_big()
    return _start_big()


def _reload_models() -> str:
    _log("reloading models (all)…", "🔄", CYAN)
    rc, out = _run_cli("models", "reload", "all", timeout=300)
    _log(("models reloaded" if rc == 0 else "model reload failed"),
         "✅" if rc == 0 else "❌", GREEN if rc == 0 else RED)
    return out[-400:]


def _reload_config() -> str:

    _log("reloading config — restarting daemon + overseer…", "🔄", CYAN)

    from lib import control
    msgs = []
    try:
        control.send_request("shutdown", timeout=10)
        msgs.append("daemon shutdown sent")
    except Exception as e:
        msgs.append(f"daemon shutdown: {e}")
    time.sleep(2)
    r = subprocess.run([sys.executable, str(_REPO_ROOT / "lib" / "daemon.py"), "start"],
                       capture_output=True, text=True, timeout=30)
    msgs.append(f"daemon start: rc={r.returncode} {r.stdout.strip() or r.stderr.strip()}")
    _overseer_restart()
    _log("config reloaded", "✅", GREEN)
    return "\n".join(msgs)

_HEADLESS_HELP = (
    f"{DIM}headless keeper — keys:{RST} "
    f"{BOLD}s{RST}tatus  {BOLD}r{RST}eload models  "
    f"{BOLD}o{RST}verseer restart  {BOLD}c{RST}li launch  "
    f"{BOLD}q{RST}uit{DIM} (or Ctrl-C){RST}"
)


def _run_headless(quit_event: threading.Event) -> None:
    print(_HEADLESS_HELP)
    while not quit_event.is_set():
        sys.stdout.write(f"{BOLD}tray>{RST} ")
        sys.stdout.flush()

        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            break
        if not line:
            time.sleep(0.2)
            continue
        key = line.strip().lower()[:1]
        if key == "s":
            print(_status_text())
        elif key == "r":
            print(_reload_models())
        elif key == "o":
            print("overseer restart:", "ok" if _overseer_restart() else "failed")
        elif key == "q":
            break
        else:
            print(_HEADLESS_HELP)




def _patch_pystray_notify() -> None:

    try:
        import pystray._util.notify_dbus as nd
        orig_hide = getattr(nd, 'NotifyDBus', None)
        if orig_hide is None:

            for attr in dir(nd):
                cls = getattr(nd, attr)
                if hasattr(cls, 'hide') and hasattr(cls, '_notify'):
                    orig_hide = cls
                    break
        if orig_hide is not None:
            original_hide = orig_hide.hide
            def safe_hide(self, *args, **kwargs):
                try:
                    return original_hide(self, *args, **kwargs)
                except Exception:
                    pass
            orig_hide.hide = safe_hide
    except Exception:
        pass


def _make_icon_image():

    from PIL import Image, ImageDraw  # type: ignore

    for ext in ("png", "jpg"):
        logo = Path(__file__).resolve().parent.parent / "assets" / f"cortexagentsquarelogo.{ext}"
        if logo.exists():
            try:
                return Image.open(logo).convert("RGBA").resize((64, 64), Image.LANCZOS)
            except Exception:
                pass
    img = Image.new("RGBA", (64, 64), (15, 17, 21, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=12, fill=(150, 220, 255, 255))

    d.rectangle([16, 18, 22, 46], fill=(15, 17, 21, 255))
    d.rectangle([16, 18, 30, 24], fill=(15, 17, 21, 255))
    d.rectangle([16, 31, 28, 37], fill=(15, 17, 21, 255))
    d.rectangle([40, 18, 46, 46], fill=(15, 17, 21, 255))
    d.rectangle([40, 18, 54, 24], fill=(15, 17, 21, 255))
    d.rectangle([40, 40, 54, 46], fill=(15, 17, 21, 255))
    return img


def _run_gui(quit_event: threading.Event) -> None:
    _patch_pystray_notify()
    import pystray  # type: ignore
    from pystray import MenuItem as MI, Menu  # type: ignore

    def _toast(icon, msg, kind="info"):
        try:
            icon.notify(msg, "Cortex")
        except Exception:
            pass
        _log(msg, "ℹ️", CYAN if kind == "info" else (GREEN if kind == "ok" else RED))

    def on_stop_big(icon, item):
        _toast(icon, _stop_big(), "ok")

    def on_start_big(icon, item):
        _toast(icon, _start_big(), "ok")

    def on_reload(icon, item):
        _toast(icon, _reload_models(), "ok")

    def on_restart_ov(icon, item):
        _toast(icon, "overseer restart: " + ("ok" if _overseer_restart() else "failed"), "ok")

    def on_reload_cfg(icon, item):
        _toast(icon, _reload_config(), "ok")

    def on_toggle_big(icon, item):

        _toast(icon, _toggle_big(), "ok")
        try:
            icon.update_menu()
        except Exception:
            pass

    def _big_label_text(_item) -> str:

        return _LABEL_STOP if _is_big_running() else _LABEL_START

    def _big_action_wrapper(icon, item) -> None:

        on_toggle_big(icon, item)

    def on_dashboard(icon, item):

        try:
            import importlib
            import lib.tray_dashboard  # noqa: F401  (ensure registered)
            from lib import tray_dashboard as _td
            try:
                _td = importlib.reload(_td)
            except Exception as reload_err:
                _log(f"dashboard reload failed: {reload_err}", "⚠️", YELLOW)
            t = threading.Thread(target=_td.open_dashboard,
                                  daemon=True, name="tray-dashboard")
            t.start()
            _log("opened overseer dashboard", "📊", CYAN)
        except Exception as e:
            _log(f"failed to open dashboard: {e}", "⚠️", YELLOW)

    def on_quit(icon, item):
        _log("Quit — tearing down overseer", "🛑", YELLOW)
        quit_event.set()



        try:
            icon.stop()
        except Exception:
            pass
        _overseer_stop()



        try:
            if _is_big_running():
                _log(_stop_big(), "🛑", YELLOW)
        except Exception as e:
            _log(f"big model unload on quit failed: {e}", "⚠️", YELLOW)


    def on_browser_console(icon, item):

        try:
            import importlib
            import lib.browser_console as _bc
            _bc = importlib.reload(_bc)
            if _bc._is_open():
                _bc.close()
                _toast(icon, "Console closed", "ok")
            elif _bc.raise_existing():
                _toast(icon, "Console raised", "ok")
            else:
                _bc.open_in_thread()
                _toast(icon, "Console opened", "ok")
        except Exception as e:
            _toast(icon, f"Failed to toggle Console: {e}", "info")
        try:
            icon.update_menu()
        except Exception:
            pass

    def on_open_terminal(icon, item):
        "Open just the plain terminal CLI in a fresh terminal window."
        import shutil
        import sys as _sys
        import subprocess as _sp
        from pathlib import Path
        script = str(Path(__file__).resolve().parent.parent / "bin" / "cortexagent")
        for term, flag in (
            ("x-terminal-emulator", "-e"),
            ("gnome-terminal", "--"),
            ("mate-terminal", "--"),
            ("xfce4-terminal", "--"),
            ("konsole", "-e"),
            ("terminator", "-x"),
            ("xterm", "-e"),
        ):
            path = shutil.which(term)
            if not path:
                continue
            try:
                _sp.Popen([path, flag, "bash", script], stdout=_sp.DEVNULL,
                          stderr=_sp.DEVNULL, stdin=_sp.DEVNULL,
                          env={**os.environ, "CORTEXAGENT_TRAY_ONLY": "0"},
                          start_new_session=True)
                _toast(icon, "Terminal opened", "ok")
            except Exception as e:
                _toast(icon, f"Terminal launch failed: {e}", "info")
            try:
                icon.update_menu()
            except Exception:
                pass
            return
        _toast(icon, "No terminal emulator found", "info")

    def _console_label_text(_item) -> str:
        try:
            import importlib, lib.browser_console as _bc
            _bc = importlib.reload(_bc)
            return "Close Console" if _bc._is_open() else "Open Console"
        except Exception:
            return "Open Console"

    menu = Menu(
        MI("Cortex", None, enabled=False),
        Menu.SEPARATOR,
        MI(_console_label_text, on_browser_console),
        Menu.SEPARATOR,
        MI("Open in Terminal", on_open_terminal),
        Menu.SEPARATOR,
        MI(_big_label_text, _big_action_wrapper),
        Menu.SEPARATOR,
        MI("Quit", on_quit),
    )
    icon = pystray.Icon("cortexagent", _make_icon_image(),
                        "Cortex", menu)


    try:
        icon.on_activate = on_dashboard
    except Exception:
        pass
    _log("tray icon running — close it via the menu's Quit to stop the overseer",
         "🟢", GREEN)
    global _ICON
    _ICON = icon









    def _refresh_tick():
        try:
            icon.update_menu()
        except Exception:
            pass
        t = threading.Timer(3.0, _refresh_tick)
        t.daemon = True
        t.start()
    _refresh_tick()

    icon.run()




def _have_pystray() -> bool:
    try:
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


def check() -> int:

    print(f"pystray: {'installed' if _have_pystray() else 'NOT installed (headless mode)'}")
    try:
        import PIL  # noqa: F401
        print("Pillow: installed")
    except Exception:
        print("Pillow: NOT installed")
    print(f"overseer running: {_overseer_pid() is not None}")
    return 0


def _signal_shutdown(quit_event: threading.Event) -> None:
    def handler(signum, frame):
        _log(f"signal {signum} — tearing down overseer and exiting", "🛑", YELLOW)
        quit_event.set()



        icon = _ICON
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        _overseer_stop()



        try:
            if _is_big_running():
                _log(_stop_big(), "🛑", YELLOW)
        except Exception as e:
            _log(f"big model unload on signal failed: {e}", "⚠️", YELLOW)
    return handler


def run(force_headless: bool = False) -> int:
    quit_event = threading.Event()
    signal.signal(signal.SIGINT, _signal_shutdown(quit_event))
    signal.signal(signal.SIGTERM, _signal_shutdown(quit_event))


    _overseer_start()

    use_gui = (not force_headless) and _have_pystray()
    if use_gui:
        _log("pystray found — starting GUI tray", "🖥️", CYAN)
        try:
            _run_gui(quit_event)
        except Exception as e:
            _log(f"GUI tray failed ({e}) — falling back to headless keeper", "⚠️", YELLOW)
            _run_headless(quit_event)
    else:
        if not force_headless:
            _log("pystray not installed — running headless keeper. "
                 "Install it for the system-tray icon:  pip install pystray Pillow",
                 "⚠️", YELLOW)
        _run_headless(quit_event)


    if _overseer_pid():
        _overseer_stop()




    try:
        if _is_big_running():
            _log(_stop_big(), "🛑", YELLOW)
    except Exception as e:
        _log(f"big model unload on exit failed: {e}", "⚠️", YELLOW)
    _log("tray exited", "✅", GREEN)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        return check()
    force_headless = "--headless" in args
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    return run(force_headless=force_headless)


if __name__ == "__main__":
    sys.exit(main())