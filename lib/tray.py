#!/usr/bin/env python3
"""lib/tray.py — the CortexAgent system-tray app that owns the overseer.

Launch with ``cortexagent tray`` (or pin it to a desktop shortcut / Windows
Start-menu entry). It is a SEPARATE PERSISTENT PROCESS from the CLI:

  - On start it brings up the overseer (``overseer.py start``).
  - "Launch CLI" opens a terminal running the agent. Closing that terminal /
    CLI does NOT touch the overseer — they are independent processes.
  - The menu offers manual model reload, overseer restart, and config reload.
  - ONLY quitting the tray stops the overseer (stability: the overseer survives
    CLI closes; only the tray's Quit tears it down).

GUI: uses ``pystray`` + ``Pillow`` if installed (cross-platform: Linux GTK/
AppIndicator, macOS, Windows). If pystray is absent, it falls back to a
HEADLESS keeper: owns the overseer just the same, reads single-key commands on
stdin (s/r/o/c/q) and exits cleanly on SIGINT/SIGTERM — so the stability
guarantee holds even on a headless box or without GUI deps.

CLI:
  python3 -m lib.tray             # run the tray (GUI if pystray present, else headless)
  python3 -m lib.tray --headless  # force headless keeper mode
  python3 -m lib.tray --check     # report deps + exit (no run)

No Ollama, no hardcoded home paths (all via lib.config.CFG).
"""
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

from lib.config import CFG  # noqa: E402

CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
    "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")
if not sys.stderr.isatty():
    CYAN = GREEN = YELLOW = RED = DIM = BOLD = RST = ""

_OVERSEER = _REPO_ROOT / "lib" / "overseer.py"
_CLI = _REPO_ROOT / "engine" / "cli.py"
_LAUNCHER = _REPO_ROOT / "bin" / "cortexagent"


def _log(msg: str, emoji: str = "", color: str = "") -> None:
    print(f"{color}{emoji} {BOLD}tray{RST} {msg}{RST}", file=sys.stderr, flush=True)


# ── Overseer ownership ───────────────────────────────────────────────────────

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
    # overseer stop also unloads the tiny model (frees VRAM)
    stopped = _overseer_pid() is None
    _log(("overseer stopped" if stopped else "overseer stop incomplete"),
         "✅" if stopped else "⚠️", GREEN if stopped else YELLOW)
    return stopped


def _overseer_restart() -> bool:
    _overseer_stop()
    time.sleep(1)
    return _overseer_start()


# ── Model + config actions (via the daemon control socket) ───────────────────

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


def _reload_models() -> str:
    _log("reloading models (all)…", "🔄", CYAN)
    rc, out = _run_cli("models", "reload", "all", timeout=300)
    _log(("models reloaded" if rc == 0 else "model reload failed"),
         "✅" if rc == 0 else "❌", GREEN if rc == 0 else RED)
    return out[-400:]


def _reload_config() -> str:
    """Reload config by restarting the daemon (re-reads config) + overseer."""
    _log("reloading config — restarting daemon + overseer…", "🔄", CYAN)
    # Stop daemon (graceful via socket), then start it fresh.
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


# ── Launch the CLI in a terminal (cross-platform) ────────────────────────────

def _cli_command() -> list[str]:
    """The command to run inside the terminal."""
    # Prefer the installed `cortexagent` on PATH; fall back to the repo launcher.
    if shutil.which("cortexagent"):
        return ["cortexagent"]
    return ["bash", str(_LAUNCHER)]


def _launch_cli() -> None:
    cmd = _cli_command()
    _log(f"launching CLI in a terminal: {' '.join(cmd)}", "🖥️", CYAN)
    try:
        if os.name == "nt":
            # Windows: open a new cmd window running the agent.
            subprocess.Popen(["cmd", "/c", "start", "CortexAgent", "cmd", "/k"] + cmd)
            return
        if sys.platform == "darwin":
            # macOS: open Terminal.
            subprocess.Popen(["open", "-a", "Terminal"] + cmd)
            return
        # Linux: pick the first available terminal emulator.
        candidates = [
            (["x-terminal-emulator", "-e"], True),   # Debian; -e takes a command
            (["gnome-terminal", "--"], False),        # -- then the cmd
            (["konsole", "-e"], True),
            (["xterm", "-e"], True),
        ]
        # Wrap the command so a shell resolves `cortexagent`/PATH + stays open on exit.
        sh_cmd = " ".join(c.replace("'", "'\\''") for c in cmd)
        wrap = f"bash -lc {sh_cmd!r}; exec bash"
        for term_args, use_e in candidates:
            term = term_args[0]
            if shutil.which(term):
                if term == "gnome-terminal":
                    full = term_args + ["bash", "-lc", sh_cmd]
                else:
                    full = term_args + ["bash", "-lc", sh_cmd]
                subprocess.Popen(full, start_new_session=True)
                _log(f"opened {term}", "✅", GREEN)
                return
        # Last resort: run in the background in this process's session.
        _log("no terminal emulator found — running CLI in background", "⚠️", YELLOW)
        subprocess.Popen(cmd, start_new_session=True)
    except Exception as e:
        _log(f"failed to launch CLI: {e}", "❌", RED)


