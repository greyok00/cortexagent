#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402
from lib.model_backend import LlamaServer  # noqa: E402
from lib import control  # noqa: E402
from lib.errorlog import log_exception, close_dump  # noqa: E402


STATE_DIR = CFG.state_dir
LOG_FILE = CFG.logs_dir / "daemon.log"
PID_FILE = STATE_DIR / "daemon.pid"
IDLE_POLL = 5

_lock = threading.Lock()
_big_lock = threading.Lock()
_last_request = 0.0
_active_sessions = 0
_SHUTDOWN = False
_proxy_proc: Optional[subprocess.Popen] = None
_tiny_was_healthy = True
_tiny_down_since: float = 0.0
TINY_DEATH_GRACE_SEC = 3.0


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

        if comm == "llama-server":
            if "--port 8080" in args or "--port=8080" in args:
                _emit(pid_i, etime, comm, args, "big")
                continue
            if "--port 8082" in args or "--port=8082" in args:
                _emit(pid_i, etime, comm, args, "tiny")
                continue

        for marker, kind in (
            ("/lib/daemon.py",        "daemon"),
            ("/lib/overseer.py",      "overseer"),
            ("/lib/grammar_proxy.py", "proxy"),
            ("/lib/diffusion_backend.py", "diffusion"),
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



def _big_extra_args() -> list:
    args = [
        "-fa", str(CFG.big_fa),
        "-ctk", str(CFG.big_ctk),
        "-ctv", str(CFG.big_ctv),
        "-np", str(CFG.big_np),
        "-b", str(CFG.big_b),
        "-ub", str(CFG.big_ub),
        "--kv-unified",
    ]
    if int(CFG.big_kv_offload) == 0:
        args.append("--no-kv-offload")
    return args


def _vram_by_process() -> Dict[str, Any]:

    out: Dict[str, Any] = {
        "big_mib": 0,
        "tiny_mib": 0,
        "other_mib": 0,
        "by_pid": [],
        "ok": False,
    }
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return out
    if proc.returncode != 0:
        return out



    big_pid: Optional[int] = None
    tiny_pid: Optional[int] = None
    try:
        for port_attr, target in (("_big.port", "big"), ("_tiny.port", "tiny")):



            for line in subprocess.run(
                ["ps", "-eo", "pid,args"],
                capture_output=True, text=True, timeout=2,
            ).stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    pidi = int(parts[0])
                except ValueError:
                    continue
                if "llama-server" not in parts[1]:
                    continue


                want_port = _big.port if target == "big" else _tiny.port
                if f"--port {want_port}" in parts[1] or f"--port={want_port}" in parts[1]:
                    if target == "big":
                        big_pid = pidi
                    else:
                        tiny_pid = pidi
    except Exception:
        pass
    for line in proc.stdout.splitlines():

        try:

            first, rest = line.split(",", 1)
            name, mib_s = rest.rsplit(",", 1)
            pid_i = int(first.strip())
            mib = int(mib_s.strip())
        except Exception:
            continue
        out["by_pid"].append({"pid": pid_i, "name": name.strip(), "mib": mib})
        if big_pid is not None and pid_i == big_pid:
            out["big_mib"] += mib
        elif tiny_pid is not None and pid_i == tiny_pid:
            out["tiny_mib"] += mib
        else:
            out["other_mib"] += mib
    out["ok"] = True
    return out


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


def _probe_big_n_ctx() -> Optional[int]:

    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{_big.port}/v1/models",
                                    timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))

        for entry in data.get("data", []):
            meta = entry.get("meta") or {}
            n_ctx = meta.get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                return n_ctx
    except Exception:
        return None
    return None


def _load_session_model() -> tuple:

    if _big.is_healthy():
        actual_ctx = _probe_big_n_ctx()
        if actual_ctx is not None and actual_ctx < int(CFG.big_ctx):
            _log(f"Big model running with too-small n_ctx (got {actual_ctx}, "
                 f"want at least {int(CFG.big_ctx)}) — reloading", "🔁", YELLOW)


            if _big.proc is not None:
                _big.stop()

            else:
                _log(f"Big is externally-owned with too-small n_ctx — please "
                     f"restart it manually with --ctx-size {int(CFG.big_ctx)}",
                     "⚠️", YELLOW)
                return True, str(_big.model_path), False
        else:
            _log(f"Model already up: {Path(_big.model_path).name} "
                 f"(n_ctx={actual_ctx})", "▶️", DIM)
            return True, str(_big.model_path), False
    free_gb = _free_vram_gb()
    if free_gb is None:
        why = "VRAM probe failed"
    else:
        why = f"VRAM free {free_gb:.1f}GB"
    _log(f"{why} — loading big model {Path(CFG.big_model).name}", "🔄", CYAN)
    if Path(_big.model_path).resolve() != Path(CFG.big_model).resolve():
        ok = _swap_big(str(CFG.big_model), ctx=int(CFG.big_ctx),
                       ngl=int(CFG.big_ngl), alias=str(CFG.big_alias),
                       extra_args=_big_extra_args())
    else:
        ok = _start_big()
    return ok, str(_big.model_path), False


