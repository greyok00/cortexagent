#!/usr/bin/env python3
"""overseer — unified heartbeat + orchestrator daemon for CortexAgent.

Combines memory health monitoring, task scheduling, plan tracking, and
the tiny LLM (LFM2.5-1.2B on llama-server :8082) into one persistent
background overseer.

Features:
  - Memory health monitoring (hot/warm/cold counts, cold distill)
  - Session health checks (proxy, DB integrity)
  - Task queue (add/list/clear/remove)
  - Calendar scheduler (cron/daily/weekly/date)
  - Plan tracking (set steps, advance, status)
  - Tiny LLM start/keepalive (LFM2.5-1.2B on llama-server :8082 — no Ollama)
  - PID-locked single instance
  - Persistent state across restarts

CLI:
  python3 overseer.py start [--interval 30]
  python3 overseer.py stop
  python3 overseer.py status
  python3 overseer.py smoke

  python3 overseer.py plan-set "Feature X" --steps 5 --context "Building X"
  python3 overseer.py plan-step [N]
  python3 overseer.py plan-status

  python3 overseer.py queue add --type command --command "echo hi"
  python3 overseer.py queue list
  python3 overseer.py queue clear

  python3 overseer.py schedule add --name "daily" --cron "0 9 * * *" --type command --command "backup"
  python3 overseer.py schedule list

  python3 overseer.py workflow run "pentest the network"
  python3 overseer.py workflow status
  python3 overseer.py workflow list
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _fromiso(s: str) -> datetime:
    """Compat wrapper for datetime.fromisoformat. Pre-3.11 only accepted the
    exact format `datetime.isoformat()` produces (no 'T' separator, no
    fractional seconds). 3.11+ accepts most ISO 8601 strings. We always
    generate ISO via `datetime.now().isoformat()` so the upgrade-to-3.11
    case is a no-op; the downgrade case is the one this guards against.
    """
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        # Common pre-3.11 issues: 'T' separator, 'Z' suffix, fractional secs.
        s2 = s.replace("T", " ").rstrip("Z")
        if "." in s2:
            s2 = s2.split(".")[0]
        return datetime.fromisoformat(s2)

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                 str(Path.home() / ".cortexagent")))
PID_FILE = STATE_DIR / "overseer.pid"
STATE_FILE = STATE_DIR / "overseer_state.json"
LOG_FILE = STATE_DIR / "logs" / "overseer.log"
QUEUE_FILE = STATE_DIR / "overseer_queue.json"
SCHEDULE_FILE = STATE_DIR / "overseer_schedule.json"
PLAN_FILE = STATE_DIR / "overseer_plan.json"
WORKFLOW_FILE = STATE_DIR / "workflow_state.json"

# ── Config + model backend (no Ollama) ────────────────────────────────────────
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from lib.config import CFG  # noqa: E402
from lib.model_backend import LlamaServer  # noqa: E402
from lib import tiny_llm  # noqa: E402
from lib import control  # noqa: E402 — daemon_present() to detect daemon mode

# Slimtoken pipeline for request optimization (minify, dedup, distill)
try:
    from slimtoken.pipeline import minify_request, MinifyConfig  # noqa: E402
    SLIMTOKEN_AVAILABLE = True
except ImportError:
    SLIMTOKEN_AVAILABLE = False

# SessionBridge for unified multi-agent chat (overseer emits "Overseer"
# username events). Imported lazily to keep boot safe if the bridge file
# is unreadable for any reason — the chat pane is a nice-to-have, the
# scheduler/dispatcher is the load-bearing thing.
def _bridge_emit(kind: str, content: str, **extra) -> None:
    """Emit one chat event to the SessionBridge with username='Overseer'.

    Best-effort: any exception is swallowed. The chat pane is decoration;
    the dispatch path is what matters.
    """
    try:
        from lib.session_bridge import SessionBridge
        ev = {
            "id": f"ovr-{int(time.time()*1000)}-{kind}",
            "from": "overseer",
            "username": "Overseer",
            "type": "message",
            "content": content,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        ev.update(extra)
        SessionBridge().write("overseer", ev)
    except Exception:
        pass

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_INTERVAL = 30  # seconds
WARM_CAP = 2000
HOT_CAP = 300
COMPACT_THRESHOLD = 0.85
COLD_DISTILL_INTERVAL = 3600  # 1 hour

# Hot-memory thresholds (the actual overflow problem). When hot exceeds:
#   SOFT (100%)        → run _auto_compact() once
#   HARD (200%)        → run /clear on the active CLI session (drop hot to zero)
#   CRITICAL (300%+)   → force /clear every tick until it drops
# Sustained-overflow counter increments when hot > HOT_CAP across consecutive
# ticks — after 5 sustained ticks (>2.5 min) we force /clear even at SOFT
# because auto-compact is failing to free space.
HOT_SOFT_PCT = 1.00
HOT_HARD_PCT = 2.00
HOT_CRITICAL_PCT = 3.00
HOT_SUSTAINED_TICKS_FORCE = 5

# HARD RULE (2026-08-11): no caps. The HOT_CAP/WARM_CAP constants are kept as
# observability targets only — the engine never auto-compacts. The only
# background memory work the overseer does is hot→warm sync (every line that
# lives in hot should also live in warm). Byte thresholds below are advisory
# only — they never trigger /clear or compaction.
HOT_HARD_LIMIT_MB = 500
HOT_WARM_LIMIT_MB = 2000

# Cap tasks dispatched per workflow tick so a 50-task workflow doesn't
# stall the overseer loop for hours. The next tick picks up where this
# left off (depends_on gate).
WORKFLOW_DISPATCH_MAX = 2

# ── Overseer model (LFM2.5-1.2B on llama-server :8082) ──────
# LFM2.5-1.2B has better reasoning than 0.5B for scheduling/minification tasks.
# 1 slot + q4_0 KV + flash-attn + 4096 ctx keeps it ~1.1 GB VRAM.
_tiny = LlamaServer(
    name="tiny",
    model_path=str(CFG.tiny_model),
    port=int(CFG.tiny_model_port),
    ctx=2048,  # matches daemon's lean tiny config (~300 MB, was 640 MB)
    ngl=999,
    alias="cortexagent-tiny",
    extra_args=["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-np", "1", "-t", "4"],
    log_file=str(CFG.logs_dir / "tiny-server.log"),
)

# Vision model removed in v3.x — the big model is multimodal and handles
# vision natively. To re-add a separate vision server, restore this block
# from git history.

# Serializes tiny start/stop so a keepalive thread and a shutdown can't both
# spawn a llama-server on :8082 (port conflict) or race a stop against a start.
_tiny_lock = threading.Lock()
_queue_dispatch_lock = threading.Lock()  # M9 fix: prevent double-dispatch

# ── Clean shutdown flag ──────────────────────────────────────────────────────
# Set by the SIGTERM/SIGINT handler so the daemon loop exits cleanly (exit code 0)
# instead of being signal-killed. A signal-kill would make systemd's
# Restart=on-failure respawn the overseer, which would re-pin the LFM2.5-1.2B model —
# the "memory jumps back up after closing cortexagent" bug.
_SHUTDOWN = False


def _handle_stop_signal(signum, frame):
    """SIGTERM/SIGINT handler: request a clean shutdown (exit 0)."""
    global _SHUTDOWN
    _SHUTDOWN = True


# ── Colors ───────────────────────────────────────────────────────────────────
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{color}{emoji} {BOLD}overseer{RST} {DIM}{color}[{ts}]{RST} {color}{msg}{RST}"
    print(line, file=sys.stderr)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_state() -> Dict:
    return _load_json(STATE_FILE, {
        "last_compact": None,
        "last_distill": None,
        "last_llm_summary": None,
        "health_events": [],
        "started_at": None,
        "total_ticks": 0,
        # Two-layer state (see CLAUDE.md "Two-layer state tracking"):
        #   overseer_state — plain-language activity tag for the tray popout
        #   task_steps     — numbered list of steps the reasoning model is
        #                    currently working through (capped at 7 visible,
        #                    trimmed to current ±1 in the consumer)
        "overseer_state": {"label": "idle", "since": None},
        "task_steps": [],   # [{"id":1, "label":"...", "status":"done|in_progress|pending"}]
        "current_step": None,
    })


def _save_state(state: Dict) -> None:
    _save_json(STATE_FILE, state)


# ── Two-layer state helpers ─────────────────────────────────────────────
# Used by both this overseer and any external caller (the big LLM, the tray
# popout, the webui) to publish what the system is doing in plain language
# and what step it's on. Each helper takes `state` so the caller can keep
# batching its own state changes without a separate write.

def overseer_set_state(state: Dict, label: str) -> None:
    """Publish the overseer's current activity as a plain-language tag.

    Examples: "idle", "watching health checks", "compacting warm memory",
    "distilling warm → cold", "running scheduled task 'nightly backup'",
    "querying tiny LLM", "self-healing (retry #1)".

    The tray popout reads this verbatim — keep it short and human.
    """
    state["overseer_state"] = {"label": label, "since": datetime.now().isoformat()}


def task_steps_publish(state: Dict, steps: List[Dict], current: Optional[int]) -> None:
    """Publish the reasoning model's task step list.

    Args:
        state: the overseer state dict (mutated in place)
        steps: list of {"id": int, "label": str, "status": "pending"|"in_progress"|"done"}
               Limited to 7 entries by the consumer; pass the full list and
               let the consumer trim to current ±1 with an "X of Y" counter.
        current: 1-indexed step that's currently in progress, or None if idle.
    """
    state["task_steps"] = list(steps)
    state["current_step"] = current


# ═══════════════════════════════════════════════════════════════════════════════
#  TINY LLM (LFM2.5-1.2B on llama-server :8082 — no Ollama)
# ═══════════════════════════════════════════════════════════════════════════════

def _preload_tiny_model() -> bool:
    """Start the tiny llama-server and wait for /health (idempotent)."""
    with _tiny_lock:
        _log(f"Starting tiny model on :{_tiny.port} (llama-server)...", "🔄", CYAN)
        if _tiny.start():
            _log(f"Tiny model ready on :{_tiny.port} (pid {_tiny.pid})", "✅", GREEN)
            return True
        _log(f"Failed to start tiny model on :{_tiny.port}", "❌", RED)
        return False


def _keepalive_tiny_model() -> bool:
    """Health-check the tiny server; restart it if it died (self-healing).

    Bounded to 60s of /health polling so a down tiny can't freeze the daemon
    loop for the full 180s startup_timeout. Runs under _tiny_lock so a
    concurrent keepalive/shutdown can't double-spawn on :8082.
    """
    with _tiny_lock:
        if _tiny.is_healthy():
            return True
        _log("Tiny model down — restarting...", "🔄", YELLOW)
        return _tiny.start(timeout=60)


def _query_tiny_llm(prompt: str, system: str = "",
                    max_tokens: int = 256) -> Optional[str]:
    """Query the tiny LLM via llama-server's OpenAI endpoint.

    The overseer is the frame-of-mind gatekeeper for every tiny call:
      1. Wrap whatever system prompt the caller (usually the big LLM via the
         task queue) supplies under a stable practical-reasoning frame so
         tiny always reasons short, operational, no markdown, no hedging —
         even if the caller's own prompt drifted.
      2. Self-heal: if the first call returns None/empty (server hiccup,
         transient HTTP error, malformed JSON), retry once with stricter
         instructions ("answer in plain text, one line, no preamble") before
         giving up. Don't loop — one retry, then surface the failure to the
         caller.
    """
    # Practical-reasoning frame wrapper — the caller's system prompt is
    # appended after so caller-specific instructions still apply, but the
    # operational tone is preserved.
    frame = (
        "You are the CortexAgent overseer's reasoning engine. Plain language, "
        "short answers (one or two lines), no markdown, no emojis, no narration. "
        "State the action taken and the artifact path. If uncertain, say so."
    )
    if system:
        wrapped_system = frame + "\n\n" + system
    else:
        wrapped_system = frame

    # First attempt
    result = tiny_llm.query(prompt, system=wrapped_system, max_tokens=max_tokens)
    if result:
        return result

    # Self-heal: one retry with a stricter framing
    _log("tiny LLM returned empty — retrying once with stricter framing", "🔁", DIM)
    strict = wrapped_system + "\n\nAnswer in plain text, one line, no preamble."
    result = tiny_llm.query(prompt, system=strict, max_tokens=max_tokens)
    return result  # may still be None — caller handles it


# ═══════════════════════════════════════════════════════════════════════════════
#  MEMORY HEALTH (from heartbeat)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_memory_stats() -> Dict:
    """Get current memory counts (NDJSON = file of truth) and byte sizes.

    Adapter over cortexllm.stats.stats (v0.4.0) — returns the legacy shape
    {hot, warm, cold, hot_bytes, warm_bytes} that callers expect, but the
    counts come from the NDJSON files (the file-of-truth per the no-caps
    rule), not from SQLite. SQLite is still queried only for the cold
    category count (cortexllm's stats returns the list of categories).
    """
    out = {"hot": 0, "warm": 0, "cold": 0,
           "hot_bytes": 0, "warm_bytes": 0}
    try:
        from cortexllm.stats import stats as _cl_stats
        from lib.memory_thin import HOT_DIR, WARM_DIR  # noqa: F401
        s = _cl_stats(platform="cortexagent", dir=HOT_DIR.parent)
        plat = s.get("hot", {}).get("by_platform", {}).get("cortexagent", {})
        out["hot"] = plat.get("entries", 0)
        out["hot_bytes"] = plat.get("bytes", 0)
        plat_w = s.get("warm", {}).get("by_platform", {}).get("cortexagent", {})
        out["warm"] = plat_w.get("entries", 0)
        out["warm_bytes"] = plat_w.get("bytes", 0)
        # Cold is category count (1 per category file). cortexllm.stats returns
        # the list; len() is the category count.
        out["cold"] = len(s.get("cold", {}).get("categories", []))
    except Exception:
        # Fallback: SQLite count + NDJSON bytes (the legacy code path).
        try:
            sys.path.insert(0, str(REPO_ROOT))
            from memory.db import db
            reader = db.reader()
            out["hot"] = reader.execute("SELECT COUNT(*) FROM Memory_Hot").fetchone()[0]
            out["warm"] = reader.execute("SELECT COUNT(*) FROM Memory_Warm").fetchone()[0]
            out["cold"] = reader.execute("SELECT COUNT(*) FROM Memory_Cold").fetchone()[0]
        except Exception as e:
            _log(f"Memory stats fallback error: {e}", "⚠️", YELLOW)
        try:
            from lib.memory_thin import HOT_DIR, WARM_DIR
            for p in HOT_DIR.glob("*.jsonl"):
                out["hot_bytes"] += p.stat().st_size
            for p in WARM_DIR.glob("*.warm.jsonl"):
                out["warm_bytes"] += p.stat().st_size
        except (ImportError, OSError):
            pass
    return out


def _check_health(stats: Dict) -> List[str]:
    """Check memory health and return alerts.

    HARD RULE (2026-08-11): no caps. The HOT_CAP/WARM_CAP percentages are
    OBSERVABILITY ONLY — they never trigger compaction or `/clear`. The
    alerts are just informational one-liners the operator can read.
    """
    alerts = []
    if stats["warm"] > WARM_CAP * COMPACT_THRESHOLD:
        pct = int(stats["warm"] / WARM_CAP * 100)
        mb = stats.get("warm_bytes", 0) / (1024 * 1024)
        alerts.append(f"Warm at {pct}% ({stats['warm']} rows, {mb:.1f}MB) — advisory only")
    if stats["hot"] > HOT_CAP * COMPACT_THRESHOLD:
        pct = int(stats["hot"] / HOT_CAP * 100)
        mb = stats.get("hot_bytes", 0) / (1024 * 1024)
        alerts.append(f"Hot at {pct}% ({stats['hot']} rows, {mb:.1f}MB) — advisory only")
    return alerts


def _check_memory_writes() -> List[str]:
    """Verify prompts are being stored. Alert if no recent activity."""
    alerts = []
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from memory.db import db
        reader = db.reader()
        row = reader.execute(
            "SELECT timestamp FROM Memory_Hot ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            ts = row["timestamp"]
            age = (datetime.now() - _fromiso(ts)).total_seconds()
            if age > 300:
                alerts.append(f"No memory writes in {int(age)}s — session may be stalled")
        else:
            alerts.append("Memory is empty — no prompts stored yet")
    except Exception as e:
        alerts.append(f"Memory read error: {e}")
    return alerts


def _check_session_health() -> List[str]:
    """Check if the main model proxy is responding.

    502 from the proxy = proxy is UP but the big model is idle-unloaded — the
    normal no-session state (the daemon loads big on demand), NOT an alert.
    Only a genuinely unreachable proxy (connection refused / 5xx other than 502)
    is a real problem.
    """
    alerts = []
    proxy_port = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/health",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status not in (200, 502):
                alerts.append(f"Proxy health check failed (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        if e.code != 502:  # 502 = backend (big model) idle-unloaded → expected
            alerts.append(f"Proxy health check failed (HTTP {e.code})")
    except Exception:
        alerts.append(f"Proxy not reachable on port {proxy_port} — main model may be down")
    return alerts


# ── Minify stats reader ──────────────────────────────────────────────────────
# The grammar proxy writes a cumulative snapshot to ~/.cortexagent/minify_stats.json
# after every minified request (tmp+rename; same pattern as big_model_steps.json).
# We poll it every tick and surface it under `state["minify"]` plus log a one-line
# delta when the saved-token count climbs — so the savings are visible from
# `overseer status`, the statusline, and the dashboard.
MINIFY_STATS_FILE = STATE_DIR / "minify_stats.json"


def _read_minify_stats() -> Dict:
    """Return the proxy's persisted minify snapshot, or {} on any read error."""
    try:
        with MINIFY_STATS_FILE.open() as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _merge_minify_into_state(state: Dict) -> None:
    """Pull the proxy's minify snapshot into the overseer state under `minify`."""
    snap = _read_minify_stats()
    if not snap:
        return
    prev = state.get("minify") or {}
    prev_tokens_saved = int(prev.get("tokens_saved", 0) or 0)
    state["minify"] = {
        "runs": int(snap.get("runs", 0) or 0),
        "tokens_in": int(snap.get("tokens_in", 0) or 0),
        "tokens_out": int(snap.get("tokens_out", 0) or 0),
        "tokens_saved": int(snap.get("tokens_saved", 0) or 0),
        "ratio_pct": float(snap.get("ratio_pct", 0.0) or 0.0),
        "last_run_ts": float(snap.get("last_run_ts", 0.0) or 0.0),
        "last_saved_pct": float(snap.get("last_saved_pct", 0.0) or 0.0),
        "history_60s": list(snap.get("history_60s") or []),
        "errors": int(snap.get("errors", 0) or 0),
    }
    # Surface a one-line delta in the tick log when the savings climb.
    delta = state["minify"]["tokens_saved"] - prev_tokens_saved
    if delta > 0:
        _log(f"Minify: +{delta} tok saved this tick "
             f"(lifetime {state['minify']['ratio_pct']:.0f}% across "
             f"{state['minify']['runs']} runs)", "📐", DIM)



    """Check if the main model proxy is responding.

    502 from the proxy = proxy is UP but the big model is idle-unloaded — the
    normal no-session state (the daemon loads big on demand), NOT an alert.
    Only a genuinely unreachable proxy (connection refused / 5xx other than 502)
    is a real problem.
    """
    alerts = []
    proxy_port = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/health",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status not in (200, 502):
                alerts.append(f"Proxy health check failed (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        if e.code != 502:  # 502 = backend (big model) idle-unloaded → expected
            alerts.append(f"Proxy health check failed (HTTP {e.code})")
    except Exception:
        alerts.append(f"Proxy not reachable on port {proxy_port} — main model may be down")
    return alerts


# Context-window monitor state (big model KV usage). Reset once below critical.
_CTX_CRITICAL_TICKS = 0
_CTX_ALERT_PCT = 88.0          # warn when the slot is this full
_CTX_CRITICAL_PCT = 95.0       # auto-compact should have fired before here
_CTX_CRITICAL_TICKS_NEEDED = 3  # sustained critical ticks (90s @30s) → failsafe


def _check_context_window() -> List[str]:
    """Monitor the big model's context-window usage (n_past vs n_ctx).

    The user hit hard 400s when the context grew to the server ceiling and
    auto-compact never fired (window misconfig). With the window now matched
    (131072), auto-compact keeps traffic ~95%; this monitor is the failsafe
    that gives visibility near the ceiling and force-resets the session when
    the slot is pegged ≥95% across several ticks (auto-compact clearly dead).
    Returns alerts (does not self-mutate; the loop handles the failsafe).
    """
    global _CTX_CRITICAL_TICKS
    port = CFG.big_model_port
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/slots")
        with urllib.request.urlopen(req, timeout=5) as resp:
            slots = json.loads(resp.read().decode() or "[]")
    except Exception:
        # Big model down/unreachable — session health check covers that.
        _CTX_CRITICAL_TICKS = 0
        return []
    alerts: List[str] = []
    critical = False
    for s in slots:
        n_past = int(s.get("n_past") or 0)
        n_ctx = int(s.get("n_ctx") or 0)
        if n_ctx <= 0 or n_past <= 0:
            continue
        pct = n_past / n_ctx * 100
        if pct >= _CTX_CRITICAL_PCT:
            critical = True
            alerts.append(f"CONTEXT WINDOW at {pct:.0f}% ({n_past}/{n_ctx} tok) — "
                          f"auto-compact failed, ceiling imminent")
        elif pct >= _CTX_ALERT_PCT:
            alerts.append(f"Context window at {pct:.0f}% ({n_past}/{n_ctx} tok) — near ceiling")
    if critical:
        _CTX_CRITICAL_TICKS += 1
    else:
        _CTX_CRITICAL_TICKS = 0
    return alerts


def _context_failsafe() -> None:
    """Force a fresh session when the slot is pegged at the ceiling — the
    auto-compact that should have fired is dead (misconfig or client bug), so
    the next request would hard-400. Reset the session (unloads big) so the
    next launch starts clean instead of failing at the ceiling again."""
    global _CTX_CRITICAL_TICKS
    if _CTX_CRITICAL_TICKS < _CTX_CRITICAL_TICKS_NEEDED:
        return
    _CTX_CRITICAL_TICKS = 0
    _log(f"Context window pegged ≥{_CTX_CRITICAL_PCT:.0f}% for "
         f"{_CTX_CRITICAL_TICKS_NEEDED} ticks — resetting session so the next "
         f"launch starts with fresh context (avoiding a hard 400)", "🔥", RED)
    try:
        control.send_request("session-reset", timeout=5)
    except Exception:
        _log("context failsafe: session-reset failed", "❌", RED)


def _cortexagent_active() -> bool:
    """True if a cortexagent session is running.

    Detects either the cortexagent CLI wrapper (``bin/cortexagent``) or a claude
    process launched by it (has ``--mcp-config`` pointing at the cortexagent
    config). Fail-safe: returns True on any error so we never unload a model we
    can't verify is idle.

    Excludes the checker's own process and its ancestors so a caller whose own
    command line happens to mention ``bin/cortexagent`` (e.g. a test harness)
    can't self-match and suppress the watchdog.
    """
    exclude = set()
    p = os.getpid()
    for _ in range(32):
        exclude.add(p)
        try:
            with open(f"/proc/{p}/stat") as f:
                parts = f.read().split()
            ppid = int(parts[3])
            if ppid == p:
                break
            p = ppid
        except Exception:
            break
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,comm,args"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return True
    for line in out.splitlines():
        # split(None, 2) splits on runs of whitespace — the pid column is
        # right-aligned to the widest pid on the system, so a fixed-width
        # split(" ", 2) yields an empty pid for any process with fewer digits
        # than the widest (e.g. a 4-digit cortexagent pid on a system whose
        # widest pid is 7 digits) and silently skips it — which would make the
        # watchdog unload the big model while cortexagent is actively running.
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid, comm, args = parts
        try:
            if int(pid) in exclude:
                continue
        except ValueError:
            continue
        # cortexagent CLI wrapper (a bash script) or any process whose args
        # reference the wrapper path.
        if "bin/cortexagent" in args:
            return True
        # claude session launched by the wrapper (has --mcp-config → cortexagent).
        if comm in ("claude", "node") and "--mcp-config" in args and "cortexagent" in args:
            return True
    return False


def _watchdog_cortexagent() -> None:
    """If cortexagent is closed but the daemon still tracks an active session,
    reset the session and unload the big model (frees VRAM).

    This is the safety net for the "model stays loaded after killing
    cortexagent" bug: a SIGKILLed CLI never sends ``session-end``, so the
    daemon's refcount stays > 0 and the idle watcher never fires. The overseer
    (always-on systemd service) detects the stale session and forces cleanup.

    Important: a 'closed' CLI must be backed by *no recent daemon activity*
    on the proxy (:8081). Otherwise a webui-only / daemon-managed session
    (no `bin/cortexagent` process running) would be falsely flagged as stale
    and unloaded mid-conversation. We require BOTH signals:
      1. No `bin/cortexagent` / `claude --mcp-config ...cortexagent` process
      2. Daemon `_last_request` older than ``watchdog_stale_sec`` (default 300s)
         OR the daemon reports active_sessions == 0
    """
    if _cortexagent_active():
        return
    # 300s is tighter than daemon's stale_session_sec default (1800s) — the
    # watchdog fires BEFORE the daemon's self-heal so a leaked session is
    # reset sooner. If the daemon has received a proxy request within this
    # window, a session is alive even when we can't see the CLI process
    # (webui, MCP clients, daemons).
    watchdog_stale_sec = 300
    try:
        st = control.send_request("status", timeout=5)
        if not st.get("ok"):
            return
        active = st.get("active_sessions", 0)
        idle = st.get("idle_sec")
        if active == 0:
            return
        if idle is not None and idle < watchdog_stale_sec:
            # Daemon saw a request recently — a client (webui or otherwise) is
            # using the proxy. Do not treat the absence of `bin/cortexagent`
            # as proof of a closed session.
            return
        _log("cortexagent closed AND daemon idle > "
             f"{watchdog_stale_sec}s with active session — "
             "resetting + unloading big model", "🧹", YELLOW)
        control.send_request("session-reset", timeout=5)
    except Exception:
        pass


def _check_db_integrity() -> List[str]:
    """Quick SQLite integrity check."""
    alerts = []
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from memory.db import db
        reader = db.reader()
        row = reader.execute("PRAGMA integrity_check").fetchone()
        if row and row[0] != "ok":
            alerts.append(f"DB integrity: {row[0]}")
    except Exception as e:
        alerts.append(f"DB integrity check failed: {e}")
    return alerts


def _estimate_tokens(stats: Dict) -> str:
    """Rough token estimate: 4 chars per token, ~200 chars per entry.

    Backed by cortexllm.stats.estimate_tokens (v0.4.0) when available —
    same heuristic (4 chars/token, ~200 chars/entry), just routed through
    the public API so we don't drift from the canonical estimator.
    """
    total = stats["hot"] + stats["warm"] + stats["cold"]
    try:
        from cortexllm.stats import estimate_tokens
        est = estimate_tokens("x" * (total * 200))
    except ImportError:
        est = (total * 200) // 4
    if est > 1_000_000:
        return f"{est/1_000_000:.1f}M"
    if est > 1_000:
        return f"{est/1_000:.0f}K"
    return str(est)


def _cold_distill() -> bool:
    """Run cold distillation."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from lib.cold_distiller import ColdDistiller
        d = ColdDistiller(min_confidence=0.3)
        stats = d.run()
        _log(f"Cold distill: scanned={stats['scanned']} extracted={stats['extracted']}", "❄️", CYAN)
        return True
    except Exception as e:
        _log(f"Cold distill failed: {e}", "⚠️", YELLOW)
        return False


def _spawn_subagent(prompt: str, model: str = "sonnet", timeout: int = 600) -> Dict:
    """Spawn a Claude Code subagent via the Task/Agent CLI to handle a delegated
    task. Returns {"ok": bool, "output": str, "error": str}.

    Uses `claude -p <prompt>` in a non-interactive shell so the overseer can
    delegate bounded work (research, sweeps, code edits) without blocking its
    tick loop. Bounded by a timeout; failures fall through to the caller so
    the queue can record them as failed and self-heal (don't loop).
    """
    try:
        # -p / --print = non-interactive (prints response and exits). This is
        # the canonical non-interactive mode for Claude Code. --bare keeps the
        # subagent from re-reading CLAUDE.md / spawning hooks / polluting the
        # parent's auto-memory. --dangerously-skip-permissions so subagents
        # don't stall waiting for the user mid-batch (the user already
        # implicitly authorized the work by queuing it).
        cmd = [
            "claude", "-p", prompt,
            "--model", model,
            "--output-format", "text",
            "--bare",
            "--dangerously-skip-permissions",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode == 0:
            return {"ok": True, "output": proc.stdout, "error": ""}
        return {"ok": False, "output": proc.stdout,
                "error": proc.stderr or f"exit {proc.returncode}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"timeout after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "output": "",
                "error": "claude CLI not found on PATH"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


def _dispatch_workflow(state: Dict) -> int:
    """Walk the current workflow and execute any tasks whose dependencies are
    satisfied. Maps workflow engines to the existing task pipeline:

        LLM_REASONING / LLM_CODE → "subagent" task (Claude Code subagent)
        SYSTEM_EXEC              → "command" task (shell)

    Returns the number of tasks dispatched this call. Runs at most
    `WORKFLOW_DISPATCH_MAX` tasks per tick to avoid blocking the overseer
    loop on a big workflow.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine import WorkflowEngine
        from engine.types import TaskStatus
        from engine.workflow import _load_workflow, _save_workflow  # module-level
        plan_path = WORKFLOW_FILE
        if not plan_path.exists():
            return 0
        plan = _load_workflow()
        if not plan:
            return 0

        # Find ready tasks (PENDING + all deps COMPLETED), priority order.
        completed = {t.id for t in plan.tasks if t.status.name == "COMPLETED"}
        ready = [
            t for t in plan.tasks
            if t.status.name == "PENDING"
            and all(d in completed for d in (t.depends_on or []))
        ]
        ready.sort(key=lambda t: t.priority)
        if not ready:
            return 0

        overseer_set_state(state, f"dispatching workflow ({len(ready)} ready)")
        dispatched = 0
        for task in ready[:WORKFLOW_DISPATCH_MAX]:
            if task.engine.name in ("LLM_REASONING", "LLM_CODE"):
                # Hand to a Claude subagent. Bounded 10-minute timeout per task.
                # Use sonnet for code, opus for reasoning if available.
                model = "opus" if task.engine.name == "LLM_REASONING" else "sonnet"
                # Inherit results of dependencies — feed them into the prompt so
                # the subagent has the context to continue the chain.
                dep_context = ""
                for dep_id in (task.depends_on or []):
                    dep = next((t for t in plan.tasks if t.id == dep_id), None)
                    if dep and dep.result:
                        dep_context += f"\n\n[{dep.name}]\n{dep.result}\n"
                full_prompt = (
                    f"Goal: {plan.goal}\n\nTask: {task.name}\n\n"
                    f"{task.prompt}\n\n{dep_context}\n\n"
                    f"Return only the result — no preamble."
                )
                _log(f"Workflow {task.id} ({task.engine.name}) → subagent ({model})",
                     "🤖", MAGENTA)
                res = _spawn_subagent(full_prompt, model=model, timeout=600)
                if res["ok"]:
                    task.status = TaskStatus.COMPLETED
                    task.result = res["output"][:8000]  # cap stored result
                    _log(f"Workflow {task.id} completed ({len(res['output'])} chars)",
                         "✅", GREEN)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = res["error"][:500]
                    _log(f"Workflow {task.id} failed: {res['error'][:120]}",
                         "❌", RED)
            elif task.engine.name == "SYSTEM_EXEC":
                _log(f"Workflow {task.id} (SYSTEM_EXEC) → shell", "🐚", MAGENTA)
                try:
                    proc = subprocess.run(
                        task.prompt, shell=True, capture_output=True, text=True,
                        timeout=600,
                    )
                    if proc.returncode == 0:
                        task.status = TaskStatus.COMPLETED
                        task.result = (proc.stdout or "")[:8000]
                        _log(f"Workflow {task.id} (exec) completed", "✅", GREEN)
                    else:
                        task.status = TaskStatus.FAILED
                        task.error = (proc.stderr or "")[:500]
                        _log(f"Workflow {task.id} (exec) failed: rc={proc.returncode}",
                             "❌", RED)
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)[:500]
                    _log(f"Workflow {task.id} (exec) crashed: {e}", "❌", RED)
            else:
                _log(f"Workflow {task.id}: unknown engine {task.engine.name}, skipping",
                     "⚠️", YELLOW)
                continue

            dispatched += 1

        if dispatched:
            _save_workflow(plan)  # persist after batch
        return dispatched
    except Exception as e:
        _log(f"Workflow dispatch error: {e}", "⚠️", YELLOW)
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  HOT-MEMORY REMEDIATION (overseer must ACT, not just alert)
# ═══════════════════════════════════════════════════════════════════════════════

# Sustained-overflow counter. Persisted in state["hot_overflow_ticks"] so a
# restart doesn't reset the count and immediately force /clear again.
def _hot_remediation(state: Dict, stats: Dict) -> None:
    """Hot→warm sync + byte-threshold advisories. HARD RULE (2026-08-11):

    The 914% overflow alarm is GONE. There is no auto-compact. There is no
    /clear. Hot grows unbounded; warm mirrors it. The only background work
    we do here is ensuring every hot line is also in warm, and warning the
    operator if byte-size exceeds the soft advisory thresholds.
    """
    hot_bytes = stats.get("hot_bytes", 0)
    warm_bytes = stats.get("warm_bytes", 0)
    sustained = int(state.get("hot_overflow_ticks", 0))

    # 1. Hot→warm sync. Driven by the daemon now (it always mirrors), but we
    #    re-check on every tick in case the daemon was down when a write
    #    happened. Cheap linear scan of the last few entries only.
    _hot_to_warm_sync(state)

    # 2. Byte-threshold advisory only (no /clear, no compact).
    hot_mb = hot_bytes / (1024 * 1024)
    warm_mb = warm_bytes / (1024 * 1024)
    if hot_mb > HOT_HARD_LIMIT_MB or warm_mb > HOT_WARM_LIMIT_MB:
        state["hot_overflow_ticks"] = sustained + 1
        overseer_set_state(
            state,
            f"memory size advisory: hot={hot_mb:.1f}MB warm={warm_mb:.1f}MB "
            f"(advisory only; no action taken per hard rule)"
        )
        if sustained % 30 == 0:  # every 30 ticks (~15 min), log a one-liner
            _log(f"Memory advisory: hot={hot_mb:.1f}MB warm={warm_mb:.1f}MB "
                 f"(no caps, no /clear — this is informational only)", "📊", YELLOW)
    else:
        if sustained:
            state["hot_overflow_ticks"] = 0


def _hot_to_warm_sync(state: Dict) -> None:
    """Mirror hot→warm. The daemon already does this on every write, but we
    re-check on every overseer tick to catch any gaps. We only sync the tail
    (from where warm left off) — older lines are already in warm.
    """
    try:
        from lib.memory_thin import HOT_DIR, WARM_DIR
        for platform in ("cortexagent", "claude", "openclaw_brain", "system"):
            hot_file = HOT_DIR / f"{platform}.jsonl"
            warm_file = WARM_DIR / f"{platform}.warm.jsonl"
            if not hot_file.exists():
                continue
            try:
                hot_size = hot_file.stat().st_size
                warm_size = warm_file.stat().st_size if warm_file.exists() else 0
                if warm_size >= hot_size:
                    continue  # warm is caught up
                # Append the tail of hot to warm (the gap).
                with open(hot_file, "rb") as f:
                    f.seek(max(0, warm_size - 1))  # re-read last byte in case of partial newline
                    gap = f.read()
                if gap:
                    _atomic_append_bytes(warm_file, gap)
            except OSError:
                continue
    except ImportError:
        pass


def _atomic_append_bytes(file_path, data: bytes) -> None:
    """POSIX-atomic append raw bytes. Safe for ≤PIPE_BUF (4096B) per write.

    Drop-in to cortexllm.atomic.atomic_append_bytes (v0.4.0). The local copy
    was a verbatim duplicate; kept as a one-liner shim so callers don't
    change and the import is optional.
    """
    try:
        from cortexllm.atomic import atomic_append_bytes
        atomic_append_bytes(file_path, data)
        return
    except ImportError:
        pass
    import os as _os
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd = _os.open(file_path, _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o644)
    try:
        _os.write(fd, data)
    finally:
        _os.close(fd)


# ═══════════════════════════════════════════════════════════════════════════════
#  TASK QUEUE (from orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_queue() -> List[Dict]:
    return _load_json(QUEUE_FILE, [])


def _save_queue(queue: List[Dict]) -> None:
    _save_json(QUEUE_FILE, queue)


def queue_add(task_type: str, prompt: str = "", command: str = "",
              output: str = "", priority: int = 0) -> Dict:
    queue = _load_queue()
    task = {
        "id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(queue)}",
        "type": task_type,
        "prompt": prompt,
        "command": command,
        "output": output or f"output_{len(queue)}",
        "priority": priority,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "result": None,
    }
    queue.append(task)
    _save_queue(queue)
    _log(f"Queued {task_type} task: {prompt[:60] or command[:60]}", "📋", CYAN)
    return task


def queue_list() -> List[Dict]:
    return _load_queue()


def queue_clear() -> None:
    _save_queue([])
    _log("Queue cleared", "🗑️", YELLOW)


def queue_remove(task_id: str) -> bool:
    queue = _load_queue()
    before = len(queue)
    queue = [t for t in queue if t["id"] != task_id]
    _save_queue(queue)
    if len(queue) < before:
        _log(f"Removed task {task_id}", "🗑️", YELLOW)
        return True
    return False


def _execute_task(task: Dict, state: Optional[Dict] = None) -> bool:
    """Execute a single task. Returns True on success.

    Step-1 refactor: thin wrapper over the tool registry (lib/tool_registry.py).
    The queue/scheduler/state machinery is untouched — this still returns bool
    so the queue's completed/failed bookkeeping is unchanged.

    ``state`` (optional) is the live overseer state dict; the llm branch
    threads it into ``run_react`` so ReAct steps publish to the tray/webui.
    """
    task_type = task.get("type", "command")
    prompt = task.get("prompt", "")
    command = task.get("command", "")
    output = task.get("output", "")

    _log(f"Running {task_type} task...", "▶️", MAGENTA)

    from lib.tool_registry import execute_tool

    if task_type == "command":
        result = execute_tool("run_command", {"command": command})
        if result.get("ok"):
            _log(f"Command succeeded: {command[:60]}", "✅", GREEN)
            return True
        _log(f"Command failed: {(result.get('output') or result.get('error', ''))[:200]}",
             "❌", RED)
        return False

    elif task_type == "llm":
        # ReAct/Socratic loop (step 2) — the tiny model drives tools.
        from lib.react_loop import run_react
        result = run_react(task, state=state)
        if result.get("ok"):
            _log(f"LLM task completed ({len(result.get('output', ''))} chars)",
                 "✅", GREEN)
            return True
        _log(f"LLM task failed: {result.get('error', '')[:120]}", "❌", RED)
        return False

    elif task_type == "subagent":
        # Delegate to a Claude Code subagent (full tool access, model per task).
        # Optional keys: model (default "sonnet"), timeout (default 600s).
        model = task.get("model", "sonnet")
        timeout = int(task.get("timeout", 600))
        result = execute_tool("spawn_subagent", {
            "prompt": prompt,
            "model": model,
            "timeout": timeout,
        })
        if result.get("ok"):
            _log(f"Subagent task completed ({len(result.get('output', ''))} chars)",
                 "✅", GREEN)
            return True
        _log(f"Subagent failed: {result.get('error', '')[:120]}", "❌", RED)
        return False

    elif task_type == "image" or task_type == "video":
        # Route to media pipeline (background model swap)
        tool = "generate_image" if task_type == "image" else "generate_video"
        result = execute_tool(tool, {"prompt": prompt})
        if result.get("ok"):
            _log(f"Media task completed ({task_type})", "✅", GREEN)
            return True
        _log(f"Media task {task_type}: {result.get('error', 'unknown')}",
             "⚠️", YELLOW)
        return False

    elif task_type == "media":
        # Auto-detect: let MediaPipeline decide image vs video vs text
        result = execute_tool("generate_media", {"prompt": prompt})
        if result.get("ok"):
            # Output is "queued media task T-<id> (background)" — extract the
            # task id from the string (the old json.loads always failed here).
            out = result.get("output", "")
            task_id = out
            for tok in out.split():
                if tok.startswith("T-"):
                    task_id = tok
                    break
            _log(f"Media task queued ({task_id})", "✅", GREEN)
            return True
        _log(f"Media task auto: {result.get('error', 'unknown')}",
             "⚠️", YELLOW)
        return False

    return False


def _process_queue(state: Optional[Dict] = None) -> None:
    """Process all queued tasks sequentially.

    M9 fix (2026-08-11): guarded by ``_queue_dispatch_lock`` so a second
    caller (e.g. a scheduled task triggering during an in-progress dispatch)
    can't double-dispatch the same queued item. Without this, overlapping
    threads both see ``status="queued"`` and both invoke ``_execute_task``.

    ``state`` (optional) is the live overseer state dict threaded from the
    tick loop; it is passed to ``_execute_task`` so ReAct steps publish live.
    """
    if not _queue_dispatch_lock.acquire(blocking=False):
        # Another dispatch is in progress; let it finish and the next tick
        # will pick up whatever remains.
        return
    try:
        queue = _load_queue()
        pending = [t for t in queue if t["status"] == "queued"]
        if not pending:
            return

        _log(f"Processing {len(pending)} queued tasks...", "▶️", MAGENTA)
        _bridge_emit("queue", f"▶️ Processing {len(pending)} queued task(s)")

        for task in pending:
            task["status"] = "running"
            task["started_at"] = datetime.now().isoformat()
            _save_queue(queue)
            _bridge_emit(
                "task_start",
                f"▶️ Task {task['id']} ({task['type']}) starting — {task.get('prompt') or task.get('command','')[:120]}",
                task_id=task["id"],
                task_type=task["type"],
            )

            try:
                success = _execute_task(task, state)
            except Exception as e:
                # A crash in _execute_task (e.g. MediaPipeline raising) must not
                # leave the task stuck in "running" forever — mark it failed.
                _log(f"Task {task['id']} crashed: {e}", "❌", RED)
                _bridge_emit("task_crash", f"❌ Task {task['id']} crashed: {e}",
                             task_id=task["id"])
                success = False

            task["status"] = "completed" if success else "failed"
            task["completed_at"] = datetime.now().isoformat()
            task["result"] = "success" if success else "failed"
            _save_queue(queue)

            if success:
                _log(f"Task {task['id']} completed", "✅", GREEN)
                _bridge_emit("task_done", f"✅ Task {task['id']} completed",
                             task_id=task["id"])
            else:
                _log(f"Task {task['id']} failed", "❌", RED)
                _bridge_emit("task_fail", f"❌ Task {task['id']} failed",
                             task_id=task["id"])
    finally:
        _queue_dispatch_lock.release()


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEDULER (from orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_schedule() -> List[Dict]:
    return _load_json(SCHEDULE_FILE, [])


def _save_schedule(schedule: List[Dict]) -> None:
    _save_json(SCHEDULE_FILE, schedule)


def _cron_matches(expr: str, now: datetime) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, mon, dow = fields
    # cron dow is 0=Sunday..6=Saturday; Python weekday() is 0=Monday..6=Sunday.
    cron_dow = (now.weekday() + 1) % 7
    values = [now.minute, now.hour, now.day, now.month, cron_dow]
    for fld, val in zip([minute, hour, dom, mon, dow], values):
        if fld == "*":
            continue
        if "," in fld:
            opts = [int(x) for x in fld.split(",")]
            if val not in opts:
                return False
        elif "/" in fld:
            base, step = fld.split("/")
            start = 0 if base == "*" else int(base)
            if val < start or (val - start) % int(step) != 0:
                return False
        elif "-" in fld:
            lo, hi = [int(x) for x in fld.split("-")]
            if val < lo or val > hi:
                return False
        else:
            if int(fld) != val:
                return False
    return True


def schedule_add(name: str, task_type: str, schedule_type: str,
                 schedule_value: str, prompt: str = "", command: str = "",
                 output: str = "", system: str = "") -> Dict:
    schedule = _load_schedule()
    entry = {
        "name": name,
        "type": task_type,
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "prompt": prompt,
        "command": command,
        "output": output,
        "system": system,
        "enabled": True,
        "last_run": None,
        "created_at": datetime.now().isoformat(),
    }
    schedule = [s for s in schedule if s.get("name") != name]
    schedule.append(entry)
    _save_schedule(schedule)
    _log(f"Scheduled '{name}' ({schedule_type}: {schedule_value})", "📅", CYAN)
    return entry


def schedule_list() -> List[Dict]:
    return _load_schedule()


def schedule_remove(name: str) -> bool:
    schedule = _load_schedule()
    before = len(schedule)
    schedule = [s for s in schedule if s["name"] != name]
    _save_schedule(schedule)
    if len(schedule) < before:
        _log(f"Removed schedule '{name}'", "🗑️", YELLOW)
        return True
    return False


def _check_schedule() -> None:
    """Check scheduled tasks and queue any that are due."""
    now = datetime.now()
    schedule = _load_schedule()

    for entry in schedule:
        if not entry.get("enabled", True):
            continue

        # Dedup: the loop runs every 30s, so a cron/daily/weekly job whose
        # minute matches would otherwise fire twice in the same minute. Skip if
        # this job already ran in the current minute.
        last_run = entry.get("last_run")
        if last_run:
            try:
                if _fromiso(last_run).strftime("%Y%m%d%H%M") == now.strftime("%Y%m%d%H%M"):
                    continue
            except Exception:
                pass

        should_run = False
        st = entry["schedule_type"]
        sv = entry["schedule_value"]

        if st == "cron":
            should_run = _cron_matches(sv, now)
        elif st == "daily":
            parts = sv.split(":")
            target_hour = int(parts[0])
            target_min = int(parts[1]) if len(parts) > 1 else 0
            should_run = (now.hour == target_hour and now.minute == target_min)
        elif st == "weekly":
            parts = sv.split(":")
            days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_day = days.get(parts[0].lower(), -1)
            target_hour = int(parts[1]) if len(parts) > 1 else 0
            target_min = int(parts[2]) if len(parts) > 2 else 0
            should_run = (now.weekday() == target_day and
                         now.hour == target_hour and now.minute == target_min)
        elif st == "date":
            try:
                target = _fromiso(sv)
                should_run = (now >= target and
                              (entry.get("last_run") is None or
                               _fromiso(entry["last_run"]) < target))
            except Exception:
                pass

        if should_run:
            task = {
                "type": entry["type"],
                "prompt": entry.get("prompt", ""),
                "command": entry.get("command", ""),
                "output": entry.get("output", ""),
                "system": entry.get("system", ""),
            }
            queue_add(task["type"], task["prompt"], task["command"], task["output"])
            entry["last_run"] = now.isoformat()
            _save_schedule(schedule)
            _log(f"Scheduled task '{entry['name']}' queued", "📅", GREEN)
            _bridge_emit(
                "schedule_fired",
                f"📅 Scheduled task '{entry['name']}' queued ({task['type']})",
                schedule_name=entry["name"],
                task_type=task["type"],
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAN TRACKING
#  (Post-cortexllm v0.4.0: thin shim over cortexllm.plan.Plan. The Plan class
#  stores the dict shape verbatim — name/total_steps/current_step/context/
#  steps/step_status/started_at/updated_at/completed — so callers don't
#  change. Local copy only kept for the log lines + the pre-existing caller
#  signature of plan_set(name, total_steps, context, steps) which is
#  DIFFERENT from cortexllm.plan.Plan.set(name, total_steps, steps, context)
#  (note the swapped last two args). The shim fixes the order.)
# ═══════════════════════════════════════════════════════════════════════════════

def _plan():
    """Lazy singleton for the cortexllm plan backing store."""
    try:
        from cortexllm.plan import Plan as _Plan
        return _Plan(dir=str(STATE_DIR), name="overseer_plan")
    except ImportError:
        return None


def plan_set(name: str, total_steps: int, context: str = "",
             steps: Optional[List[str]] = None) -> Dict:
    """Set or update the current plan.

    Note: parameter order is `(name, total_steps, context, steps)` — fixed
    from the pre-2026-08-11 bug where cortexllm's order is
    `(name, total_steps, steps, context)`. The shim swaps before calling.
    """
    plan = _plan()
    if plan is not None:
        # cortexllm.plan.Plan.set signature: (name, total_steps, steps, context)
        result = plan.set(name=name, total_steps=total_steps,
                          steps=steps, context=context)
        _log(f"Plan set: '{name}' ({total_steps} steps)", "📋", CYAN)
        return result
    # Fallback (cortexllm missing): local copy.
    local = {
        "name": name,
        "total_steps": total_steps,
        "current_step": 0,
        "context": context,
        "steps": steps or [f"Step {i+1}" for i in range(total_steps)],
        "step_status": ["pending"] * total_steps,
        "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "completed": False,
    }
    _save_json(PLAN_FILE, local)
    _log(f"Plan set: '{name}' ({total_steps} steps)", "📋", CYAN)
    return local


def plan_step(n: Optional[int] = None) -> Dict:
    """Advance to step N, or next step if N is None."""
    plan = _plan()
    if plan is not None:
        result = plan.advance(n=n)
        if "error" in result:
            return result
        if result.get("completed"):
            _log(f"Plan '{result['name']}' completed!", "🎉", GREEN)
        else:
            _log(f"Step {result['current_step']}/{result['total_steps']}: "
                 f"{result['steps'][result['current_step']-1]}", "➡️", CYAN)
        return result
    # Fallback (cortexllm missing): local copy.
    data = _load_json(PLAN_FILE)
    if not data:
        return {"error": "No plan set. Use plan-set first."}
    if data.get("completed"):
        return {"error": "Plan already completed."}
    if n is not None:
        if n < 1 or n > data["total_steps"]:
            return {"error": f"Step {n} out of range (1-{data['total_steps']})"}
        data["current_step"] = n
    else:
        data["current_step"] += 1
    if data["current_step"] > data["total_steps"]:
        data["completed"] = True
        data["current_step"] = data["total_steps"]
        data["updated_at"] = datetime.now().isoformat()
        _save_json(PLAN_FILE, data)
        _log(f"Plan '{data['name']}' completed!", "🎉", GREEN)
        return data
    data["step_status"][data["current_step"] - 1] = "in_progress"
    data["updated_at"] = datetime.now().isoformat()
    _save_json(PLAN_FILE, data)
    _log(f"Step {data['current_step']}/{data['total_steps']}: "
         f"{data['steps'][data['current_step']-1]}", "➡️", CYAN)
    return data


def plan_status() -> Dict:
    """Get current plan status."""
    plan = _plan()
    if plan is not None:
        return plan.status()
    data = _load_json(PLAN_FILE)
    if not data:
        return {"error": "No plan set. Use plan-set first."}
    return data


def plan_complete() -> Dict:
    """Mark the current plan as completed."""
    plan = _plan()
    if plan is not None:
        result = plan.complete()
        if "error" not in result:
            _log(f"Plan '{result['name']}' marked complete", "🎉", GREEN)
        return result
    data = _load_json(PLAN_FILE)
    if not data:
        return {"error": "No plan set."}
    data["completed"] = True
    data["updated_at"] = datetime.now().isoformat()
    _save_json(PLAN_FILE, data)
    _log(f"Plan '{data['name']}' marked complete", "🎉", GREEN)
    return data


# ═══════════════════════════════════════════════════════════════════════════════
#  DAEMON LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def _daemon_loop(interval: int) -> None:
    """Main overseer loop: health checks, schedule, queue, LLM keepalive."""
    # Register clean-shutdown handlers so SIGTERM/SIGINT exit 0 (not signal-kill).
    # This prevents systemd Restart=on-failure from respawning us and re-pinning
    # the LFM2.5-1.2B model after cortexagent closes.
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)

    _log(f"Overseer daemon started (interval: {interval}s, tiny: :{_tiny.port})", "🚀", CYAN)

    state = _load_state()
    state["started_at"] = datetime.now().isoformat()
    _save_state(state)

    # Start the tiny LFM2.5-1.2B llama-server (replaces Ollama preload)
    has_llm = _preload_tiny_model()

    tick = 0
    while not _SHUTDOWN:
        try:
            tick += 1
            state["total_ticks"] = tick
            now = datetime.now().strftime("%H:%M:%S")
            _log(f"── Tick {tick} @ {now} ─────────────────────", "⏱️", DIM)

            # Publish the tick's step list (5-7 visible, current ±1). The tray
            # popout and webui read this verbatim — keep labels short.
            task_steps_publish(state, [
                {"id": 1, "label": "Memory health checks",       "status": "in_progress"},
                {"id": 2, "label": "Watchdog (every 2nd tick)",  "status": "pending"},
                {"id": 3, "label": "Minify stats merge",         "status": "pending"},
                {"id": 4, "label": "Schedule + queue dispatch",  "status": "pending"},
                {"id": 5, "label": "LLM health summary",         "status": "pending"},
            ], current=1)

            # ── Health checks ──
            overseer_set_state(state, "watching memory health")
            stats = _get_memory_stats()
            _log(f"Memory: {stats['hot']}H / {stats['warm']}W / {stats['cold']}C", "📊", DIM)
            alerts = _check_health(stats)
            alerts += _check_memory_writes()
            alerts += _check_session_health()
            # Context-window monitor: alert near the ceiling; failsafe-reset on
            # sustained critical (auto-compact dead → the 400-class bug).
            ctx_alerts = _check_context_window()
            alerts += ctx_alerts
            _context_failsafe()
            if ctx_alerts:
                _log("Context: " + " | ".join(ctx_alerts), "📏", YELLOW)

            # ── CortexAgent watchdog (every 2nd tick) ──
            # If cortexagent is closed but the daemon still tracks an active
            # session, reset + unload the big model so VRAM is freed.
            if tick % 2 == 0:
                overseer_set_state(state, "watchdogging cortexagent session")
                _watchdog_cortexagent()

            # ── Minify stats (proxy writes to ~/.cortexagent/minify_stats.json) ──
            # Pull the cumulative snapshot, surface a delta log line, and merge
            # into state for the dashboard / statusline / CLI to read.
            overseer_set_state(state, "merging minify stats")
            _merge_minify_into_state(state)

            # DB integrity every 10th tick
            if tick % 10 == 0:
                alerts += _check_db_integrity()

            if alerts:
                for alert in alerts:
                    _log(f"ALERT: {alert}", "🔴", RED)
                state["health_events"].append({
                    "time": datetime.now().isoformat(),
                    "alerts": alerts,
                })
                state["health_events"] = state["health_events"][-100:]

                # Auto-compact gate — HARD RULE (2026-08-11): no auto-compact.
                # The legacy threshold is kept as observation only; we never
                # compact automatically. Warm grows unbounded.
                if stats["warm"] > WARM_CAP * COMPACT_THRESHOLD:
                    overseer_set_state(
                        state,
                        f"warm at {int(stats['warm']/WARM_CAP*100)}% (advisory only; "
                        f"no auto-compact per hard rule)"
                    )

            # Hot-memory remediation — hot→warm sync + byte-threshold advisory.
            # The 914% alarm is GONE. There is no /clear. Hot grows unbounded.
            _hot_remediation(state, stats)

            # ── Cold distill (hourly) ──
            last_distill = state.get("last_distill")
            if stats["warm"] > 100 and (
                not last_distill or
                (datetime.now() - _fromiso(last_distill)).total_seconds() > COLD_DISTILL_INTERVAL
            ):
                overseer_set_state(state, "distilling warm → cold")
                _cold_distill()
                state["last_distill"] = datetime.now().isoformat()

            # ── Schedule check ──
            overseer_set_state(state, "checking schedule + queue")
            sched_count = len(_load_schedule())
            _log(f"Schedule: {sched_count} entries", "📅", DIM)
            _check_schedule()
            # ── Process queue ──
            q = _load_queue()
            pending = len([t for t in q if t["status"] == "queued"])
            if pending:
                _log(f"Queue: {pending} pending tasks", "📦", DIM)
            _process_queue(state)

            # ── Workflow engine check + dispatch ──
            try:
                sys.path.insert(0, str(REPO_ROOT))
                from engine import WorkflowEngine
                wf = WorkflowEngine()
                wf_status = wf.get_status()
                if wf_status.get("status") == "in_progress":
                    pending_wf = wf_status.get("pending", 0)
                    running_wf = wf_status.get("running", 0)
                    if pending_wf > 0 or running_wf > 0:
                        _log(f"Workflow: {pending_wf} pending, {running_wf} running", "⚙️", DIM)
                # Actually dispatch ready tasks (depends_on gate).
                # The original loop only read status — workflows stayed
                # "pending" forever. Now the dispatcher walks the DAG and
                # executes any task whose deps are COMPLETED.
                # Run in a daemon thread so a 10-minute subagent invocation
                # doesn't block the next tick (queue, health, watchdog).
                if wf_status.get("pending", 0) > 0:
                    threading.Thread(
                        target=_dispatch_workflow, args=(state,),
                        daemon=True,
                    ).start()
            except Exception:
                pass

            # ── LLM keepalive (every 5th tick) ──
            # Always run (not gated on the boot-time has_llm): if the tiny
            # failed to start at boot, the keepalive is the only thing that can
            # recover it. Runs in a thread so a down tiny (up to 60s of /health
            # polling) can't freeze the watchdog / health checks / scheduler.
            if tick % 5 == 0:
                threading.Thread(target=_keepalive_tiny_model, daemon=True).start()

            # ── LLM health summary (every 10th tick) ──
            if has_llm and tick % 10 == 0:
                overseer_set_state(state, "querying tiny LLM for health summary")
                prompt = (
                    f"Memory: {stats['hot']}H/{stats['warm']}W/{stats['cold']}C. "
                    f"Alerts: {len(alerts)}. Ticks: {tick}. "
                    "Is the system healthy? One short sentence."
                )
                summary = _query_tiny_llm(prompt, "You are a system monitor. Be concise.", 64)
                if summary:
                    _log(f"LLM health: {summary}", "💬", DIM)
                    state["last_llm_summary"] = summary

            # ── Log memory estimate ──
            if tick % 5 == 0:
                est = _estimate_tokens(stats)
                _log(f"Memory: {stats['hot']}H/{stats['warm']}W/{stats['cold']}C (~{est} tok)  "
                     f"Alerts: {len(alerts)}  Ticks: {tick}", "📊", DIM)

            # Reset state for the next tick's readers
            overseer_set_state(state, "idle")
            task_steps_publish(state, [], None)
            _save_state(state)

        except Exception as e:
            _log(f"Daemon error: {e}", "❌", RED)

        # Interruptible sleep: poll the shutdown flag every 1s so a SIGTERM is
        # noticed within ~1s instead of waiting up to `interval` seconds.
        for _ in range(interval):
            if _SHUTDOWN:
                break
            time.sleep(1)

    # ── Clean shutdown: unload the LFM2.5-1.2B so the llama-server frees VRAM, then exit 0 ──
    _log("Overseer shutting down — unloading tiny model...", "🛑", YELLOW)
    _unload_tiny_model()
    state = _load_state()
    state["stopped_at"] = datetime.now().isoformat()
    _save_state(state)
    PID_FILE.unlink(missing_ok=True)
    _log("Overseer stopped cleanly (exit 0)", "✅", GREEN)
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════════════════════
#  DAEMON LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════

def _is_running() -> Optional[int]:
    """Check if daemon is running. Returns PID or None."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _start(interval: int) -> None:
    """Start the overseer daemon."""
    pid = _is_running()
    if pid:
        print(f"Overseer already running (pid {pid})")
        return

    pid = os.fork()
    if pid > 0:
        # Parent
        PID_FILE.write_text(str(pid))
        print(f"Overseer started (pid {pid})")
        return

    # Child — become session leader
    os.setsid()
    # Redirect all stdio to /dev/null. stderr MUST be redirected too: if the
    # daemon inherits the parent's stderr pipe, the parent's exit closes the
    # read end and the daemon's next _log() print to stderr raises SIGPIPE and
    # kills it. The log file (written by _log) is the source of truth — monitor
    # with: tail -f ~/.cortexagent/logs/overseer.log
    with open(os.devnull, 'w') as null:
        os.dup2(null.fileno(), 0)
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)
    _daemon_loop(interval)


def _unload_tiny_model() -> bool:
    """Stop the tiny llama-server to free VRAM.

    In daemon mode the persistent daemon owns the tiny model — we must NOT stop
    it here (the daemon keeps it up for the next session). The daemon will tear
    it down on its own shutdown.
    """
    if control.daemon_present():
        _log("Daemon present — leaving tiny model to the daemon (not stopping)", "🛡️", DIM)
        return True
    with _tiny_lock:
        if _tiny.stop():
            _log(f"Tiny model stopped on :{_tiny.port} — VRAM freed", "💤", DIM)
            return True
        return False


def _stop() -> None:
    """Stop the overseer daemon and stop the tiny llama-server.

    Order matters: SIGTERM the daemon FIRST so it can no longer issue keepalive
    ticks that would restart the LFM2.5-1.2B. The daemon's clean handler stops the
    tiny server itself and exits 0. We then stop again as a backup so VRAM is
    freed even if the daemon was already dead or failed to stop it.
    Exiting 0 (not signal-killed) keeps systemd Restart=on-failure from
    respawning us and re-loading the LFM2.5-1.2B after cortexagent closes.
    """
    pid = _is_running()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 45s for a clean exit (daemon exits within ~2s normally;
            # margin covers a mid-tick LLM query, which can take up to 30s).
            # SIGKILLing a mid-query daemon would make systemd Restart=on-failure
            # respawn it and re-pin the LFM2.5-1.2B — the exact bug clean exit 0 avoids.
            exited = False
            for _ in range(450):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    exited = True
                    break
            if not exited:
                # Last resort: SIGKILL. (May cause systemd restart, but a stuck
                # daemon is worse. The clean handler should make this unreachable.)
                os.kill(pid, signal.SIGKILL)
                PID_FILE.unlink(missing_ok=True)
                print(f"Overseer force-killed (pid {pid})")
            else:
                print(f"Overseer stopped cleanly (pid {pid})")
        except Exception as e:
            print(f"Error stopping overseer: {e}")
    else:
        print("Overseer not running")
        PID_FILE.unlink(missing_ok=True)

    # Backup stop: stop the tiny llama-server regardless of daemon state.
    if _unload_tiny_model():
        print(f"Tiny model stopped on :{_tiny.port} — VRAM freed")
    else:
        print(f"Tiny model on :{_tiny.port} may already be stopped")


def _status() -> None:
    """Show overseer status."""
    pid = _is_running()
    if pid:
        state = _load_state()
        plan = _load_json(PLAN_FILE)
        queue = _load_queue()
        schedule = _load_schedule()

        print(f"Overseer: RUNNING (pid {pid})")
        print(f"  Started: {state.get('started_at', 'unknown')}")
        print(f"  Ticks: {state['total_ticks']}")
        print(f"  Model: tiny LFM2.5-1.2B on :{_tiny.port} ({'up' if _tiny.is_healthy() else 'down'})")

        stats = _get_memory_stats()
        print(f"  Memory: {stats['hot']}H / {stats['warm']}W / {stats['cold']}C")
        print(f"  Last compact: {state.get('last_compact', 'never')}")
        print(f"  Last distill: {state.get('last_distill', 'never')}")

        pending = len([t for t in queue if t["status"] == "queued"])
        print(f"  Queue: {len(queue)} total ({pending} pending)")
        print(f"  Schedule: {len(schedule)} entries")

        # Minify savings — surfacing in `overseer status` makes it visible at
        # the CLI without the user opening the dashboard.
        m = state.get("minify") or _read_minify_stats()
        if m and m.get("runs", 0):
            print(f"  Minify: {m['tokens_saved']:,} tok saved "
                  f"({m['ratio_pct']:.0f}%) across {m['runs']} runs")
        else:
            print(f"  Minify: no runs yet")

        if plan and "error" not in plan:
            step = plan.get("current_step", 0)
            total = plan.get("total_steps", 0)
            name = plan.get("name", "?")
            done = "✅" if plan.get("completed") else "➡️"
            print(f"  Plan: {done} '{name}' — step {step}/{total}")
    else:
        print("Overseer: STOPPED")


def _smoke() -> int:
    """Smoke test — verify all subsystems."""
    print(f"{BOLD}Overseer Smoke Test{RST}")
    print(f"{'─'*50}")

    # 1. Tiny model (start llama-server on :8082)
    has = _preload_tiny_model()
    print(f"  Tiny LLM (:{_tiny.port}): {'✅' if has else '❌'} ready")

    # 2. Memory
    stats = _get_memory_stats()
    print(f"  Memory DB: {stats['hot']}H / {stats['warm']}W / {stats['cold']}C")

    # 3. Health checks
    alerts = _check_health(stats)
    print(f"  Capacity: {'✅' if not alerts else '⚠️ ' + ', '.join(alerts)}")
    write_alerts = _check_memory_writes()
    print(f"  Writes: {'✅' if not write_alerts else '⚠️ ' + ', '.join(write_alerts)}")
    session_alerts = _check_session_health()
    print(f"  Session: {'✅' if not session_alerts else '⚠️ ' + ', '.join(session_alerts)}")
    db_alerts = _check_db_integrity()
    print(f"  DB: {'✅' if not db_alerts else '⚠️ ' + ', '.join(db_alerts)}")

    # 4. Plan tracking — back up any real plan first so the smoke test can't
    #    destroy the user's active plan (it would otherwise overwrite PLAN_FILE
    #    and then unlink it).
    saved_plan = None
    if PLAN_FILE.exists():
        try:
            saved_plan = PLAN_FILE.read_text()
        except Exception:
            pass
    plan_set("smoke-test", 3, "Testing plan tracking")
    plan_step(1)
    plan_step(2)
    plan_step(3)
    plan_step()  # advance past end to trigger completion
    p = plan_status()
    done = p.get("completed", False)
    print(f"  Plan tracking: {'✅' if done else '❌'}")

    # 5. Queue
    queue_add("command", command="echo 'overseer smoke test'")
    q = queue_list()
    print(f"  Queue: {'✅' if len(q) > 0 else '❌'} ({len(q)} tasks)")
    queue_clear()

    # 6. Schedule
    schedule_add("smoke-test-sched", "command", "cron", "0 9 * * *", command="echo test")
    s = schedule_list()
    print(f"  Schedule: {'✅' if len(s) > 0 else '❌'} ({len(s)} entries)")
    schedule_remove("smoke-test-sched")

    # Restore the user's plan (or remove the smoke-test plan if none existed)
    if saved_plan is not None:
        try:
            PLAN_FILE.write_text(saved_plan)
        except Exception:
            pass
    elif PLAN_FILE.exists():
        PLAN_FILE.unlink()

    print(f"{'─'*50}")
    print(f"Overseer smoke: {'✅ ALL PASS' if has else '⚠️  Tiny LLM missing'}")
    return 0 if has else 1


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _minify_status_cli(args: List[str]) -> None:
    """Print live minify stats from the proxy snapshot. No daemon needed."""
    snap = _read_minify_stats()
    if not snap:
        print("Minify: no data yet (proxy hasn't served a minified request)")
        return
    runs = int(snap.get("runs", 0) or 0)
    print(f"  Minify: {runs} run(s)")
    print(f"    tokens in:    {int(snap.get('tokens_in', 0) or 0):,}")
    print(f"    tokens out:   {int(snap.get('tokens_out', 0) or 0):,}")
    saved = int(snap.get("tokens_saved", 0) or 0)
    ratio = float(snap.get("ratio_pct", 0.0) or 0.0)
    print(f"    tokens saved: {saved:,}  ({ratio:.1f}%)")
    print(f"    last run:     {float(snap.get('last_saved_pct', 0.0) or 0.0):.1f}% saved "
          f"@ {snap.get('last_run_ts', 0)}")
    history = snap.get("history_60s") or []
    if history:
        if history:
            last = history[-1]
            pct = f"{last[1]:.1f}% saved" if isinstance(last, (list, tuple)) and len(last) >= 2 else "n/a"
        else:
            pct = "n/a"
        print(f"    60s samples:  {len(history)} (last {pct})")


def _parse_interval(args: List[str]) -> int:
    for i, arg in enumerate(args):
        if arg == "--interval" and i + 1 < len(args):
            return int(args[i + 1])
    return DEFAULT_INTERVAL


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    # ── Daemon lifecycle ──
    if cmd == "start":
        interval = _parse_interval(sys.argv[2:])
        _start(interval)
        return 0
    elif cmd == "stop":
        _stop()
        return 0
    elif cmd == "status":
        _status()
        return 0
    elif cmd == "minify":
        _minify_status_cli(sys.argv[2:])
        return 0
    elif cmd == "smoke":
        return _smoke()

    # ── Plan tracking ──
    elif cmd == "plan-set":
        if len(sys.argv) < 3:
            print("Usage: overseer.py plan-set <name> [--steps N] [--context ...]")
            return 1
        name = sys.argv[2]
        steps = 1
        context = ""
        step_names = None
        for i, arg in enumerate(sys.argv[3:], 3):
            if arg == "--steps" and i + 1 < len(sys.argv):
                steps = int(sys.argv[i + 1])
            elif arg == "--context" and i + 1 < len(sys.argv):
                context = sys.argv[i + 1]
        result = plan_set(name, steps, context, step_names)
        print(json.dumps(result, indent=2))
        return 0

    elif cmd == "plan-step":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else None
        result = plan_step(n)
        print(json.dumps(result, indent=2))
        return 0

    elif cmd == "plan-status":
        result = plan_status()
        print(json.dumps(result, indent=2))
        return 0

    elif cmd == "plan-complete":
        result = plan_complete()
        print(json.dumps(result, indent=2))
        return 0

    # ── Queue ──
    elif cmd == "queue":
        if len(sys.argv) < 3:
            print("Usage: overseer.py queue <add|list|clear|remove> ...")
            return 1
        sub = sys.argv[2]
        if sub == "add":
            task_type = "command"
            prompt = ""
            command = ""
            output = ""
            for i, arg in enumerate(sys.argv[3:], 3):
                if arg == "--type" and i + 1 < len(sys.argv):
                    task_type = sys.argv[i + 1]
                elif arg == "--prompt" and i + 1 < len(sys.argv):
                    prompt = sys.argv[i + 1]
                elif arg == "--command" and i + 1 < len(sys.argv):
                    command = sys.argv[i + 1]
                elif arg == "--output" and i + 1 < len(sys.argv):
                    output = sys.argv[i + 1]
            result = queue_add(task_type, prompt, command, output)
            print(json.dumps(result, indent=2))
        elif sub == "list":
            for t in queue_list():
                print(f"  [{t['status']}] {t['type']}: {t.get('prompt','')[:60] or t.get('command','')[:60]}")
        elif sub == "clear":
            queue_clear()
            print("Queue cleared")
        elif sub == "remove":
            tid = sys.argv[3] if len(sys.argv) > 3 else ""
            if queue_remove(tid):
                print(f"Removed task {tid}")
            else:
                print(f"Task {tid} not found")
        return 0

    # ── Schedule ──
    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: overseer.py schedule <add|list|remove> ...")
            return 1
        sub = sys.argv[2]
        if sub == "add":
            name = ""
            task_type = "command"
            sched_type = ""
            sched_val = ""
            prompt = ""
            command = ""
            for i, arg in enumerate(sys.argv[3:], 3):
                if arg == "--name" and i + 1 < len(sys.argv):
                    name = sys.argv[i + 1]
                elif arg == "--type" and i + 1 < len(sys.argv):
                    task_type = sys.argv[i + 1]
                elif arg == "--cron" and i + 1 < len(sys.argv):
                    sched_type = "cron"
                    sched_val = sys.argv[i + 1]
                elif arg == "--daily" and i + 1 < len(sys.argv):
                    sched_type = "daily"
                    sched_val = sys.argv[i + 1]
                elif arg == "--weekly" and i + 1 < len(sys.argv):
                    sched_type = "weekly"
                    sched_val = sys.argv[i + 1]
                elif arg == "--date" and i + 1 < len(sys.argv):
                    sched_type = "date"
                    sched_val = sys.argv[i + 1]
                elif arg == "--prompt" and i + 1 < len(sys.argv):
                    prompt = sys.argv[i + 1]
                elif arg == "--command" and i + 1 < len(sys.argv):
                    command = sys.argv[i + 1]
            if not name or not sched_type:
                print("Error: --name and --cron/--daily/--weekly/--date required")
                return 1
            result = schedule_add(name, task_type, sched_type, sched_val, prompt, command)
            print(json.dumps(result, indent=2))
        elif sub == "list":
            for s in schedule_list():
                on_off = "ON" if s.get("enabled", True) else "OFF"
                print(f"  [{on_off}] {s['name']}: {s['schedule_type']} {s['schedule_value']}")
        elif sub == "remove":
            name = sys.argv[3] if len(sys.argv) > 3 else ""
            if schedule_remove(name):
                print(f"Removed schedule '{name}'")
            else:
                print(f"Schedule '{name}' not found")
        return 0

    # ── Workflow ──
    elif cmd == "workflow":
        if len(sys.argv) < 3:
            print("Usage: overseer.py workflow <run|status|list|clear> ...")
            return 1
        sub = sys.argv[2]
        try:
            sys.path.insert(0, str(REPO_ROOT))
            from engine import WorkflowEngine
            wf = WorkflowEngine()
        except Exception as e:
            print(f"Workflow engine not available: {e}")
            return 1

        if sub == "run":
            prompt = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "generic task"
            print(f"Running workflow: {prompt}")
            result = wf.run(prompt)
            print(json.dumps(result, indent=2))
        elif sub == "status":
            status = wf.get_status()
            s = status.get("status", "unknown")
            if s == "no_workflow":
                print("No workflow has been run yet")
            else:
                print(f"Goal: {status['goal']}")
                print(f"Tasks: {status['total_tasks']} total, {status['completed']} completed, "
                      f"{status.get('failed', 0)} failed, {status.get('pending', 0)} pending")
                for t in status.get("tasks", []):
                    icon = {"COMPLETED": "✅", "RUNNING": "🔄", "FAILED": "❌", "PENDING": "⏳"}
                    print(f"  {icon.get(t['status'], '⏳')} {t['id']}: {t['name']} ({t['engine']})")
        elif sub == "list":
            status = wf.get_status()
            if status.get("status") == "no_workflow":
                print("No workflow found")
            else:
                print(f"Workflow: {status['goal']}")
                for t in status.get("tasks", []):
                    icon = {"COMPLETED": "✅", "RUNNING": "🔄", "FAILED": "❌", "PENDING": "⏳"}
                    print(f"  {icon.get(t['status'], '⏳')} {t['id']}: {t['name']} ({t['engine']})")
        elif sub == "clear":
            from engine.workflow import WORKFLOW_FILE
            if WORKFLOW_FILE.exists():
                WORKFLOW_FILE.unlink()
                print("Workflow state cleared")
            else:
                print("No workflow state to clear")
        return 0

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