# ── Headless keeper mode (no pystray) ────────────────────────────────────────

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
        # Read one key/line without blocking the signal handler.
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
        elif key == "c":
            _launch_cli()
        elif key == "q":
            break
        else:
            print(_HEADLESS_HELP)


# ── GUI tray (pystray + Pillow) ──────────────────────────────────────────────

def _make_icon_image():
    """CortexAgent tray icon — the square logo asset if present, else a small
    64x64 wolf head drawn with Pillow."""
    from PIL import Image, ImageDraw  # type: ignore
    # Try logo file (jpg or png), then fall back to drawn wolf head
    for ext in ("png", "jpg"):
        logo = Path(__file__).resolve().parent.parent / "assets" / f"cortexagentsquarelogo.{ext}"
        if logo.exists():
            try:
                return Image.open(logo).convert("RGBA").resize((64, 64), Image.LANCZOS)
            except Exception:
                pass  # fall through to the drawn mark
    img = Image.new("RGBA", (64, 64), (15, 17, 21, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=12, fill=(150, 220, 255, 255))
    # crude "CA" — two rounded bars
    d.rectangle([16, 18, 22, 46], fill=(15, 17, 21, 255))
    d.rectangle([16, 18, 30, 24], fill=(15, 17, 21, 255))
    d.rectangle([16, 31, 28, 37], fill=(15, 17, 21, 255))
    d.rectangle([40, 18, 46, 46], fill=(15, 17, 21, 255))
    d.rectangle([40, 18, 54, 24], fill=(15, 17, 21, 255))
    d.rectangle([40, 40, 54, 46], fill=(15, 17, 21, 255))
    return img


def _run_gui(quit_event: threading.Event) -> None:
    import pystray  # type: ignore
    from pystray import MenuItem as MI, Menu  # type: ignore

    def _toast(icon, msg, kind="info"):
        try:
            icon.notify(msg, "CortexAgent")
        except Exception:
            pass
        _log(msg, "ℹ️", CYAN if kind == "info" else (GREEN if kind == "ok" else RED))

    def on_status(icon, item):
        _toast(icon, _status_text().replace("\033[0m", "").replace(RST, ""), "info")

    def on_reload(icon, item):
        _toast(icon, _reload_models(), "ok")

    def on_restart_ov(icon, item):
        _toast(icon, "overseer restart: " + ("ok" if _overseer_restart() else "failed"), "ok")

    def on_reload_cfg(icon, item):
        _toast(icon, _reload_config(), "ok")

    def on_cli(icon, item):
        _launch_cli()

    def on_open_webui(icon, item):
        """Tray click → 8090 webui (the single dashboard, per R5)."""
        import webbrowser
        webbrowser.open("http://127.0.0.1:8090/")
        _log("opened webui: http://127.0.0.1:8090/", "🌐", CYAN)

    def on_quit(icon, item):
        _log("Quit — tearing down overseer", "🛑", YELLOW)
        _overseer_stop()
        icon.stop()
        quit_event.set()

    menu = Menu(
        MI("CortexAgent", None, enabled=False),
        Menu.SEPARATOR,
        MI("Status", on_status),
        MI("Reload models", on_reload),
        MI("Restart overseer", on_restart_ov),
        MI("Reload config", on_reload_cfg),
        Menu.SEPARATOR,
        MI("Launch CLI", on_cli),
        MI("Open webui (8090)", on_open_webui),
        Menu.SEPARATOR,
        MI("Quit", on_quit),
    )
    icon = pystray.Icon("cortexagent", _make_icon_image(),
                        "CortexAgent", menu)
    _log("tray icon running — close it via the menu's Quit to stop the overseer",
         "🟢", GREEN)
    icon.run()


# ── Main ─────────────────────────────────────────────────────────────────────

def _have_pystray() -> bool:
    try:
        import pystray  # noqa: F401
        return True
    except Exception:
        return False


def check() -> int:
    """Report tray dependencies + overseer state, then exit (no run)."""
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
        _overseer_stop()
        quit_event.set()
    return handler


def run(force_headless: bool = False) -> int:
    quit_event = threading.Event()
    signal.signal(signal.SIGINT, _signal_shutdown(quit_event))
    signal.signal(signal.SIGTERM, _signal_shutdown(quit_event))

    # Own the overseer from the start.
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

    # Final cleanup if not already done (e.g. GUI quit path already stopped it).
    if _overseer_pid():
        _overseer_stop()
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