_big = LlamaServer(
    "big", str(CFG.big_model), port=int(CFG.big_model_port),
    ctx=int(CFG.big_ctx), ngl=int(CFG.big_ngl), alias=str(CFG.big_alias),
    extra_args=_big_extra_args(), log_file=str(CFG.big_log), startup_timeout=300,
)
_tiny = LlamaServer(
    "tiny", str(CFG.tiny_model), port=int(CFG.tiny_model_port),
    ctx=2048, ngl=999, alias="cortexagent-tiny",


    extra_args=["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-np", "1"],
    log_file=str(CFG.logs_dir / "tiny-server.log"), startup_timeout=180,
)


def _start_tiny() -> bool:
    if _tiny.is_healthy():
        return True
    _log(f"Starting tiny model on :{_tiny.port}...", "🔄", CYAN)
    ok = _tiny.start()
    _log(f"Tiny model {'ready' if ok else 'FAILED'} on :{_tiny.port}",
         "✅" if ok else "❌", GREEN if ok else RED)
    return ok


def _start_big(timeout: Optional[int] = None) -> bool:

    global _big
    with _big_lock:
        if _big.is_healthy():
            return True
        _log(f"Loading big model on :{_big.port} (this can take ~60s)...", "🔄", CYAN)
        ok = _big.start(timeout=timeout)
        _log(f"Big model {'ready' if ok else 'FAILED'} on :{_big.port} (pid {_big.pid})",
             "✅" if ok else "❌", GREEN if ok else RED)
        return ok


def _stop_big() -> bool:
    with _big_lock:
        if not _big.running and not _big.is_healthy():
            return True


        _log("Stopping big model — freeing VRAM...", "💤", YELLOW)
        ok = _big.stop()
        if ok:
            _log("Big model stopped — VRAM freed", "💤", DIM)
        else:
            _log("Big model stop returned False — pid may still be alive", "⚠️", YELLOW)
        return ok


def _swap_big(model_path: str, ctx: int = 8192, ngl: int = 999,
              alias: str = "cortexagent", extra_args: Optional[list] = None) -> bool:

    global _big
    with _big_lock:
        if _big.running or _big.is_healthy():

            if _big.proc is None:




                _log("Big not owned by daemon (adopted/external) — refusing swap", "🛡️", DIM)
                return False
            _log(f"Swapping — stopping current big ({Path(_big.model_path).name})",
                 "💤", YELLOW)
            _big.stop()
        _big = LlamaServer(
            "big", str(model_path), port=int(CFG.big_model_port),
            ctx=int(ctx), ngl=int(ngl), alias=str(alias),
            extra_args=list(extra_args or []),
            log_file=str(CFG.big_log), startup_timeout=300,
        )
        _log(f"Loading big model: {Path(model_path).name} on :{_big.port}", "🔄", CYAN)
        ok = _big.start()
        _log(f"Big model {'ready' if ok else 'FAILED'} ({Path(model_path).name})",
             "✅" if ok else "❌", GREEN if ok else RED)
        return ok


def _stop_tiny() -> bool:


    if _tiny.proc is None:
        _log("Tiny not owned by daemon (adopted/external) — leaving it", "🛡️", DIM)
        return True
    return _tiny.stop()



