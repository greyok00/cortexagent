#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG
from lib import control
from lib.errorlog import close_dump

STATE_DIR = CFG.state_dir
LOG_FILE = CFG.logs_dir / "daemon.log"
PID_FILE = STATE_DIR / "daemon.pid"
IDLE_POLL = 5

_lock = threading.Lock()
_last_request = 0.0
_status_cache = {"t": 0.0, "payload": None}
_claims: Dict[str, Dict[str, Any]] = {}
_SHUTDOWN = False
_started_at = time.time()

def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or int(pid) <= 1:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OSError):
        return False

def _ppid_of(pid: Optional[int]) -> Optional[int]:
    if not pid:
        return None
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as fh:
            data = fh.read().decode("utf-8", "replace")
        return int(data.rsplit(")", 1)[1].split()[1])
    except Exception:
        return None

def _claim_pids(peer_pid: Optional[int]) -> List[int]:
    pids: List[int] = []
    try:
        peer = int(peer_pid) if peer_pid else 0
    except (TypeError, ValueError):
        peer = 0
    if peer > 1:
        pids.append(peer)
        parent = _ppid_of(peer)
        if parent and parent > 1:
            pids.append(parent)
    return pids

def _prune_claims_locked() -> int:
    for key in [k for k, c in _claims.items()
                if c.get("pids") and not any(_pid_alive(p) for p in c["pids"])]:
        _claims.pop(key, None)
    return len(_claims)

def _live_sessions() -> int:
    with _lock:
        return _prune_claims_locked()

def _scan_active_sessions() -> List[Dict]:

    out: List[Dict] = []
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,etime,comm,args"],
            capture_output=True, text=True, timeout=4
        ).stdout
    except Exception:
        return out
    seen: set = set()

    def _emit(pid_i: int, etime: str, comm: str, args: str, kind: str) -> None:
        if pid_i in seen:
            return
        seen.add(pid_i)
        out.append({"pid": pid_i, "etime": etime, "comm": comm,
                    "kind": kind, "args_excerpt": args[:160]})

    for line in ps.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        pid_s, etime, comm, args = parts
        if not args:
            continue
        try:
            pid_i = int(pid_s)
        except ValueError:
            continue

        for marker, kind in (
            ("/lib/daemon.py",        "daemon"),
            ("/lib/overseer.py",      "overseer"),
        ):
            if marker in args:
                _emit(pid_i, etime, comm, args, kind)
                break
        if len(out) >= 12:
            break
    return out

CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
    "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")

