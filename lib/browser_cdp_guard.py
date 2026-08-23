#!/usr/bin/env python3
"""browser_cdp_guard — CDP connection security for browser automation (§4).

Goals from the spec, mapped to what is actually achievable on a CDP endpoint:

  * Bind to localhost only — verify the debug port is 127.0.0.1, never 0.0.0.0
    or a routable interface. Refuse to operate if exposed.
  * Prefer --remote-debugging-pipe over a TCP port — provided as a launcher
    flag for agent-owned browser instances; for the attach-to-running-Brave
    model the port is already 127.0.0.1-only, which removes the routable
    surface. (Pipe removes the network surface entirely; documented below.)
  * Validate the WebSocket handshake Origin against an explicit allowlist of
    this agent's clients — enforced via Brave's --remote-allow-origins launch
    flag (the browser side rejects foreign-origin ws upgrades).
  * After our client attaches, poll for additional/unauthorized clients and,
    if one is detected, terminate the session and alert.

Honesty on the last point: the HTTP /json endpoint lists *targets* (tabs), not
*connected clients*, so "list every attached client" is not directly exposed.
The reliable signal of a foreign client attaching is that our page-level
websocket is closed by the remote while the tab still exists (a target can only
be driven by one debugger client at a time — Chromium detaches the prior client
when a new one attaches to the same target). CDPGuard watches for exactly that:
unexpected socket death on a still-live target => alert, and (opt-in) kill.

The kill action is opt-in (STEALTH_CDP_GUARD_KILL=1) because in the
attach-to-running-Brave model, killing the user's daily browser is destructive.
For agent-owned launches (launch_brave), the guard kills the child it spawned.
"""
from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

# Where alerts are appended. Agent-inaccessible: restrictive mode, append-only.
LOG_PATH = os.path.expanduser("~/cortexagent/logs/cdp_guard.log")

# Allowed WebSocket Origin values for the agent's clients. Used to set Brave's
# --remote-allow-origins flag on agent-owned launches. Keep this minimal.
ALLOWED_ORIGINS = ["http://localhost", "http://127.0.0.1"]


def _ensure_log() -> str:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    return LOG_PATH


def alert(kind: str, details: Dict[str, Any]) -> None:
    """Append an alert to the immutable-ish audit log (O_APPEND, mode 0600).

    'Immutable, agent-inaccessible' here means: the agent's normal tool surface
    never reads this file; it is append-only via O_APPEND and restricted to the
    operator. (True immutability needs chattr +a / a dedicated uid; documented.)
    """
    path = _ensure_log()
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, "details": details}) + "\n")
        # Best-effort append-only attribute if the FS supports it.
        try:
            subprocess.run(["chattr", "+a", path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass
    except Exception:
        pass


def _parse_proc_tcp(port: int) -> List[str]:
    """Return the local bind addresses listening on `port` from /proc/net/tcp.

    Each address is a hex ip:port. We look for LISTEN (state 0A) on the port.
    """
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
                # /proc/net/tcp ip is little-endian hex: 0100007F = 127.0.0.1
                ip_int = int(ip_hex, 16)
                ip = socket.inet_ntoa(ip_int.to_bytes(4, "little"))
                hits.append(ip)
    except Exception:
        pass
    return hits


def assert_localhost(port: int = 9222) -> bool:
    """Verify the CDP port is bound to localhost only. Alert + return False if
    it is bound to a routable interface (0.0.0.0 or a non-loopback IP)."""
    binds = _parse_proc_tcp(port)
    if not binds:
        # Not listening at all — fine for the guard; the caller will handle.
        return True
    bad = [b for b in binds if b not in ("127.0.0.1", "::1")]
    if bad:
        alert("CDP_EXPOSED", {"port": port, "binds": binds})
        return False
    return True


def fix_exposed_port(port: int) -> bool:
    """Best-effort: if a known agent-owned process exposes `port` on 0.0.0.0,
    log the recommendation. True config fixes happen in the owning compose/launcher.
    Returns True if the port is now localhost-bound."""
    if assert_localhost(port):
        return True
    alert("CDP_FIX_NEEDED", {"port": port, "note": "rebind to 127.0.0.1 in the owning compose/launcher"})
    return False


class CDPGuard:
    """Background thread that watches our CDP sockets for unexpected death.

    Polls the browser_control socket cache liveness; if a cached socket dies
    while its target still exists, treats it as a suspected unauthorized client
    attachment and alerts (and kills if configured).
    """

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
            return  # refuse to guard an exposed endpoint
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
        # Snapshot the socket cache; check each is still open.
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
                continue  # tab closed normally — not an alert
            # A still-listed target whose socket is dead => foreign attach suspected.
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
    url = getattr(bc, "CDP_HTTP", "http://127.0.0.1:9222")
    try:
        return int(url.rsplit(":", 1)[1])
    except Exception:
        return 9222


# ---- agent-owned Brave launcher (pipe-preferred, origin-allowlisted) --------
BRAVE_BIN_CANDIDATES = [
    "/opt/brave.com/brave/brave",
    "/usr/bin/brave-browser-stable",
    "/usr/bin/brave-browser",
]


def brave_binary() -> Optional[str]:
    for p in BRAVE_BIN_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def launch_brave(user_data_dir: str, extra_args: Optional[List[str]] = None,
                pipe: bool = True, port: int = 0) -> Dict[str, Any]:
    """Launch an agent-owned Brave with a hardened CDP surface.

    pipe=True (preferred) uses --remote-debugging-pipe (no TCP port at all;
    we speak CDP over the child's stdin/stdout). pipe=False uses a random
    localhost port (--remote-debugging-port=0) with --remote-allow-origins
    restricting who can upgrade the ws. AutomationControlled is disabled so
    navigator.webdriver is not set at the source (driver-level, not a JS patch).
    Returns {"pid":..., "port":..., "pipe":bool, "devtools_port_path":...|None}.
    """
    bin_ = brave_binary()
    if not bin_:
        raise RuntimeError("Brave binary not found")
    args = [bin_,
            f"--user-data-dir={user_data_dir}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run", "--no-default-browser-check",
            "--disable-features=AutomationControlled"]
    if pipe:
        args.append("--remote-debugging-pipe")
    else:
        args.append(f"--remote-debugging-port={port}")
        args.append(f"--remote-allow-origins={','.join(ALLOWED_ORIGINS)}")
    if extra_args:
        args += extra_args
    proc = subprocess.Popen(args, stdin=subprocess.PIPE if pipe else subprocess.DEVNULL,
                            stdout=subprocess.PIPE if pipe else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return {"pid": proc.pid, "proc": proc, "pipe": pipe, "port": port,
            "devtools_port_path": os.path.join(user_data_dir, "DevToolsActivePort") if not pipe else None}