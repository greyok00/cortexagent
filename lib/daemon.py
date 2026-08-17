#!/usr/bin/env python3
"""lib/daemon.py — the persistent CortexAgent backend daemon.

Owns the model backends and the grammar proxy so the CLI can be a thin client:

  - big coding model on :8080        (loaded on demand, idle-unloaded to free VRAM)
  - grammar proxy on :8081           (reload-aware: triggers big reload on request)
  - AF_UNIX control socket           (status / load / unload / session / shutdown)

The tiny LFM2.5-1.2B (:8082) is owned by the always-on OVERSEER systemd service, not
this daemon. The daemon reports its state + exposes manual ``load tiny`` /
``unload tiny`` commands, but does NOT auto-start/stop it (avoids a boot race).

Idle auto-unload: after ``CORTEXAGENT_IDLE_UNLOAD_SEC`` (default 0s — big stays
loaded) with no proxy traffic and no active CLI session, the big model is
stopped → ~13 GB VRAM freed. The next request reloads it transparently (the
proxy buffers + retries), so the CLI never relaunches and never sees a 502.

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
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402
from lib.model_backend import LlamaServer  # noqa: E402
from lib import control  # noqa: E402
from lib.errorlog import log_exception, close_dump  # noqa: E402

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
_tiny_was_healthy = True     # edge-detector: trigger big-kill on tiny death (rising edge only)
_tiny_down_since: float = 0.0  # unix ts; 0.0 = currently up. Big-kill only fires after GRACE_SEC of continuous downtime.
TINY_DEATH_GRACE_SEC = 3.0    # tolerate brief tiny restarts (keepalive reload) before unloading the 13.7 GB big


def _scan_active_sessions() -> List[Dict]:
    """Inventory ONLY CortexAgent's own local stack — NEVER generic claude /
    ollama / shell processes. We match by comm + cmdline marker:

      comm == "llama-server" with --port 8080 (big) or --port 8082 (tiny)
      cmdline contains  /lib/daemon.py
      cmdline contains  /lib/overseer.py
      cmdline contains  /lib/grammar_proxy.py
      cmdline contains  /lib/webui.py
      cmdline contains  /lib/diffusion_backend.py  (diffusers run)

    The user explicitly does NOT want generic Claude / ollama launches picked
    up here — those can be any third-party claude session and would mislead
    the dashboard. If we don't match a process here, it isn't CortexAgent.

    Returns a list of dicts; capped at 12."""
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
        # llama-server on the ports we own
        if comm == "llama-server":
            if "--port 8080" in args or "--port=8080" in args:
                _emit(pid_i, etime, comm, args, "big")
                continue
            if "--port 8082" in args or "--port=8082" in args:
                _emit(pid_i, etime, comm, args, "tiny")
                continue
        # Own-stack python processes (lib/* paths under this repo)
        for marker, kind in (
            ("/lib/daemon.py",        "daemon"),
            ("/lib/overseer.py",      "overseer"),
            ("/lib/grammar_proxy.py", "proxy"),
            ("/lib/webui.py",         "webui"),
            ("/lib/diffusion_backend.py", "diffusion"),
        ):
            if marker in args:
                _emit(pid_i, etime, comm, args, kind)
                break
        if len(out) >= 12:
            break
    return out

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


def _vram_by_process() -> Dict[str, Any]:
    """Per-process VRAM breakdown for the status payload.

    Uses ``nvidia-smi --query-compute-apps=pid,process_name,used_memory`` so the
    dashboard + statusline can show "big 14.3GB + tiny 0.9GB + other 0GB" instead
    of a single 14.9/16GB total that hides who's using what. Categorises by
    whether the owning PID matches a known model slot (:8080 big / :8082 tiny
    llama-server); everything else falls into ``other``.

    Cheap & cached: the query runs at most once per status call (~tens of ms),
    and the result is structured so a failed nvidia-smi just yields zeros — the
    UI degrades to the existing total-only display, never an error.
    """
    out: Dict[str, Any] = {
        "big_mib": 0,        # llama-server on _big.port
        "tiny_mib": 0,       # llama-server on _tiny.port
        "other_mib": 0,
        "by_pid": [],        # [{pid, name, mib}] for transparency
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
    # Map PID → port via /proc/<pid>/cmdline for known llama-server PIDs. We
    # only do this once per status call (typically 1-3 rows), so the cost is
    # negligible compared to nvidia-smi itself.
    big_pid: Optional[int] = None
    tiny_pid: Optional[int] = None
    try:
        for port_attr, target in (("_big.port", "big"), ("_tiny.port", "tiny")):
            # port lookup via the local Popen registry would be ideal but we
            # only need the PID for VRAM bucketing — accept a small race if the
            # model restarts between the nvidia-smi snapshot and the proc scan.
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
                # The big/tiny ports are stable per process startup; match by
                # the same port our LlamaServer instance is using.
                want_port = _big.port if target == "big" else _tiny.port
                if f"--port {want_port}" in parts[1] or f"--port={want_port}" in parts[1]:
                    if target == "big":
                        big_pid = pidi
                    else:
                        tiny_pid = pidi
    except Exception:
        pass
    for line in proc.stdout.splitlines():
        # csv-ish row: pid, name, used_mib  (name may contain spaces)
        try:
            pid_s, mib_s = line.rsplit(",", 1)
            name = pid_s.split(",", 1)[0] if "," in pid_s else ""
            # actually the schema is "pid, process_name, used_memory" — reparse
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


def _probe_big_n_ctx() -> Optional[int]:
    """Read the actual n_ctx the running llama-server on :8080 is using.

    Probes GET /v1/models and extracts meta.n_ctx. Used to detect when a
    stale or externally-launched server is on :8080 with a different ctx
    than CFG.big_ctx (e.g. an old 32k server from a prior experiment, an
    adopted 256k instance, etc.). Returns the int n_ctx or None on failure.
    """
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{_big.port}/v1/models",
                                    timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        # OpenAI-compat path: data[0].meta.n_ctx
        for entry in data.get("data", []):
            meta = entry.get("meta") or {}
            n_ctx = meta.get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                return n_ctx
    except Exception:
        return None
    return None


def _load_session_model() -> tuple:
    """Load the big model for the new session. Re-runs every session-start.

    If the big model is already up + healthy AND its reported n_ctx is at
    least CFG.big_ctx, keep it — no VRAM probe. (The probe reads *free* VRAM,
    which counts the big model's own ~14 GB as "used", so probing while the
    big model is loaded would read ~2 GB free and wrongly unload the healthy
    big model.) If the running server reports a SMALLER n_ctx than wanted
    (stale instance, externally-launched server with the wrong --ctx-size,
    leftover from a prior config), the daemon kills it and reloads with the
    correct size — without this, the cortex CLI gets stuck talking to a 32k
    server while the daemon thinks everything is fine.
    NOTE: llama.cpp rounds n_ctx UP to a multiple of 32, so the reported
    n_ctx is normally a little LARGER than CFG.big_ctx (e.g. 156160 vs the
    requested 156000). An exact-match check would therefore reload on every
    session start, keeping :8080 down and spamming "Connection refused".
    Only reload when the actual ctx is genuinely SMALLER than wanted.
    Otherwise probe free VRAM (glitch-rejecting: max of 3 reads) and log
    the result, then load the big model — it just gets loaded; if VRAM is
    genuinely too tight it fails and the daemon logs the failure (no
    fallback swap path). Returns (ok, model_path, is_fallback=False always).
    """
    if _big.is_healthy():
        actual_ctx = _probe_big_n_ctx()
        if actual_ctx is not None and actual_ctx < int(CFG.big_ctx):
            _log(f"Big model running with too-small n_ctx (got {actual_ctx}, "
                 f"want at least {int(CFG.big_ctx)}) — reloading", "🔁", YELLOW)
            # Adopted/external (proc is None) → can't stop it ourselves;
            # log and keep it. Otherwise stop and let _swap_big reload.
            if _big.proc is not None:
                _big.stop()
                # fall through to the load path below
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

    If the load fails (CUDA OOM, missing GGUF, etc.) the daemon logs the
    failure and returns False. There is no fallback swap path; :8080 stays
    down until the user fixes the underlying issue.
    """
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
    global _active_sessions, _SHUTDOWN  # stale-release at line 405 mutates these
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
            # Stale-session self-heal: a wrapper that died without sending
            # session-end (SIGPIPE/SIGKILL/orphaned bash) leaves the refcount
            # stuck >0, which permanently blocks the idle-unload below. If no
            # request has arrived for stale_session_sec, treat the claim as
            # dead and release it so idle-unload can free VRAM.
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
            # Tiny-death → big-kill with grace window. User rule: closing the
            # system tray or any tiny failure must unload big so the GPU isn't
            # held by an orphaned 13.7 GB process. But tiny's keepalive reload
            # (5-10s) used to reap big spuriously on every reload. TINY_DEATH_GRACE_SEC
            # tolerates brief downtime: big-kill only fires after tiny has been
            # continuously down for >=GRACE_SEC. Recovery within the grace
            # window cancels the pending kill entirely.
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
        sessions = _scan_active_sessions()
        primary = sessions[0] if sessions else {}
        return {
            "ok": True,
            "big": {"port": _big.port, "healthy": _big.is_healthy(timeout=1), "running": _big.running,
                    "model": str(_big.model_path),
                    "alias": str(_big.alias) if hasattr(_big, "alias") else ""},
            "tiny": {"port": _tiny.port,
                    "healthy": _tiny.is_healthy(timeout=1),
                    # running = process exists OR port responds. _tiny.running
                    # is a Popen-stored handle that can be stale after overseer
                    # adoption or external spawns; health-check the port as
                    # ground truth so the dashboard never reports a live model
                    # as "running: false".
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
        if not ok:
            # M11 fix: load failed → unwind the refcount increment so the
            # idle-unload path can still fire when there are no live sessions.
            # Without this, the big stays "claimed" by a session that never
            # opened (refcount leaks).
            with _lock:
                _active_sessions = max(0, _active_sessions - 1)
        # Tiny auto-reload: after the previous unload, pkill, or tray-close,
        # the overseer-owned tiny on :8082 may be down. The big model is
        # useless without the orchestrator (no scheduler, no memory
        # distillation, no diffusion orchestration). Try to reload tiny here
        # so the session starts in a balanced state. Overseer normally owns
        # tiny — if it's down the overseer should have reloaded it; we try
        # anyway as a safety net (the overseer can also adopt what we start).
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

    if cmd == "proxy-metrics":
        # Forward proxy /metrics via the daemon socket. The proxy exposes
        # current_tok_s, current_in_tps, current_out_tps, avg_tok_s,
        # avg_in_tps, avg_out_tps, minify{}, and VRAM stats.
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


# ── Main loop ─────────────────────────────────────────────────────────────────
def _run() -> None:
    """Foreground daemon: proxy + control socket + idle watcher.

    The tiny LFM2.5-1.2B (:8082) is owned by the always-on OVERSEER systemd service,
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
    # Close dump: record the clean shutdown (SIGINT/SIGTERM) with uptime so a
    # "normal close" is still auditable.
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