def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{color}{emoji} {BOLD}daemon{RST} {DIM}{color}[{ts}]{RST} {color}{msg}{RST}"
    print(line, file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass

def _free_vram_gb(samples: int = 3, interval: float = 0.7) -> Optional[float]:

    best: Optional[float] = None
    for i in range(max(1, samples)):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                val = float(out.stdout.strip().splitlines()[0].strip()) / 1024.0
                if best is None or val > best:
                    best = val
        except Exception:
            pass
        if i < samples - 1:
            time.sleep(interval)
    return best

def _claim_pruner() -> None:

    while not _SHUTDOWN:
        time.sleep(IDLE_POLL)
        with _lock:
            n = _prune_claims_locked()
        if n:
            _log(f"Pruned {n} dead session claim(s)", "\U0001f9f9", DIM)

def _handle(req: Dict) -> Dict:
    global _last_request, _SHUTDOWN
    cmd = req.get("cmd", "")

    if cmd == "ping":
        return {"ok": True}

    if cmd == "status":
        now = time.time()
        cached = _status_cache["payload"]
        if cached is not None and now - _status_cache["t"] < 1.0:
            return cached

        sessions = _scan_active_sessions()
        primary = sessions[0] if sessions else {}
        payload = {
            "ok": True,
            "active_sessions": _live_sessions(),
            "raw_claims": sorted(_claims.keys()),
            "sessions": sessions,
            "session": primary,
            "last_request": _last_request,
            "idle_sec": int(time.time() - (_last_request or _started_at)),
        }
        _status_cache["t"] = now
        _status_cache["payload"] = payload
        return payload

    if cmd == "activity":

        with _lock:
            _last_request = time.time()
        return {"ok": True}

    if cmd == "session-start":
        pids = _claim_pids(req.get("_peer_pid"))
        anchor = pids[-1] if pids else None
        key = f"pid:{anchor}" if anchor else f"anon:{time.time()}"
        with _lock:
            _claims[key] = {"pids": pids, "ts": time.time()}
            _last_request = time.time()
        return {"ok": True, "active_sessions": _live_sessions()}

    if cmd == "session-end":
        with _lock:
            _prune_claims_locked()
            if _claims:
                oldest = min(_claims.items(), key=lambda kv: kv[1]["ts"])[0]
                _claims.pop(oldest, None)
            _last_request = time.time()
            remaining = len(_claims)
        _log(f"Session end (active={remaining})", "⏹️", DIM)
        return {"ok": True, "active_sessions": remaining}

    if cmd == "session-reset":
        with _lock:
            _claims.clear()
            _last_request = time.time()
        _log("Session reset (stale session detected by overseer watchdog)",
             "🧹", YELLOW)
        return {"ok": True, "active_sessions": 0}

    if cmd == "shutdown":
        _SHUTDOWN = True
        _log("Shutdown requested", "🛑", YELLOW)
        return {"ok": True}

    return {"ok": False, "error": f"unknown cmd: {cmd}"}

def _panel_writer_loop() -> None:
    import os as _os
    import subprocess as _sp
    writers = [
        ("dispatcher", ["python3", os.path.expanduser("~/dispatcher/server.py"),
                        "--write-status"]),
        ("secops", ["python3", os.path.expanduser("~/security-hardening/secops-mcp.py"),
                    "--write-status"]),
        ("messenger", ["python3", os.path.expanduser("~/messenger/bin/messenger-server"),
                       "--write-status"]),
    ]
    env = dict(_os.environ,
               CORTEXAGENT_STATUS_DIR=str(STATE_DIR / "panel-status"))
    while not _SHUTDOWN:
        for name, cmd in writers:
            try:
                _sp.run(cmd, env=env, capture_output=True, timeout=60)
            except Exception as exc:
                _log(f"panel writer {name}: {exc}", "⚠️", YELLOW)
        for _ in range(60):
            if _SHUTDOWN:
                return
            time.sleep(1)

def _run() -> None:

    signal.signal(signal.SIGTERM, lambda *_: _request_shutdown())
    signal.signal(signal.SIGINT, lambda *_: _request_shutdown())

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (CFG.logs_dir).mkdir(parents=True, exist_ok=True)
    _log("CortexAgent daemon starting (control + session tracking; "
         "lanes :11435/:11436 → :11600 live outside the daemon)", "🚀", CYAN)

    threading.Thread(target=_claim_pruner, daemon=True).start()
    threading.Thread(target=control.serve, args=(_handle,), daemon=True).start()
    threading.Thread(target=_panel_writer_loop, daemon=True).start()

    _log("Daemon ready — control socket listening", "✅", GREEN)
    while not _SHUTDOWN:
        time.sleep(1)

    _log("Daemon shutting down", "🛑", YELLOW)
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        os.unlink(control._socket_path())
    except Exception:
        pass

    close_dump(component="daemon", reason="SIGINT/SIGTERM clean shutdown", log_file=LOG_FILE)
    _log("Daemon stopped cleanly (exit 0)", "✅", GREEN)

def _request_shutdown() -> None:
    global _SHUTDOWN
    _SHUTDOWN = True

def _is_running() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return None

def _start_bg() -> int:

    pid = _is_running()
    if pid:
        print(f"Daemon already running (pid {pid})")
        return 0
    pid = os.fork()
    if pid > 0:
        PID_FILE.write_text(str(pid))
        print(f"Daemon started (pid {pid})")
        return 0
    os.setsid()
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 0)
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)
    _run()
    return 0

def _stop() -> int:
    pid = _is_running()
    if not pid:

        try:
            r = control.send_request("shutdown", timeout=5)
            print("Daemon shutdown via socket:", r)
            return 0
        except Exception:
            print("Daemon not running")
            return 0
    try:
        control.send_request("shutdown", timeout=5)
    except Exception:
        os.kill(pid, signal.SIGTERM)

    for _ in range(150):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            break
    PID_FILE.unlink(missing_ok=True)
    print("Daemon stopped")
    return 0

def _status() -> int:
    try:
        s = control.send_request("status", timeout=5)
    except Exception as e:
        print(f"Daemon not reachable: {e}")
        return 1
    if not s.get("ok"):
        print("status error:", s)
        return 1
    print("CortexAgent daemon: 🟢 running")
    print("  lanes : slimtoken :11435/:11436 → ollama :11600")
    print(f"  sessions: {s['active_sessions']}  idle: {s['idle_sec']}s")
    return 0

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "run":
        existing = _is_running()
        if existing:
            print(f"Daemon already running (pid {existing}) — this instance will exit.", flush=True)
            return 0
        PID_FILE.write_text(str(os.getpid()))
        try:
            _run()
        finally:
            PID_FILE.unlink(missing_ok=True)
        return 0
    if cmd == "start":
        return _start_bg()
    if cmd == "stop":
        return _stop()
    if cmd == "status":
        return _status()
    print(f"unknown command: {cmd}\n", file=sys.stderr)
    print(__doc__)
    return 1

if __name__ == "__main__":
    sys.exit(main())
