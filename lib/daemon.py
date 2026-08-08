#!/usr/bin/env python3
"""lib/daemon.py — the persistent CortexAgent backend daemon.

Owns the model backends and the grammar proxy so the CLI can be a thin client:

  - big coding model on :8080        (loaded on demand, idle-unloaded to free VRAM)
  - grammar proxy on :8081           (reload-aware: triggers big reload on request)
  - AF_UNIX control socket           (status / load / unload / session / shutdown)

The tiny 0.5b (:8082) is owned by the always-on OVERSEER systemd service, not
this daemon. The daemon reports its state + exposes manual ``load tiny`` /
``unload tiny`` commands, but does NOT auto-start/stop it (avoids a boot race).

Idle auto-unload: after ``CORTEXAGENT_IDLE_UNLOAD_SEC`` (default 600s) with no
proxy traffic and no active CLI session, the big model is stopped → ~13 GB VRAM
freed. The next request reloads it transparently (the proxy buffers + retries),
so the CLI never relaunches and never sees a 502.

Lifecycle:
  python3 lib/daemon.py run       # foreground (systemd ExecStart)
  python3 lib/daemon.py start     # fork to background (manual)
  python3 lib/daemon.py stop      # graceful shutdown via control socket
  python3 lib/daemon.py status    # report via control socket

No Ollama. No hardcoded home paths (all via lib/config.py).
"""
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
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402
from lib.model_backend import LlamaServer  # noqa: E402
from lib import control  # noqa: E402

# ── State ────────────────────────────────────────────────────────────────────
STATE_DIR = CFG.state_dir
LOG_FILE = CFG.logs_dir / "daemon.log"
PID_FILE = STATE_DIR / "daemon.pid"
IDLE_POLL = 5  # seconds between idle checks

_lock = threading.Lock()       # brief: _last_request / _active_sessions counters
_big_lock = threading.Lock()   # serializes big-model load/unload (long-held)
_last_request = 0.0          # unix ts of last proxy activity / session event
_active_sessions = 0         # CLI sessions currently active (refcount)
_SHUTDOWN = False
_proxy_proc: Optional[subprocess.Popen] = None

# ── Colors ───────────────────────────────────────────────────────────────────
CYAN, GREEN, YELLOW, RED, DIM, BOLD, RST = (
    "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m")


def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{color}{emoji} {BOLD}daemon{RST} {DIM}{color}[{ts}]{RST} {color}{msg}{RST}"
    print(line, file=sys.stderr)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass  # best-effort — don't let logging failure mask the real error


# ── Model backends ────────────────────────────────────────────────────────────
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


def _fallback_extra_args() -> list:
    """llama-server args for the small fallback model (LFM2.5-8B-A1B).

    Mamba-2 + MoE hybrid (8.3B total / 1.5B active, Q4_K_M ≈ 6.7 GB). Used when
    sustained GPU load leaves < big_vram_min_gb free, so the 35B won't fit. Runs
    at fallback_ctx (8192) — small, so the kv-unified compute-buffer savings
    are negligible; verified to load and emit OpenAI tool_calls WITHOUT
    --kv-unified, so we omit it (same fa/ctk/ctv/np/batch knobs as the big
    model so the proxy + tool-calling path stay consistent).
    """
    return [
        "-fa", str(CFG.big_fa),
        "-ctk", str(CFG.big_ctk),
        "-ctv", str(CFG.big_ctv),
        "-np", str(CFG.big_np),
        "-b", str(CFG.big_b),
        "-ub", str(CFG.big_ub),
    ]


def _free_vram_gb(samples: int = 3, interval: float = 0.7) -> Optional[float]:
    """Free GPU VRAM in GB, glitch-rejecting. Returns the MAX free across
    ``samples`` reads spaced ``interval`` seconds apart.

    Why max-of-N (not one read, not min, not median): a single nvidia-smi read
    can catch a momentary spike — a browser compositing, a tab initializing,
    a window resize — that frees in well under a second. One such glitch must
    NOT force the small fallback when the GPU actually has room for the 35B.
    Taking the best (max) reading across ~2s means we only fall back when VRAM
    is CONSISTENTLY low on every sample — i.e. a real, sustained GPU consumer
    (a game, a diffusion run, a browser with HW accel holding VRAM). A
    sub-second transient is rejected because at least one sample lands outside
    it. None (no NVIDIA GPU / nvidia-smi fails on every sample) → caller treats
    as 'enough VRAM' so we never block on a missing probe.
    """
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


