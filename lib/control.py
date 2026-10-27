#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG

SOCK_PATH = str(CFG.control_socket)
PING_TIMEOUT = 2.0
DEFAULT_TIMEOUT = 15.0

TCP_FALLBACK_HOST = "127.0.0.1"
TCP_FALLBACK_PORT = int(os.environ.get("CORTEXAGENT_CONTROL_PORT", "0"))

# Control-plane hardening (isolation audit 2026-10-27):
# - inbound requests are size-capped and deadline-bounded, never read unbounded
# - worker concurrency is bounded; excess connections are shed with "control busy"
# - TCP mode is opt-in and requires a bearer token; the unix socket (mode 0600,
#   same-uid by construction) stays the default and needs no token
# - transports that cannot establish caller identity (TCP) may not run
#   identity-sensitive commands (shutdown, session-reset)
MAX_REQUEST_BYTES = 1 << 20          # inbound request cap
MAX_RESPONSE_BYTES = 8 << 20         # client-side response cap
REQUEST_DEADLINE = 30.0              # overall seconds to receive one request
MAX_CONCURRENT_CONNECTIONS = 16
SENSITIVE_CMDS = frozenset(("shutdown", "session-reset"))
TOKEN_ENV = "CORTEXAGENT_CONTROL_TOKEN"
_WORKER_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_CONNECTIONS)

def _is_unix() -> bool:
    return hasattr(socket, "AF_UNIX") and TCP_FALLBACK_PORT <= 0

def _socket_path() -> str:
    return os.environ.get("CORTEXAGENT_CONTROL_SOCK", SOCK_PATH)

def _tcp_token(persist: bool = False) -> str:
    """Bearer token shared by a TCP-control daemon and its local clients.

    Resolution order: TOKEN_ENV, else the generated token file under the
    state dir. Only the server (persist=True) ever generates or writes the
    token; clients read it so both sides always agree.
    """
    tok = os.environ.get(TOKEN_ENV, "").strip()
    if tok:
        return tok
    tok_file = Path(CFG.state_dir) / "control-token"
    tok = ""
    try:
        tok = tok_file.read_text().strip()
    except OSError:
        pass
    if tok or not persist:
        return tok
    import secrets
    tok = secrets.token_hex(32)
    try:
        Path(CFG.state_dir).mkdir(parents=True, exist_ok=True)
        tok_file.write_text(tok)
        os.chmod(tok_file, 0o600)
    except OSError:
        return ""
    return tok

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
        params.setdefault("token", _tcp_token())

    try:
        s.sendall((json.dumps({"cmd": cmd, **params}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_RESPONSE_BYTES:
                raise RuntimeError("control response too large")
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
        # fail closed: TCP mode must establish a token before serving anything
        if not _tcp_token(persist=True):
            raise RuntimeError("TCP control mode requires a control token "
                               f"({TOKEN_ENV} or a writable state dir)")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((TCP_FALLBACK_HOST, TCP_FALLBACK_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        if not _WORKER_SLOTS.acquire(blocking=False):
            # workers are busy: shed the connection instead of queueing it
            try:
                conn.sendall(b'{"ok": false, "error": "control busy"}\n')
            except OSError:
                pass
            finally:
                conn.close()
            continue
        try:
            threading.Thread(target=_serve_one, args=(conn, handler), daemon=True).start()
        except Exception:
            # worker never started: hand the slot back instead of leaking it
            _WORKER_SLOTS.release()
            try:
                conn.close()
            except OSError:
                pass

def _peer_pid(conn) -> Optional[int]:
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                              struct.calcsize("3i"))
        pid, _uid, _gid = struct.unpack("3i", raw)
        return pid or None
    except (AttributeError, OSError, struct.error):
        return None

def _serve_one(conn, handler):

    is_tcp = not _is_unix()
    deadline = time.monotonic() + REQUEST_DEADLINE
    try:
        buf = bytearray()
        overflow = False
        while b"\n" not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("request deadline exceeded")
            conn.settimeout(min(REQUEST_DEADLINE, remaining))
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_REQUEST_BYTES:
                overflow = True
                break
        if overflow:
            raise ValueError(f"request exceeds {MAX_REQUEST_BYTES} bytes")
        data = bytes(buf)
        req: Dict = {}
        if data.strip():
            req = json.loads(data.decode().strip().splitlines()[0])
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
        if is_tcp:
            expected = _tcp_token()
            got = req.pop("token", None)   # never let the token reach the handler
            if not expected or got != expected:
                raise PermissionError("unauthorized: TCP control requires the control token")
            if req.get("cmd", "") in SENSITIVE_CMDS:
                raise PermissionError("refused over TCP: use the unix control socket for this command")
        req["_peer_pid"] = _peer_pid(conn)
        resp = handler(req)
    except Exception as e:
        resp = {"ok": False, "error": str(e)}
    try:
        conn.sendall((json.dumps(resp) + "\n").encode())
    except Exception:
        pass
    finally:
        conn.close()
        _WORKER_SLOTS.release()

if __name__ == "__main__":

    print("daemon present:", daemon_present())