#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional


LOG_PATH = os.path.expanduser("~/cortexagent/logs/cdp_guard.log")



ALLOWED_ORIGINS = ["http://localhost", "http://127.0.0.1"]


def _ensure_log() -> str:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    return LOG_PATH


def alert(kind: str, details: Dict[str, Any]) -> None:

    path = _ensure_log()
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, "details": details}) + "\n")

        try:
            subprocess.run(["chattr", "+a", path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass
    except Exception:
        pass


def _parse_proc_tcp(port: int) -> List[str]:

    hits = []
    try:
        with open("/proc/net/tcp") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split()
                local = parts[1]
                state = parts[3]
                if state != "0A":
                    continue
                ip_hex, port_hex = local.split(":")
                if int(port_hex, 16) != port:
                    continue

                ip_int = int(ip_hex, 16)
                ip = socket.inet_ntoa(ip_int.to_bytes(4, "little"))
                hits.append(ip)
    except Exception:
        pass
    return hits


def assert_localhost(port: int = 9223) -> bool:

    binds = _parse_proc_tcp(port)
    if not binds:

        return True
    bad = [b for b in binds if b not in ("127.0.0.1", "::1")]
    if bad:
        alert("CDP_EXPOSED", {"port": port, "binds": binds})
        return False
    return True




class CDPGuard:


    def __init__(self, bc: Any, interval: float = 2.0, kill: Optional[bool] = None,
                 owned_pids: Optional[List[int]] = None) -> None:
        self.bc = bc
        self.interval = interval
        self.kill = (os.environ.get("STEALTH_CDP_GUARD_KILL", "0") in ("1", "true")) if kill is None else kill
        self.owned_pids = owned_pids or []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not assert_localhost(_port_of(self.bc)):
            alert("GUARD_REFUSED_EXPOSED", {"port": _port_of(self.bc)})
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="cdp-guard")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:
                alert("GUARD_ERROR", {"err": str(e)[:200]})
            self._stop.wait(self.interval)

    def _poll_once(self) -> None:
        import urllib.request

        cache = dict(getattr(self.bc, "_ws_cache", {}))
        if not cache:
            return
        try:
            with urllib.request.urlopen(self.bc.CDP_HTTP + "/json", timeout=2) as r:
                tabs = json.load(r)
        except Exception:
            return
        live_ids = {t.get("id") for t in tabs if t.get("type") == "page"}
        for target_id, ws in cache.items():
            if target_id not in live_ids:
                continue

            sock = getattr(ws, "sock", None)
            closed = False
            try:
                if sock is not None:
                    closed = (sock.fileno() == -1) or bool(getattr(sock, "_closed", False))
                else:
                    closed = bool(getattr(ws, "_closed", False))
            except Exception:
                closed = True
            if closed:
                alert("UNAUTHORIZED_CLIENT_SUSPECTED", {
                    "target_id": target_id, "url": next((t.get("url") for t in tabs if t.get("id") == target_id), "")})
                if self.kill:
                    self._kill_session()

    def _kill_session(self) -> None:
        for pid in self.owned_pids:
            try:
                os.kill(pid, 15)
            except Exception:
                pass
        try:
            self.bc.close()
        except Exception:
            pass


def _port_of(bc: Any) -> int:
    url = getattr(bc, "CDP_HTTP", "http://127.0.0.1:9224")
    try:
        return int(url.rsplit(":", 1)[1])
    except Exception:
        return 9224