def _load_session_model() -> tuple:
    """Pick the big model if VRAM allows, else the small fallback. VRAM-aware.

    Re-runs every session-start. If the current model is already up + healthy,
    keep it — no VRAM probe. (The probe reads *free* VRAM, which counts the big
    model's own ~14 GB as "used", so probing while the big model is loaded
    would read ~2 GB free and wrongly swap the healthy big model out for the
    fallback.) Otherwise probe free VRAM (glitch-rejecting: max of 3 reads). If
    a sustained GPU load (browser, game, diffusion) leaves < big_vram_min_gb
    free, the 35B would spill to CPU (slow), so swap in the small fallback.
    Returns (ok, model_path, is_fallback).
    """
    if _big.is_healthy():
        is_fallback = Path(_big.model_path).resolve() == Path(CFG.fallback_model).resolve()
        _log(f"Model already up: {Path(_big.model_path).name}", "▶️", DIM)
        return True, str(_big.model_path), is_fallback
    free_gb = _free_vram_gb()
    if free_gb is None:
        desired_big = True
        why = "VRAM probe failed"
    else:
        desired_big = free_gb >= float(CFG.big_vram_min_gb)
        why = f"VRAM free {free_gb:.1f}GB {'≥' if desired_big else '<'} {CFG.big_vram_min_gb}GB"
    desired_path = str(CFG.big_model) if desired_big else str(CFG.fallback_model)
    already = Path(_big.model_path).resolve() == Path(desired_path).resolve()
    if desired_big:
        if already:
            _log(f"{why} — (re)loading big model", "▶️", CYAN)
            ok = _start_big()
        else:
            _log(f"{why} — swapping to big model", "▶️", CYAN)
            ok = _swap_big(str(CFG.big_model), ctx=int(CFG.big_ctx),
                           ngl=int(CFG.big_ngl), alias=str(CFG.big_alias),
                           extra_args=_big_extra_args())
        return ok, str(_big.model_path), False
    _log(f"{why} (sustained GPU load) — fallback {Path(CFG.fallback_model).name}",
         "🎮", YELLOW)
    ok = _swap_big(str(CFG.fallback_model), ctx=int(CFG.fallback_ctx), ngl=999,
                   alias=str(CFG.big_alias), extra_args=_fallback_extra_args())
    return ok, str(_big.model_path), True