def _start_proxy() -> bool:

    global _proxy_proc
    proxy_script = _REPO_ROOT / "lib" / "grammar_proxy.py"
    if not proxy_script.exists():
        _log("grammar_proxy.py not found — proxy disabled", "⚠️", YELLOW)
        return False
    port = int(os.environ.get("CORTEXAGENT_PROXY_PORT", "8081"))
    log = CFG.logs_dir / "proxy.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CORTEXAGENT_PROXY_PORT"] = str(port)
    env["CORTEXAGENT_PROXY_TARGET"] = f"http://127.0.0.1:{_big.port}"
    try:
        log_fh = open(log, "ab")
    except OSError as e:
        _log(f"Proxy log open error: {e}", "❌", RED)
        return False
    try:
        _proxy_proc = subprocess.Popen(
            [sys.executable, str(proxy_script), str(port)],
            env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception as e:
        log_fh.close()
        _log(f"Proxy start error: {e}", "❌", RED)
        return False
    log_fh.close()
    time.sleep(1)
    ok = _proxy_proc.poll() is None
    _log(f"Grammar proxy {'ready' if ok else 'FAILED'} on :{port} (pid {_proxy_proc.pid if _proxy_proc else '?'})",
         "✅" if ok else "❌", GREEN if ok else RED)
    return ok


def _stop_proxy() -> None:
    global _proxy_proc
    if _proxy_proc and _proxy_proc.poll() is None:
        try:
            _proxy_proc.terminate()
            _proxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proxy_proc.kill()
    _proxy_proc = None



def _idle_watcher() -> None:

    global _active_sessions, _SHUTDOWN
    while not _SHUTDOWN:
        time.sleep(IDLE_POLL)
        should_unload = False




        with _big_lock:
            big_running = _big.running
            with _lock:
                last = _last_request
                sessions = _active_sessions





            if big_running and sessions > 0 and last:
                idle = time.time() - last
                if idle > CFG.stale_session_sec:
                    _log(f"Session claim stale ({int(idle)}s no request > "
                         f"{CFG.stale_session_sec}s) — releasing {sessions} leaked "
                         f"session(s) so big model can idle-unload",
                         "🧹", YELLOW)
                    with _lock:
                        _active_sessions = 0
                    sessions = 0
            if big_running and sessions == 0 and last and CFG.idle_unload_sec > 0:
                idle = time.time() - last
                if idle > CFG.idle_unload_sec:
                    _log(f"Idle {int(idle)}s > {CFG.idle_unload_sec}s — unloading big model",
                         "💤", YELLOW)
                    should_unload = True







            global _tiny_was_healthy, _tiny_down_since
            tiny_healthy = _tiny.is_healthy(timeout=1)
            now = time.time()
            if tiny_healthy:
                _tiny_down_since = 0.0
            elif _tiny_down_since == 0.0:
                _tiny_down_since = now
            if (not tiny_healthy and _tiny_was_healthy and big_running):
                _log(f"Tiny :{_tiny.port} DOWN — grace {TINY_DEATH_GRACE_SEC:.0f}s "
                     f"before big-kill", "⚠️", YELLOW)
            if (not tiny_healthy and big_running
                    and _tiny_down_since > 0
                    and (now - _tiny_down_since) >= TINY_DEATH_GRACE_SEC):
                _log(f"Tiny :{_tiny.port} DOWN >{TINY_DEATH_GRACE_SEC:.0f}s — "
                     f"unloading big to free VRAM (tiny-death → big-kill rule)",
                     "🛑", YELLOW)
                should_unload = True
            _tiny_was_healthy = tiny_healthy
        if should_unload:
            _stop_big()



def _handle(req: Dict) -> Dict:
    global _active_sessions, _last_request, _SHUTDOWN
    cmd = req.get("cmd", "")

    if cmd == "ping":
        return {"ok": True}

    if cmd == "status":



        sessions = _scan_active_sessions()
        primary = sessions[0] if sessions else {}
        return {
            "ok": True,
            "big": {"port": _big.port, "healthy": _big.is_healthy(timeout=1), "running": _big.running,
                    "model": str(_big.model_path),
                    "alias": str(_big.alias) if hasattr(_big, "alias") else ""},
            "tiny": {"port": _tiny.port,
                    "healthy": _tiny.is_healthy(timeout=1),





                    "running": bool(_tiny.running) or _tiny.is_healthy(timeout=1)},
            "proxy": {"running": (lambda p: bool(p and p.poll() is None))(_proxy_proc)},
            "active_sessions": _active_sessions,
            "sessions": sessions,
            "session": primary,
            "vram_by_proc": _vram_by_process(),
            "last_request": _last_request,
            "idle_sec": int(time.time() - _last_request) if _last_request else None,
            "idle_unload_sec": int(CFG.idle_unload_sec),
        }

    if cmd == "activity":

        with _lock:
            _last_request = time.time()
        return {"ok": True, "big_healthy": _big.is_healthy()}

    if cmd == "load":
        which = req.get("which", "big")



        with _lock:
            _last_request = time.time()



        model = req.get("model")
        if model and which in ("big", None):
            ok = _swap_big(model, ctx=int(req.get("ctx") or 8192),
                           ngl=int(req.get("ngl") or 999),
                           alias=req.get("alias", "cortexagent"),
                           extra_args=req.get("extra_args"))
            return {"ok": ok, "big_healthy": _big.is_healthy(),
                    "model": str(_big.model_path)}
        if which == "big":
            ok = _start_big(timeout=int(req.get("timeout") or 300))
            return {"ok": ok, "big_healthy": _big.is_healthy()}
        if which == "tiny":
            return {"ok": _start_tiny(), "tiny_healthy": _tiny.is_healthy()}
        if which == "all":
            return {"ok": _start_tiny() and _start_big(), }
        return {"ok": False, "error": f"unknown which: {which}"}

    if cmd == "swap":


        model = req.get("model")
        if not model:
            return {"ok": False, "error": "swap requires 'model' path"}
        with _lock:
            _last_request = time.time()
        ok = _swap_big(model, ctx=int(req.get("ctx") or 8192),
                       ngl=int(req.get("ngl") or 999),
                       alias=req.get("alias", "cortexagent"),
                       extra_args=req.get("extra_args"))
        return {"ok": ok, "big_healthy": _big.is_healthy(),
                "model": str(_big.model_path)}

    if cmd == "unload":
        which = req.get("which", "big")
        if which == "big":
            return {"ok": _stop_big()}
        if which == "tiny":
            return {"ok": _stop_tiny()}
        if which == "all":
            return {"ok": _stop_big() and _stop_tiny()}
        return {"ok": False, "error": f"unknown which: {which}"}

    if cmd == "session-start":
        with _lock:
            _active_sessions += 1
            _last_request = time.time()





        ok, model_path, is_fallback = _load_session_model()
        if not ok:




            with _lock:
                _active_sessions = max(0, _active_sessions - 1)







        tiny_ok = True
        try:
            if not _tiny.is_healthy():
                _log("Tiny :8082 down on session-start — reloading",
                     "🛡️", DIM)
                tiny_ok = _start_tiny()
        except Exception as _e:
            tiny_ok = False
            _log(f"Tiny reload attempt failed: {_e}", "⚠️", YELLOW)
        return {"ok": ok, "active_sessions": _active_sessions,
                "big_healthy": _big.is_healthy(), "model": model_path,
                "fallback": is_fallback,
                "tiny_healthy": _tiny.is_healthy(),
                "tiny_reloaded": tiny_ok and not _tiny_was_healthy}

    if cmd == "session-end":
        with _lock:
            _active_sessions = max(0, _active_sessions - 1)
            _last_request = time.time()
        _log(f"Session end (active={_active_sessions}) — big idles in {CFG.idle_unload_sec}s",
             "⏹️", DIM)
        return {"ok": True, "active_sessions": _active_sessions}

    if cmd == "session-reset":



        with _lock:
            _active_sessions = 0
            _last_request = time.time()
        _log("Session reset (stale session detected by overseer watchdog) — unloading big model",
             "🧹", YELLOW)
        _stop_big()
        return {"ok": True, "active_sessions": 0}

    if cmd == "shutdown":
        _SHUTDOWN = True
        _log("Shutdown requested", "🛑", YELLOW)
        return {"ok": True}

    if cmd == "proxy-metrics":



        try:
            import urllib.request
            port = int(os.environ.get("CORTEXAGENT_PROXY_PORT", "8081"))
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/metrics", timeout=2
            ) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            return {"ok": False, "error": f"proxy metrics: {exc}"}

    return {"ok": False, "error": f"unknown cmd: {cmd}"}



