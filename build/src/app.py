from __future__ import annotations

def erase() -> str:
    return "\x1b[2K"

import os
import select
import shutil
import sys
import termios
import threading
import time
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import llm as llm_mod
from core.loop import run, compression_stats
from core.wiring import register_all
from model.server import is_ready, tokens_per_second
from ui.splash import compact_splash_lines, shade, splash_lines

RESET = "\033[0m"
SHOW = "\033[?25h"

_print_lock = threading.RLock()
_state = {"buffer": "", "cols": 80, "rows": 24, "status": "idle",
          "spin": 0, "ticker_row": None}
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def erase() -> str:
    return "\x1b[2K"


def ticker_text() -> str:
    comp = compression_stats()
    comp_box = ("comp in=%d kept=%d r=%.2f" % (
        comp.get("last_in") or comp["tokens_in"],
        comp.get("last_kept") or comp["tokens_kept"],
        comp["ratio"])) if comp["tokens_in"] else "comp lossless"
    try:
        from services.memory_thin import check_sessions, HOT_FILE
        count = 0
        try:
            with open(HOT_FILE, "r") as fh:
                count = sum(1 for _ in fh)
        except Exception:
            count = 0
        daemon = daemon_ok()
        mem_box = "mem %s e=%d" % ("up" if daemon else "direct", count)
    except Exception:
        mem_box = "mem n/a"
    model_box = "model %s" % _state["status"]
    if is_ready():
        tps = llm_mod.LAST_TPS
        if tps <= 0.1:
            tps = tokens_per_second()
        model_box += " %.1f t/s" % tps
    spin = SPIN[_state["spin"] % len(SPIN)]
    _state["spin"] = (_state["spin"] + 1) % len(SPIN)
    return "  ".join([model_box, "│", comp_box, "│", spin, "", mem_box])


def daemon_ok() -> bool:
    import socket as _socket
    sock = ROOT / "state" / "memory.sock"
    if not sock.exists():
        return False
    try:
        c = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        c.settimeout(0.5)
        c.connect(str(sock))
        c.close()
        return True
    except Exception:
        return False


def log_write(text: str) -> None:
    with _print_lock:
        cols = _state["cols"]
        sys.stdout.write("\r\n")
        i = 0
        while i < len(text):
            sys.stdout.write(text[i:i + cols] + erase() + "\r\n")
            i += cols
        if not text:
            sys.stdout.write(erase() + "\r\n")
        ticker_write()
        sys.stdout.flush()


def ticker_write() -> None:
    text = ticker_text()
    line = text[:_state["cols"] - 1]
    sys.stdout.write("\x1b[2A\x1b[2K" + line + "\r\n\x1b[2K╰─ " + shade(7) +
                     _state["buffer"] + RESET)
    col = min(len(_state["buffer"]) + 4, _state["cols"] - 1)
    sys.stdout.write("\x1b[%d;%dH" % (_state["rows"], col))


def _ticker_loop() -> None:
    while True:
        ticker_write()
        time.sleep(0.8)


def submit(text: str) -> None:
    log_write("> " + text)
    if text.strip() == "/tools":
        from core.registry import list_tools
        log_write(", ".join(t["name"] for t in list_tools(stub=False)))
        return

    def run_turn() -> None:
        _state["status"] = "loading"
        register_all()
        if not is_ready():
            _state["status"] = "idle"
            log_write("model unavailable — start the model server first")
            return
        r = run({"prompt": text},
                on_event=lambda ev: log_write("  [tool] %s" % ev.get("name", "")))
        _state["status"] = "up"
        log_write(str(r.get("output") or r.get("error", ""))[:4000])

    threading.Thread(target=run_turn, daemon=True).start()


def ctrl_quit(*_a) -> None:
    pass


def main() -> None:
    if not sys.stdin.isatty():
        print("cortexagent needs a terminal")
        return
    size = shutil.get_terminal_size((80, 24))
    _state["cols"], _state["rows"] = size.columns, size.lines
    import signal
    old_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, ctrl_quit)
    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~termios.ICRNL
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        sys.stdout.write("\033[?25l")
        cols = _state["cols"]
        lines = splash_lines() if cols >= 90 else compact_splash_lines()
        for line in lines:
            sys.stdout.write(line[:cols + 12] + erase() + "\r\n")
        threading.Thread(target=_ticker_loop, daemon=True).start()
        buf = ""
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.3)
            if not r:
                continue
            ch = os.read(fd, 1).decode("utf-8", errors="ignore")
            if ch == "\x03":
                break
            elif ch == "\x0d" or ch == "\x0a":
                if buf.strip():
                    submit(buf.strip())
                buf = ""
                _state["buffer"] = buf
                ticker_write()
            elif ch == "\x7f":
                buf = buf[:-1]
                _state["buffer"] = buf
                ticker_write()
            elif ch == "\x0e":
                log_write("new session")
            elif ch == "\x12":
                from core import wiring
                wiring._state["done"] = False
                n = wiring.register_all()
                log_write("tools reloaded: %d" % n)
            elif ch == "\x06":
                from services.memory_thin import read_last
                for entry in read_last(5):
                    log_write("mem: " + str(entry.get("content", ""))[:100])
            elif ch == "\x0b":
                from services.scheduler_store import Store
                for t in Store().list()[:5]:
                    log_write("sched: " + str(t)[:100])
            elif ch >= " ":
                buf += ch
                _state["buffer"] = buf
                ticker_write()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
        signal.signal(signal.SIGINT, old_int)
        sys.stdout.write(SHOW)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
