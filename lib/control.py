#!/usr/bin/env python3

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


TCP_FALLBACK_HOST = "127.0.0.1"
TCP_FALLBACK_PORT = int(os.environ.get("CORTEXAGENT_CONTROL_PORT", "0"))


def _is_unix() -> bool:
    return hasattr(socket, "AF_UNIX") and TCP_FALLBACK_PORT <= 0


def _socket_path() -> str:
    return os.environ.get("CORTEXAGENT_CONTROL_SOCK", SOCK_PATH)


def daemon_present(timeout: float = PING_TIMEOUT) -> bool:

    try:
        return bool(send_request("ping", timeout=timeout).get("ok"))
    except Exception:
        return False


def send_request(cmd: str, timeout: float = DEFAULT_TIMEOUT, **params) -> Dict:

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
    try:
        return json.loads(buf.decode().strip().splitlines()[0])
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"control: malformed JSON from daemon: {e}") from e


def serve(handler: Callable[[Dict], Dict],
          sock_path: Optional[str] = None) -> None:

    if _is_unix():
        path = sock_path or _socket_path()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
    else:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((TCP_FALLBACK_HOST, TCP_FALLBACK_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()


        threading.Thread(target=_serve_one, args=(conn, handler), daemon=True).start()


def _serve_one(conn, handler):



    conn.settimeout(30)
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

    print("daemon present:", daemon_present())