def _run() -> None:

    signal.signal(signal.SIGTERM, lambda *_: _request_shutdown())
    signal.signal(signal.SIGINT, lambda *_: _request_shutdown())

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (CFG.logs_dir).mkdir(parents=True, exist_ok=True)
    _log(f"CortexAgent daemon starting (idle_unload={CFG.idle_unload_sec}s)", "🚀", CYAN)




    if _tiny.is_healthy():
        _log(f"Tiny :{_tiny.port} up (owned by overseer — adopted)", "🛡️", DIM)
    else:
        _log(f"Tiny :{_tiny.port} down — overseer will keepalive it", "💤", DIM)
    _start_proxy()





    if not _big.running and _big.is_healthy(timeout=1):
        _log(f"Orphaned big model detected on :{_big.port} — killing it", "🧹", YELLOW)
        _big._kill_port_server()
    elif _big.running:
        _log(f"Big model :{_big.port} up (pid {_big.pid})", "▶️", DIM)

    threading.Thread(target=_idle_watcher, daemon=True).start()
    threading.Thread(target=control.serve, args=(_handle,), daemon=True).start()

    _log("Daemon ready — control socket listening", "✅", GREEN)
    while not _SHUTDOWN:
        time.sleep(1)



    _log("Daemon shutting down — stopping proxy + big model...", "🛑", YELLOW)
    _stop_proxy()
    _stop_big()
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
    big = s["big"]
    tiny = s["tiny"]
    from pathlib import Path as _P
    model_name = _P(big.get("model", "")).name or "?"
    print(f"CortexAgent daemon: 🟢 running")
    print(f"  big  :{big['port']}  {'🟢 healthy' if big['healthy'] else '🔴 down'}  (running={big['running']})")
    print(f"       model: {model_name} (big)")
    print(f"  tiny :{tiny['port']}  {'🟢 healthy' if tiny['healthy'] else '🔴 down'}  (running={tiny['running']})")
    print(f"  proxy: {'🟢 up' if s['proxy']['running'] else '🔴 down'}")
    print(f"  sessions: {s['active_sessions']}  idle: {s['idle_sec']}s / {s['idle_unload_sec']}s")
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