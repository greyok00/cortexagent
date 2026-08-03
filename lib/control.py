#!/usr/bin/env python3
"""lib/control.py — AF_UNIX control socket for the cortexagent daemon.

Protocol: one JSON request per line → one JSON response per line.

  Request:  {"cmd": "status", ...optional params}
  Response: {"ok": true, ...}   |   {"ok": false, "error": "..."}

Clients (one short-lived connection per command):
  - lib/grammar_proxy.py  → "load big" when :8080 is down (reload-on-request)
  - bin/cortexagent + engine/cli.py → "session-start" / "session-end" / "models"
  - lib/overseer.py → "ping" to detect daemon mode (don't stop the tiny if up)

Server: lib/daemon.py runs `serve(handler)` in a thread.

The socket path is config-driven (``CFG.control_socket`` →
``~/.cortexagent/control.sock``). Falls back to TCP on platforms without
AF_UNIX (older Windows) — see ``TCP_FALLBACK_HOST`` / env
``CORTEXAGENT_CONTROL_PORT``.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402

SOCK_PATH = str(CFG.control_socket)
PING_TIMEOUT = 2.0
DEFAULT_TIMEOUT = 15.0

# TCP fallback (platforms without AF_UNIX). Disabled unless a port is given.
TCP_FALLBACK_HOST = "127.0.0.1"
TCP_FALLBACK_PORT = int(os.environ.get("CORTEXAGENT_CONTROL_PORT", "0"))


def _is_unix() -> bool:
    return hasattr(socket, "AF_UNIX") and TCP_FALLBACK_PORT <= 0


def _socket_path() -> str:
    return os.environ.get("CORTEXAGENT_CONTROL_SOCK", SOCK_PATH)


def daemon_present(timeout: float = PING_TIMEOUT) -> bool:
    """True iff the daemon control socket is up and answers ``ping``."""
    try:
        return bool(send_request("ping", timeout=timeout).get("ok"))
    except Exception:
        return False


def send_request(cmd: str, timeout: float = DEFAULT_TIMEOUT, **params) -> Dict:
    """Send one command to the daemon and return the response dict.

    Raises if the socket is missing or the daemon doesn't answer.
    """
    if _is_unix():
        path = _socket_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"control socket not found: {path}")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(path)
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((TCP_FALLBACK_HOST, TCP_FALLBACK_PORT))

    try:
        s.sendall((json.dumps({"cmd": cmd, **params}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    if not buf:
        raise RuntimeError("empty response from daemon")
    return json.loads(buf.decode().strip().splitlines()[0])


def serve(handler: Callable[[Dict], Dict],
          sock_path: Optional[str] = None) -> None:
    """Listen on the control socket; dispatch each request to ``handler``.

    Blocks forever. One request per connection (simple + robust — clients open a
    fresh connection per command). Removes a stale socket file first.
    """
    if _is_unix():
        path = sock_path or _socket_path()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)  # only the owner may drive the daemon
    else:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((TCP_FALLBACK_HOST, TCP_FALLBACK_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        # Thread per connection: a long-running "load big" must not block
        # concurrent "activity" / "status" / "ping" commands from the proxy.
        threading.Thread(target=_serve_one, args=(conn, handler), daemon=True).start()


def _serve_one(conn, handler):
    try:
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        req = json.loads(data.decode().strip().splitlines()[0]) if data.strip() else {}
        resp = handler(req)
    except Exception as e:
        resp = {"ok": False, "error": str(e)}
    try:
        conn.sendall((json.dumps(resp) + "\n").encode())
    except Exception:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    # Quick probe: python3 lib/control.py → is the daemon up?
    print("daemon present:", daemon_present())