#!/usr/bin/env python3
"""cortexagent status ticker — live bottom-line that updates every second.

Different from statusline.py: that one renders ONCE per Claude Code
statusLine hook call (once per prompt submit). This ticker runs as a
background thread inside the CLI session and overwrites the same line
in place every second, so the user always sees fresh data.

Output: single line, ANSI cursor-up + erase-line before each render so
the bar sits at the bottom of the terminal and never scrolls.

Reads:
  - daemon control socket (status command) — model, VRAM, sessions
  - grammar proxy /metrics                 — token rate, minify savings
  - ~/.cortexagent/minify_stats.json       — savings snapshot (fallback)

Fails soft: any error returns "" so the ticker line never blows up.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from lib.config import CFG  # author tag is configurable (CORTEXAGENT_AUTHOR)
except Exception:
    CFG = None


# ── Daemon control socket (status snapshot, low latency) ─────────────────────

def _daemon_status(timeout: float = 0.4) -> dict[str, Any]:
    sock = Path.home() / ".cortexagent" / "control.sock"
    if not sock.exists():
        return {}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(str(sock))
        s.sendall(b'{"cmd":"status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        if not buf:
            return {}
        return json.loads(buf.decode("utf-8", "replace").strip() or "{}")
    except Exception:
        return {}


def _proxy_metrics(timeout: float = 0.4) -> dict[str, Any]:
    port = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/metrics", method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def _minify_snapshot() -> dict[str, Any]:
    try:
        p = Path.home() / ".cortexagent" / "minify_stats.json"
        if not p.exists():
            return {}
        d = json.loads(p.read_text() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ── Formatting helpers ──────────────────────────────────────────────────────

def _ctx_str(daemon: dict[str, Any]) -> str:
    cw = daemon.get("context_window") or {}
    if isinstance(cw, dict):
        used = cw.get("used") or cw.get("used_tokens") or cw.get("current")
        total = cw.get("total") or cw.get("limit") or cw.get("max")
        if used and total:
            return f"{used}/{total} tok"
    return ""


def _tok_metrics(proxy: dict[str, Any]) -> str:
    if not proxy:
        return ""
    in_tps = proxy.get("current_in_tps") or 0
    out_tps = proxy.get("current_out_tps") or proxy.get("current_tok_s") or 0
    reqs = proxy.get("requests", 0)
    parts: list[str] = []
    if in_tps and out_tps:
        parts.append(f"in {in_tps:.0f} t/s · out {out_tps:.0f} t/s")
    elif out_tps:
        parts.append(f"{out_tps:.0f} t/s")
    elif in_tps:
        parts.append(f"in {in_tps:.0f} t/s")
    if reqs:
        parts.append(f"{reqs} req")
    return " · ".join(parts)


def _vram_str(daemon: dict[str, Any]) -> str:
    vbp = daemon.get("vram_by_proc") or {}
    if not vbp.get("ok"):
        return ""
    big = int(vbp.get("big_mib", 0) or 0)
    tiny = int(vbp.get("tiny_mib", 0) or 0)
    other = int(vbp.get("other_mib", 0) or 0)
    used = big + tiny + other
    if used <= 0:
        return ""
    parts: list[str] = []
    if big:
        parts.append(f"big {big/1024:.1f} GB")
    if tiny:
        parts.append(f"tiny {tiny/1024:.1f} GB")
    if not parts:
        return f"{used/1024:.1f} GB"
    return " + ".join(parts) + f" / {used/1024:.1f} GB"


def _minify_str(minify: dict[str, Any]) -> str:
    try:
        runs = int(minify.get("runs", 0) or 0)
        if runs <= 0:
            return ""
        ratio = float(minify.get("ratio_pct", 0.0) or 0.0)
        saved = int(minify.get("tokens_saved", 0) or 0)
        if saved <= 0 or ratio <= 0:
            return ""
        shown = (f"{saved // 1000}k" if saved >= 1000 else f"{saved}")
        return f"minify -{ratio:.0f}% ({shown})"
    except Exception:
        return ""


def render_line() -> str:
    """Compose the live status line. Pulls from daemon, proxy, snapshot."""
    daemon = _daemon_status()
    proxy = _proxy_metrics()
    minify = _minify_snapshot()

    brand = (str(CFG.author) if CFG else "CortexAgent") or "CortexAgent"
    model = ""
    m = daemon.get("model")
    if isinstance(m, dict):
        model = m.get("display_name") or m.get("id") or ""
    elif isinstance(m, str):
        model = m
    elif proxy.get("model_alias"):
        model = proxy.get("model_alias")

    cwd = daemon.get("cwd") or ""
    if cwd:
        home = os.path.expanduser("~")
        if cwd == home:
            cwd = "~"
        elif cwd.startswith(home + os.sep):
            cwd = "~" + cwd[len(home):]

    parts: list[str] = [brand]
    if model and model.strip().lower() != brand.strip().lower():
        parts.append(model)
    if cwd:
        parts.append(cwd)
    ctx = _ctx_str(daemon)
    if ctx:
        parts.append(ctx)
    tok = _tok_metrics(proxy)
    if tok:
        parts.append(tok)
    vram = _vram_str(daemon)
    if vram:
        parts.append(vram)
    mf = _minify_str(minify)
    if mf:
        parts.append(mf)
    return " · ".join(str(p) for p in parts if p)


# ── Background ticker ───────────────────────────────────────────────────────

class StatusTicker:
    """Background thread that overwrites a single status line every interval.

    Usage:
        t = StatusTicker(interval=1.0)
        t.start()
        ... do work ...
        t.stop()

    The ticker prints `\x1b[1A\x1b[2K<line>` so the previous line is cleared
    before the new one is written — keeping the bar pinned to the bottom of
    the terminal without scrolling. When stdout is not a TTY, the line is
    printed fresh each tick instead.
    """

    def __init__(self, interval: float = 1.0, stream=None) -> None:
        self.interval = interval
        self.stream = stream or sys.stderr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_tty = hasattr(self.stream, "isatty") and self.stream.isatty()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="cortexagent-status-ticker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _emit(self, line: str) -> None:
        if self._is_tty:
            # Cursor-up + erase-line + newline + new content. ANSI sequences
            # stripped to the simplest reliable subset.
            self.stream.write(f"\x1b[1A\x1b[2K{line}\n")
            self.stream.flush()
        else:
            self.stream.write(f"{line}\n")
            self.stream.flush()

    def _run(self) -> None:
        # Prime: print a blank line first so the cursor-up sequence has a
        # line above to clear on subsequent ticks.
        try:
            self.stream.write("\n")
            self.stream.flush()
        except Exception:
            return
        last_emit = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_emit >= self.interval:
                try:
                    line = render_line()
                    if line:
                        self._emit(line)
                except Exception:
                    pass
                last_emit = now
            # Sleep in short slices so stop() is responsive.
            self._stop.wait(0.1)


# ── Smoke-test entry point ──────────────────────────────────────────────────

def _smoke() -> int:
    """Run a single render to stdout and exit 0. Used by the smoke gate."""
    try:
        line = render_line()
        print(line or "CortexAgent")
        return 0
    except Exception as e:
        print(f"ticker smoke FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        sys.exit(_smoke())
    # Default: run the ticker for ~5s then exit (handy for manual testing).
    t = StatusTicker(interval=1.0)
    t.start()
    try:
        time.sleep(5.5)
    finally:
        t.stop()