_big = LlamaServer(
    "big", str(CFG.big_model), port=int(CFG.big_model_port),
    ctx=int(CFG.big_ctx), ngl=int(CFG.big_ngl), alias=str(CFG.big_alias),
    extra_args=_big_extra_args(), log_file=str(CFG.big_log), startup_timeout=300,
)
_tiny = LlamaServer(
    "tiny", str(CFG.tiny_model), port=int(CFG.tiny_model_port),
    ctx=2048, ngl=999, alias="cortexagent-tiny",
    # Lean keepalive: 1 slot + q4_0 KV + flash-attn ≈ 300 MB (was 640 MB at
    # 4-slot f16). Frees VRAM for the 35B big model on 16 GB cards.
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
    """Load the big model and wait for /health. Idempotent. Thread-safe.

    Holds _big_lock for the (long) duration so only one load runs at a time,
    but does NOT hold _lock — so activity/status/session commands stay responsive.

    If the big (35B) model fails to load — e.g. a transient CUDA OOM from VRAM
    contention — falls back to the small model on the same port so :8080 stays
    up. Without this, a failed 35B load leaves :8080 dead and the CLI hangs on
    "Herding…". (_load_session_model picks the model up front from a VRAM probe;
    this catches the case where VRAM looked free but the load still OOM'd.)
    """
    global _big
    with _big_lock:
        if _big.is_healthy():
            return True
        _log(f"Loading big model on :{_big.port} (this can take ~60s)...", "🔄", CYAN)
        ok = _big.start(timeout=timeout)
        _log(f"Big model {'ready' if ok else 'FAILED'} on :{_big.port} (pid {_big.pid})",
             "✅" if ok else "❌", GREEN if ok else RED)
        if ok:
            return True
        # 35B failed (e.g. CUDA OOM). Only fall back if we were actually trying
        # the big model — don't recurse if the fallback itself just failed.
        if Path(_big.model_path).resolve() != Path(CFG.big_model).resolve():
            return False
        _log("Big model failed — falling back to small model on :8080", "⚠️", YELLOW)
        _big.stop()
        _big = LlamaServer(
            "big", str(CFG.fallback_model), port=int(CFG.big_model_port),
            ctx=int(CFG.fallback_ctx), ngl=999, alias=str(CFG.big_alias),
            extra_args=_fallback_extra_args(), log_file=str(CFG.big_log),
            startup_timeout=300,
        )
        ok2 = _big.start(timeout=timeout)
        _log(f"Fallback model {'ready' if ok2 else 'FAILED'} on :{_big.port} "
             f"(pid {_big.pid})", "✅" if ok2 else "❌", GREEN if ok2 else RED)
        return ok2


def _stop_big() -> bool:
    with _big_lock:
        if not _big.running and not _big.is_healthy():
            return True
        # Don't kill a big model we didn't start (e.g. one already on :8080 that
        # the daemon adopted via is_healthy()). proc is None in that case.
        if _big.proc is None:
            _log("Big not owned by daemon (adopted/external) — leaving it", "🛡️", DIM)
            return True
        _log("Stopping big model — freeing VRAM...", "💤", YELLOW)
        ok = _big.stop()
        _log("Big model stopped — VRAM freed", "💤", DIM)
        return ok


def _swap_big(model_path: str, ctx: int = 8192, ngl: int = 999,
              alias: str = "cortexagent", extra_args: Optional[list] = None) -> bool:
    """Hot-swap a different model into the main slot (:8080).

    Stops the current big model and loads ``model_path`` in its place, keeping
    the same port (so the grammar proxy's target stays valid). Used to switch
    between coding / image / video / overseer models by type — one model at a
    time. Holds _big_lock for the whole stop→start so status/session views stay
    consistent. Returns True if the new model is healthy.
    """
    global _big
    with _big_lock:
        if _big.running or _big.is_healthy():
            # Don't kill a big model we didn't start (adopted/external).
            if _big.proc is None:
                # An external server we don't own is up on :8080 — we can't
                # swap (the port is occupied and we won't kill a server we
                # didn't start). Refuse rather than start a second server that
                # fails to bind.
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
        # OOM fallback (mirrors _start_big): a big-model swap that fails to
        # load (e.g. CUDA OOM from VRAM contention) must not leave :8080 dead —
        # fall back to the small model on the same port so the session works.
        if not ok and Path(model_path).resolve() == Path(CFG.big_model).resolve():
            _log("Big model failed — falling back to small model on :8080", "⚠️", YELLOW)
            _big.stop()
            _big = LlamaServer(
                "big", str(CFG.fallback_model), port=int(CFG.big_model_port),
                ctx=int(CFG.fallback_ctx), ngl=999, alias=str(CFG.big_alias),
                extra_args=_fallback_extra_args(), log_file=str(CFG.big_log),
                startup_timeout=300,
            )
            ok = _big.start()
        _log(f"Big model {'ready' if ok else 'FAILED'} ({Path(model_path).name})",
             "✅" if ok else "❌", GREEN if ok else RED)
        return ok


def _stop_tiny() -> bool:
    # Don't kill a tiny we didn't start (e.g. the overseer's tiny already on
    # :8082 that the daemon adopted via is_healthy()). proc is None then.
    if _tiny.proc is None:
        _log("Tiny not owned by daemon (adopted/external) — leaving it", "🛡️", DIM)
        return True
    return _tiny.stop()


# ── Grammar proxy ─────────────────────────────────────────────────────────────
def _start_proxy() -> bool:
    """Start the reload-aware grammar proxy on :8081 (→ :8080)."""
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
        log_fh.close()  # Popen raised — don't leak the log fd
        _log(f"Proxy start error: {e}", "❌", RED)
        return False
    log_fh.close()  # parent's fd no longer needed — child has a dup'd copy
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


# ── Idle watcher ──────────────────────────────────────────────────────────────
def _idle_watcher() -> None:
    """Unload the big model when idle to free VRAM."""
    while not _SHUTDOWN:
        time.sleep(IDLE_POLL)
        should_unload = False
        # Re-check sessions while holding _big_lock: a session-start's load
        # (via _start_big/_swap_big) also takes _big_lock, so if a session
        # started while we slept, we see its incremented refcount here and skip
        # the unload instead of racing it (TOCTOU).
        with _big_lock:
            big_running = _big.running
            with _lock:
                last = _last_request
                sessions = _active_sessions
            if big_running and sessions == 0 and last:
                idle = time.time() - last
                if idle > CFG.idle_unload_sec:
                    _log(f"Idle {int(idle)}s > {CFG.idle_unload_sec}s — unloading big model",
                         "💤", YELLOW)
                    should_unload = True
        if should_unload:
            _stop_big()  # re-acquires _big_lock — must be outside the with block


# ── Control socket handler ────────────────────────────────────────────────────
def _handle(req: Dict) -> Dict:
    global _active_sessions, _last_request, _SHUTDOWN
    cmd = req.get("cmd", "")

    if cmd == "ping":
        return {"ok": True}

    if cmd == "status":
        # Short health-check timeout: status must stay responsive even when a
        # model is down (a down port can take the full connect timeout to fail,
        # and two sequential checks would blow past the CLI's 5s request timeout).
        return {
            "ok": True,
            "big": {"port": _big.port, "healthy": _big.is_healthy(timeout=1), "running": _big.running,
                    "model": str(_big.model_path),
                    "fallback": Path(_big.model_path).resolve() == Path(CFG.fallback_model).resolve()},
            "tiny": {"port": _tiny.port, "healthy": _tiny.is_healthy(timeout=1), "running": _tiny.running},
            "proxy": {"running": (lambda p: bool(p and p.poll() is None))(_proxy_proc)},
            "active_sessions": _active_sessions,
            "last_request": _last_request,
            "idle_sec": int(time.time() - _last_request) if _last_request else None,
            "idle_unload_sec": int(CFG.idle_unload_sec),
        }

    if cmd == "activity":
        # proxy reports a forward — reset the idle timer
        with _lock:
            _last_request = time.time()
        return {"ok": True, "big_healthy": _big.is_healthy()}

    if cmd == "load":
        which = req.get("which", "big")
        # A manual load counts as activity — prime the idle timer so the model
        # idles out after idle_unload_sec if no session claims it (rather than
        # the idle watcher skipping it because _last_request was never set).
        with _lock:
            _last_request = time.time()
        # Optional model swap: load an arbitrary model into the big slot (image
        # / video / overseer / a different coding model). Only meaningful for
        # the big slot — the tiny overseer is fixed.
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
        # Explicit hot-swap of an arbitrary model into the main slot (:8080).
        # {cmd:"swap", model:"/path/to/model.gguf", ctx?, ngl?, alias?, extra_args?}
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
        # VRAM-aware: load the big model if there's room, else the small
        # fallback (game / GPU load present). Synchronous so the first token
        # isn't delayed by a cold load; later sessions find it up → idempotent.
        # Thread-per-connection control socket ⇒ this long call does NOT
        # block concurrent activity/status/ping commands.
        ok, model_path, is_fallback = _load_session_model()
        return {"ok": ok, "active_sessions": _active_sessions,
                "big_healthy": _big.is_healthy(), "model": model_path,
                "fallback": is_fallback}

    if cmd == "session-end":
        with _lock:
            _active_sessions = max(0, _active_sessions - 1)
            _last_request = time.time()  # restart idle timer; big stays for idle_sec
        _log(f"Session end (active={_active_sessions}) — big idles in {CFG.idle_unload_sec}s",
             "⏹️", DIM)
        return {"ok": True, "active_sessions": _active_sessions}

    if cmd == "session-reset":
        # Stale-session recovery: the overseer watchdog calls this when it
        # detects cortexagent is closed but the session refcount never reached 0
        # (e.g. the CLI was SIGKILLed before its cleanup could send session-end).
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

    return {"ok": False, "error": f"unknown cmd: {cmd}"}


# ── Main loop ─────────────────────────────────────────────────────────────────
def _run() -> None:
    """Foreground daemon: proxy + control socket + idle watcher.

    The tiny 0.5b (:8082) is owned by the always-on OVERSEER systemd service,
    NOT by this daemon. The daemon's ``_tiny`` instance is kept only for status
    reporting (``is_healthy``) and manual ``load tiny``/``unload tiny`` control
    commands — it does NOT auto-start/stop the tiny at boot/shutdown. This
    avoids a boot race where both services start a tiny and contend for :8082.
    """
    signal.signal(signal.SIGTERM, lambda *_: _request_shutdown())
    signal.signal(signal.SIGINT, lambda *_: _request_shutdown())

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (CFG.logs_dir).mkdir(parents=True, exist_ok=True)
    _log(f"CortexAgent daemon starting (idle_unload={CFG.idle_unload_sec}s)", "🚀", CYAN)

    # Tiny is the overseer's responsibility — don't start it here. Just report
    # its state (overseer has it up); if it's down the overseer's keepalive owns
    # the recovery, not us.
    if _tiny.is_healthy():
        _log(f"Tiny :{_tiny.port} up (owned by overseer — adopted)", "🛡️", DIM)
    else:
        _log(f"Tiny :{_tiny.port} down — overseer will keepalive it", "💤", DIM)
    _start_proxy()

    # Kill any orphaned big model on :8080 that the daemon doesn't own.
    # On restart, the old daemon's _big.proc is gone but the llama-server
    # process may still be running — the daemon can't manage its lifecycle
    # (idle-unload, swap, etc.) without owning the Popen handle.
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

    # ── graceful shutdown ──
    # Stop the proxy + any big model we own; leave the tiny (overseer-owned).
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
    """Fork to background (manual start without systemd)."""
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
        # maybe running as systemd (no pid file) — try the socket
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
    # wait for exit
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
    tag = " 🎮 fallback (low VRAM)" if big.get("fallback") else " (big)"
    print(f"CortexAgent daemon: 🟢 running")
    print(f"  big  :{big['port']}  {'🟢 healthy' if big['healthy'] else '🔴 down'}  (running={big['running']})")
    print(f"       model: {model_name}{tag}")
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