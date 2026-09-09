#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import collections
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Deque








_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


try:
    from lib.scheduler import Store, Recovery, SchedulerUI
    SCHEDULER_AVAILABLE = True
except ImportError as _ie:
    SCHEDULER_AVAILABLE = False
    print(f"[overseer] scheduler import failed: {_ie}", file=sys.stderr)


def _fromiso(s: str) -> datetime:

    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):

        s2 = s.replace("T", " ").rstrip("Z")
        if "." in s2:
            s2 = s2.split(".")[0]
        return datetime.fromisoformat(s2)


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


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from lib.config import CFG  # noqa: E402
from lib import control  # noqa: E402 — daemon_present() to detect daemon mode
from lib.errorlog import log_exception, close_dump  # noqa: E402


try:
    from slimtoken.pipeline import minify_request, MinifyConfig  # noqa: E402
    SLIMTOKEN_AVAILABLE = True
except ImportError:
    SLIMTOKEN_AVAILABLE = False





def _bridge_emit(kind: str, content: str, **extra) -> None:

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


DEFAULT_INTERVAL = 30
WARM_CAP = 2000
HOT_CAP = 300
COMPACT_THRESHOLD = 0.85
COLD_DISTILL_INTERVAL = 3600








HOT_SOFT_PCT = 1.00
HOT_HARD_PCT = 2.00
HOT_CRITICAL_PCT = 3.00
HOT_SUSTAINED_TICKS_FORCE = 5






HOT_HARD_LIMIT_MB = 500
HOT_WARM_LIMIT_MB = 2000




WORKFLOW_DISPATCH_MAX = 2






MAX_QUEUE_SIZE = 500
MAX_WORKERS = 4
WORKER_TIMEOUT = 120
QUEUE_METRICS_FILE = STATE_DIR / "queue_metrics.json"
WORKER_POOL_FILE = STATE_DIR / "worker_pool.json"





_MAX_LLM_CALLS = 2
_llm_call_semaphore = threading.Semaphore(_MAX_LLM_CALLS)




_BACKOFF_BASE = 0.5
_BACKOFF_MAX = 30
_BACKOFF_FACTOR = 1.5
_BACKOFF_JITTER = 0.25



_latency_history: Deque = deque(maxlen=1000)
_token_history: Deque = deque(maxlen=1000)
_queue_depth_history: Deque = deque(maxlen=500)
_context_history: Deque = deque(maxlen=500)
_metrics_lock = threading.Lock()




CONTEXT_WARN_PCT = 85
CONTEXT_CRIT_PCT = 95


_worker_heartbeat: Deque = deque(maxlen=64)











_queue_dispatch_lock = threading.Lock()






_SHUTDOWN = False


def _handle_stop_signal(signum, frame):

    global _SHUTDOWN
    _SHUTDOWN = True



CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"






def _log(msg: str, emoji: str = "", color: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{color}{emoji} {BOLD}overseer{RST} {DIM}{color}[{ts}]{RST} {color}{msg}{RST}"
    print(line, file=sys.stderr)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")






def _load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")






def _backoff_delay(retry_count: int) -> float:

    base = _BACKOFF_BASE * (_BACKOFF_FACTOR ** retry_count)
    jitter = random.uniform(1 - _BACKOFF_JITTER, 1 + _BACKOFF_JITTER)
    return min(base * jitter, _BACKOFF_MAX)


def retry_with_backoff(func, *args, max_retries: int = 3, **kwargs) -> Any:

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = _backoff_delay(attempt)
                _log(f"Retry {attempt+1}/{max_retries} after {delay:.1f}s: {e}", "🔄", YELLOW)
                time.sleep(delay)
    raise last_exc






def _queue_add_backpressure(task: Dict) -> bool:

    queue = _load_queue()
    if len(queue) >= MAX_QUEUE_SIZE:
        _log(f"Queue full ({len(queue)}/{MAX_QUEUE_SIZE}) — backpressure", "⚠️", YELLOW)
        return False
    queue.append(task)
    _save_queue(queue)
    return True


def _queue_depth() -> int:

    queue = _load_queue()
    return len(queue)






class WorkerPool:

    def __init__(self, max_workers: int = MAX_WORKERS):
        self.max_workers = max_workers
        self.workers: Dict[str, threading.Thread] = {}
        self.heartbeats: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._shutdown = threading.Event()

    def submit(self, task: Dict) -> str:

        worker_id = f"worker-{task.get('id', 'unknown')}"
        worker = threading.Thread(
            target=self._run_task,
            args=(task,),
            daemon=True,
        )
        worker.start()
        with self._lock:
            self.workers[worker_id] = worker
            self.heartbeats[worker_id] = time.time()
        return worker_id

    def _run_task(self, task: Dict) -> None:

        worker_id = f"worker-{task.get('id', 'unknown')}"
        try:
            while not self._shutdown.is_set():
                self.heartbeats[worker_id] = time.time()

                success = _execute_task(task)
                if success:
                    break

                time.sleep(1)
        except Exception as e:
            _log(f"Worker {worker_id} crashed: {e}", "❌", RED)
        finally:
            with self._lock:
                if worker_id in self.workers:
                    del self.workers[worker_id]
                if worker_id in self.heartbeats:
                    del self.heartbeats[worker_id]

    def heartbeat_check(self) -> List[str]:

        dead = []
        now = time.time()
        with self._lock:
            for worker_id, last_heartbeat in list(self.heartbeats.items()):
                if now - last_heartbeat > WORKER_TIMEOUT:
                    dead.append(worker_id)

                    self.workers.pop(worker_id, None)
                    self.heartbeats.pop(worker_id, None)
        return dead

    def shutdown(self) -> None:

        self._shutdown.set()
        with self._lock:
            for worker in self.workers.values():
                worker.join(timeout=5)
            self.workers.clear()
            self.heartbeats.clear()






def _record_latency(task_type: str, duration_ms: float) -> None:

    with _metrics_lock:
        _latency_history.append((time.time(), task_type, duration_ms))


def _record_tokens(tokens_in: int, tokens_out: int) -> None:

    with _metrics_lock:
        _token_history.append((time.time(), tokens_in, tokens_out))


def _record_queue_depth(depth: int) -> None:

    with _metrics_lock:
        _queue_depth_history.append((time.time(), depth))


def _record_context_usage(context_len: int, max_ctx: int) -> None:

    with _metrics_lock:
        pct = (context_len / max_ctx * 100) if max_ctx > 0 else 0
        _context_history.append((time.time(), pct))


def _get_latency_stats() -> Dict:

    with _metrics_lock:
        if not _latency_history:
            return {"count": 0}
        latencies = [v for _, _, v in list(_latency_history)[-100:]]
        if not latencies:
            return {"count": 0}
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        return {
            "count": n,
            "avg_ms": round(sum(sorted_lat) / n, 2),
            "p95_ms": round(sorted_lat[int(n * 0.95)], 2) if n > 1 else sorted_lat[0],
            "p99_ms": round(sorted_lat[int(n * 0.99)], 2) if n > 1 else sorted_lat[0],
            "max_ms": round(sorted_lat[-1], 2),
        }


def _get_token_stats() -> Dict:

    with _metrics_lock:
        if not _token_history:
            return {"count": 0}
        recent = list(_token_history)[-100:]
        total_in = sum(t[1] for t in recent)
        total_out = sum(t[2] for t in recent)
        return {
            "count": len(recent),
            "tokens_in": total_in,
            "tokens_out": total_out,
            "ratio": round(total_out / total_in * 100, 1) if total_in > 0 else 0,
        }


def _get_queue_depth_stats() -> Dict:

    with _metrics_lock:
        if not _queue_depth_history:
            return {"count": 0}
        depths = [v for _, v in list(_queue_depth_history)[-100:]]
        if not depths:
            return {"count": 0}
        return {
            "count": len(depths),
            "avg": round(sum(depths) / len(depths), 2),
            "max": max(depths),
            "current": depths[-1] if depths else 0,
        }


def _get_context_stats() -> Dict:

    with _metrics_lock:
        if not _context_history:
            return {"count": 0}
        pcts = [v for _, v in list(_context_history)[-100:]]
        if not pcts:
            return {"count": 0}
        return {
            "count": len(pcts),
            "avg_pct": round(sum(pcts) / len(pcts), 2),
            "max_pct": max(pcts),
            "current_pct": pcts[-1] if pcts else 0,
        }


def _check_context_alerts() -> List[str]:

    alerts = []
    ctx_stats = _get_context_stats()
    current_pct = ctx_stats.get("current_pct", 0)
    if current_pct >= CONTEXT_CRIT_PCT:
        alerts.append(f"CRITICAL: Context at {current_pct:.1f}% — auto-reset needed")
    elif current_pct >= CONTEXT_WARN_PCT:
        alerts.append(f"WARN: Context at {current_pct:.1f}% — approaching limit")
    return alerts






def _shutdown_signal_handler(signum, frame):

    global _SHUTDOWN, _worker_pool
    _SHUTDOWN = True
    _log(f"Shutdown signal received ({signum}) — draining...", "🛑", RED)


    if _worker_pool:
        _worker_pool.stop()
        _log("Worker pool stopped", "🛑", DIM)


    _drain_queue()


    try:
        _save_metrics()
    except Exception:
        pass



signal.signal(signal.SIGTERM, _shutdown_signal_handler)
signal.signal(signal.SIGINT, _shutdown_signal_handler)


def _drain_queue() -> None:

    queue = _load_queue()
    pending = [t for t in queue if t["status"] in ("queued", "running")]
    if not pending:
        _log("Queue drain: nothing to do", "🧹", DIM)
        return
    _log(f"Draining {len(pending)} remaining tasks...", "🧹", CYAN)
    for task in pending:
        try:
            _execute_task(task)
            task["status"] = "completed"
            task["completed_at"] = datetime.now().isoformat()
        except Exception as e:
            task["status"] = "failed"
            task["completed_at"] = datetime.now().isoformat()
            task["error"] = str(e)[:200]
            _log(f"Drain: task {task['id']} failed: {e}", "❌", YELLOW)
    _save_queue(queue)
    _log("Queue drain complete", "🧹", GREEN)






def _save_metrics() -> None:

    metrics = {
        "timestamp": time.time(),
        "latency": _get_latency_stats(),
        "tokens": _get_token_stats(),
        "queue_depth": _get_queue_depth_stats(),
        "context": _get_context_stats(),
        "queue_size": _queue_depth(),
    }
    try:
        _save_json(QUEUE_METRICS_FILE, metrics)
    except Exception:
        pass


def _load_state() -> Dict:
    return _load_json(STATE_FILE, {
        "last_compact": None,
        "last_distill": None,
        "last_llm_summary": None,
        "health_events": [],
        "started_at": None,
        "total_ticks": 0,





        "overseer_state": {"label": "idle", "since": None},
        "task_steps": [],
        "current_step": None,
    })


def _save_state(state: Dict) -> None:
    _save_json(STATE_FILE, state)








def overseer_set_state(state: Dict, label: str) -> None:

    state["overseer_state"] = {"label": label, "since": datetime.now().isoformat()}


def task_steps_publish(state: Dict, steps: List[Dict], current: Optional[int]) -> None:

    state["task_steps"] = list(steps)
    state["current_step"] = current






def _query_llm(prompt: str, system: str = "", max_tokens: int = 256,
               temperature: float = 0.1, timeout: int = 30) -> Optional[str]:

    frame = (
        "You are the CortexAgent overseer's reasoning engine. Plain language, "
        "short answers (one or two lines), no markdown, no emojis, no narration. "
        "State the action taken and the artifact path. If uncertain, say so."
    )
    if system:
        wrapped_system = frame + "\n\n" + system
    else:
        wrapped_system = frame

    messages = [
        {"role": "system", "content": wrapped_system},
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": CFG.big_alias,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = f"http://127.0.0.1:{CFG.big_model_port}/v1/chat/completions"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        choices = data.get("choices") or [{}]
        content = choices[0].get("message", {}).get("content", "") or ""
        return content.strip()
    except Exception:
        return None


def _parse_tool_calls(message: dict) -> list:

    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append({
            "id": tc.get("id", f"call_{len(calls)}"),
            "name": name,
            "arguments": args,
        })
    return calls


def _parse_text_tool_calls(content: str) -> list:

    if not content:
        return []
    text = content.strip()

    m = re.search(
        r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:\n\s*Action Input:\s*(\{.*\}))?",
        text, re.S)
    if m:
        name = m.group(1)
        args = {}
        if m.group(2):
            try:
                args = json.loads(m.group(2))
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        return [{"id": "call_text_0", "name": name, "arguments": args}]

    m = re.search(r"<function_call>(.*?)</function_call>", text, re.S)
    if m:
        inner = m.group(1).strip()
        try:
            obj = json.loads(inner)
        except Exception:
            obj = None
        items = obj if isinstance(obj, list) else ([obj] if isinstance(obj, dict) else [])
        calls = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            if isinstance(name, str) and name:
                calls.append({"id": f"call_tag_{len(calls)}",
                              "name": name, "arguments": args})
        if calls:
            return calls

    start = text.find("{")
    if start == -1:
        return []
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return []
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []

    if "tool_call" in obj and isinstance(obj["tool_call"], dict):
        obj = obj["tool_call"]
    name = obj.get("tool") or obj.get("name") or obj.get("function")
    if isinstance(name, dict):
        name = name.get("name")
    if not isinstance(name, str) or not name:
        return []
    args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return [{"id": "call_text_0", "name": name, "arguments": args}]


def _query_llm_with_tools(messages: list, tools: list, max_tokens: int = 512,
                          timeout: int = 60) -> Optional[dict]:

    payload = {
        "model": CFG.big_alias,
        "messages": messages,
        "tools": tools,
        "max_tokens": int(max_tokens),
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = f"http://127.0.0.1:{CFG.big_model_port}/v1/chat/completions"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        choices = data.get("choices") or [{}]
        message = choices[0].get("message", {}) or {}
        calls = _parse_tool_calls(message)
        if calls:
            return {"kind": "tool_calls", "calls": calls}
        content = (message.get("content") or "").strip()
        if content:
            text_calls = _parse_text_tool_calls(content)
            if text_calls:
                return {"kind": "tool_calls", "calls": text_calls}
            return {"kind": "text", "content": content}
        return None
    except Exception:
        return None


def _big_model_healthy(timeout: float = 5.0) -> bool:

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{CFG.big_model_port}/slots", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _get_memory_stats() -> Dict:

    out = {"hot": 0, "warm": 0, "cold": 0,
           "hot_bytes": 0, "warm_bytes": 0}
    try:
        from slimtoken.memory.stats import stats as _cl_stats
        from lib.memory_thin import HOT_DIR, WARM_DIR  # noqa: F401
        s = _cl_stats(platform="cortexagent", dir=HOT_DIR.parent)
        plat = s.get("hot", {}).get("by_platform", {}).get("cortexagent", {})
        out["hot"] = plat.get("entries", 0)
        out["hot_bytes"] = plat.get("bytes", 0)
        plat_w = s.get("warm", {}).get("by_platform", {}).get("cortexagent", {})
        out["warm"] = plat_w.get("entries", 0)
        out["warm_bytes"] = plat_w.get("bytes", 0)


        out["cold"] = len(s.get("cold", {}).get("categories", []))
    except Exception:

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

    alerts = []
    proxy_port = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/health",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status not in (200, 502):
                alerts.append(f"Proxy health check failed (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        if e.code != 502:
            alerts.append(f"Proxy health check failed (HTTP {e.code})")
    except Exception:
        alerts.append(f"Proxy not reachable on port {proxy_port} — main model may be down")
    return alerts








MINIFY_STATS_FILE = STATE_DIR / "minify_stats.json"


def _read_minify_stats() -> Dict:

    try:
        with MINIFY_STATS_FILE.open(encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _merge_minify_into_state(state: Dict) -> None:

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



def _merge_token_stats() -> Dict:

    proxy_stats = _read_minify_stats()

    return {
        "proxy": proxy_stats,
        "total": {
            "runs": proxy_stats.get("runs", 0),
            "tokens_in": proxy_stats.get("tokens_in", 0),
            "tokens_out": proxy_stats.get("tokens_out", 0),
            "tokens_saved": proxy_stats.get("tokens_saved", 0),
            "ratio_pct": 0.0,
            "last_run_ts": proxy_stats.get("last_run_ts", 0),
        },
    }


def _merge_minify_into_state(state: Dict) -> None:

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
        if e.code != 502:
            alerts.append(f"Proxy health check failed (HTTP {e.code})")
    except Exception:
        alerts.append(f"Proxy not reachable on port {proxy_port} — main model may be down")
    return alerts



_CTX_CRITICAL_TICKS = 0




def _check_context_window() -> List[str]:

    global _CTX_CRITICAL_TICKS
    alert_pct = CFG.context_alert_pct
    critical_pct = CFG.context_critical_pct
    port = CFG.big_model_port
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/slots")
        with urllib.request.urlopen(req, timeout=5) as resp:
            slots = json.loads(resp.read().decode() or "[]")
    except Exception:

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
        if pct >= critical_pct:
            critical = True
            alerts.append(f"CONTEXT WINDOW at {pct:.0f}% ({n_past}/{n_ctx} tok) — "
                          f"auto-compact failed, ceiling imminent")
        elif pct >= alert_pct:
            alerts.append(f"Context window at {pct:.0f}% ({n_past}/{n_ctx} tok) — near ceiling")
    if critical:
        _CTX_CRITICAL_TICKS += 1
    else:
        _CTX_CRITICAL_TICKS = 0
    return alerts


def _context_failsafe() -> None:

    global _CTX_CRITICAL_TICKS
    needed = CFG.context_critical_ticks
    if _CTX_CRITICAL_TICKS < needed:
        return
    _CTX_CRITICAL_TICKS = 0
    _log(f"Context window pegged ≥{CFG.context_critical_pct:.0f}% for "
         f"{needed} ticks — resetting session so the next "
         f"launch starts with fresh context (avoiding a hard 400)", "🔥", RED)
    try:
        control.send_request("session-reset", timeout=5)
    except Exception:
        _log("context failsafe: session-reset failed", "❌", RED)


def _check_latency_alert() -> List[str]:

    threshold = CFG.latency_alert_p95_ms
    if not threshold:
        return []
    stats = _get_latency_stats()
    if stats.get("count", 0) < 5:
        return []
    p95 = stats.get("p95_ms", 0)
    if p95 > threshold:
        return [f"LATENCY p95 {p95:.0f}ms > {threshold:.0f}ms threshold "
                f"({stats.get('count', 0)} samples, avg {stats.get('avg_ms', 0):.0f}ms)"]
    return []


def _cortexagent_active() -> bool:

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






        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid, comm, args = parts
        try:
            if int(pid) in exclude:
                continue
        except ValueError:
            continue


        if "bin/cortexagent" in args:
            return True

        if comm in ("claude", "node") and "--mcp-config" in args and "cortexagent" in args:
            return True
    return False


def _watchdog_cortexagent() -> None:

    if _cortexagent_active():
        return





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



            return
        _log("cortexagent closed AND daemon idle > "
             f"{watchdog_stale_sec}s with active session — "
             "resetting + unloading big model", "🧹", YELLOW)
        control.send_request("session-reset", timeout=5)
    except Exception:
        pass


def _check_db_integrity() -> List[str]:

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

    total = stats["hot"] + stats["warm"] + stats["cold"]
    try:
        from slimtoken.memory.stats import estimate_tokens
        est = estimate_tokens("x" * (total * 200))
    except ImportError:
        est = (total * 200) // 4
    if est > 1_000_000:
        return f"{est/1_000_000:.1f}M"
    if est > 1_000:
        return f"{est/1_000:.0f}K"
    return str(est)


def _cold_distill() -> bool:

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

    try:






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

    try:
        sys.path.insert(0, str(REPO_ROOT))
        from engine import WorkflowEngine
        from engine.types import TaskStatus
        from engine.workflow import _load_workflow, _save_workflow
        plan_path = WORKFLOW_FILE
        if not plan_path.exists():
            return 0
        plan = _load_workflow()
        if not plan:
            return 0


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


                model = "opus" if task.engine.name == "LLM_REASONING" else "sonnet"


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
                    task.result = res["output"][:8000]
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
            _save_workflow(plan)
        return dispatched
    except Exception as e:
        _log(f"Workflow dispatch error: {e}", "⚠️", YELLOW)
        return 0








def _hot_remediation(state: Dict, stats: Dict) -> None:

    hot_bytes = stats.get("hot_bytes", 0)
    warm_bytes = stats.get("warm_bytes", 0)
    sustained = int(state.get("hot_overflow_ticks", 0))




    _hot_to_warm_sync(state)


    hot_mb = hot_bytes / (1024 * 1024)
    warm_mb = warm_bytes / (1024 * 1024)
    if hot_mb > HOT_HARD_LIMIT_MB or warm_mb > HOT_WARM_LIMIT_MB:
        state["hot_overflow_ticks"] = sustained + 1
        overseer_set_state(
            state,
            f"memory size advisory: hot={hot_mb:.1f}MB warm={warm_mb:.1f}MB "
            f"(advisory only; no action taken per hard rule)"
        )
        if sustained % 30 == 0:
            _log(f"Memory advisory: hot={hot_mb:.1f}MB warm={warm_mb:.1f}MB "
                 f"(no caps, no /clear — this is informational only)", "📊", YELLOW)
    else:
        if sustained:
            state["hot_overflow_ticks"] = 0


def _hot_to_warm_sync(state: Dict) -> None:

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
                    continue

                with open(hot_file, "rb") as f:
                    f.seek(max(0, warm_size - 1))
                    gap = f.read()
                if gap:
                    _atomic_append_bytes(warm_file, gap)
            except OSError:
                continue
    except ImportError:
        pass


def _atomic_append_bytes(file_path, data: bytes) -> None:

    try:
        from slimtoken.memory.atomic import atomic_append_bytes
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






def _load_queue() -> List[Dict]:
    return _load_json(QUEUE_FILE, [])


def _save_queue(queue: List[Dict]) -> None:
    _save_json(QUEUE_FILE, queue)


def queue_add(task_type: str, prompt: str = "", command: str = "",
              output: str = "", priority: int = 0,
              scheduler_task_id: str = "") -> Dict:
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
        "scheduler_task_id": scheduler_task_id or None,
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

    task_type = task.get("type", "command")
    prompt = task.get("prompt", "")
    command = task.get("command", "")
    output = task.get("output", "")
    start_time = time.time()
    max_retries = 3 if task_type in ("llm", "image", "video") else 0

    _log(f"Running {task_type} task...", "▶️", MAGENTA)

    from lib.tool_registry import execute_tool

    if task_type == "command":
        try:
            result = execute_tool("run_command", {"command": command})
            if result.get("ok"):
                _log(f"Command succeeded: {command[:60]}", "✅", GREEN)
                return True
            _log(f"Command failed: {(result.get('output') or result.get('error', ''))[:200]}",
                 "❌", RED)
            return False
        except Exception as e:
            _log(f"Command error: {e}", "❌", RED)
            return False

    elif task_type == "llm":


        from lib.react_loop import run_react

        try:
            result = retry_with_backoff(
                run_react,
                task,
                max_retries=max_retries,
                state=state,
            )
            if result.get("ok"):
                duration_ms = (time.time() - start_time) * 1000
                _record_latency("llm", duration_ms)
                _record_tokens(
                    max(1, len(prompt) // 4),
                    max(0, len(result.get('output', '')) // 4),
                )

                from lib.react_loop import _beautify_response
                result['output'] = _beautify_response(result.get('output', ''))
                _log(f"LLM task completed ({len(result.get('output', ''))} chars, {duration_ms:.0f}ms)",
                     "✅", GREEN)
                return True
            _log(f"LLM task failed: {result.get('error', '')[:120]}", "❌", RED)
            return False
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            _record_latency("llm", duration_ms)
            _log(f"LLM task error: {e}", "❌", RED)
            return False

    elif task_type == "subagent":


        model = task.get("model", "sonnet")
        timeout = int(task.get("timeout", 600))
        try:
            result = retry_with_backoff(
                execute_tool,
                "spawn_subagent",
                {"prompt": prompt, "model": model, "timeout": timeout},
                max_retries=1,
            )
            if result.get("ok"):
                _log(f"Subagent task completed ({len(result.get('output', ''))} chars)",
                     "✅", GREEN)
                return True
            _log(f"Subagent failed: {result.get('error', '')[:120]}", "❌", RED)
            return False
        except Exception as e:
            _log(f"Subagent error: {e}", "❌", RED)
            return False

    elif task_type in ("image", "video"):

        tool = "generate_image" if task_type == "image" else "generate_video"
        try:
            result = retry_with_backoff(
                execute_tool,
                tool,
                {"prompt": prompt},
                max_retries=2,
            )
            if result.get("ok"):
                _log(f"Media task completed ({task_type})", "✅", GREEN)
                return True
            _log(f"Media task {task_type}: {result.get('error', 'unknown')}",
                 "⚠️", YELLOW)
            return False
        except Exception as e:
            _log(f"Media task error: {e}", "⚠️", YELLOW)
            return False

    elif task_type == "media":

        try:
            result = execute_tool("generate_media", {"prompt": prompt})
            if result.get("ok"):


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
        except Exception as e:
            _log(f"Media task error: {e}", "⚠️", YELLOW)
            return False

    elif task_type == "ingest":

        try:
            if command:
                result = execute_tool("run_command", {"command": command, "timeout": 3600})
            else:
                result = execute_tool("ingest_domain", {
                    "domain": task.get("domain", ""),
                    "source": task.get("source", ""),
                    "text": task.get("text", ""),
                })
            if result.get("ok"):
                _log(f"Ingest task completed: {(result.get('output') or '')[:120]}", "✅", GREEN)
                return True
            _log(f"Ingest task failed: {(result.get('output') or result.get('error', ''))[:200]}",
                 "❌", RED)
            return False
        except Exception as e:
            _log(f"Ingest error: {e}", "❌", RED)
            return False

    return False


def _sync_scheduler_result(task: Dict, success: bool) -> None:

    sched_task_id = task.get("scheduler_task_id")
    if not sched_task_id:
        return
    sched = _scheduler()
    if sched is None:
        return
    try:
        rec = sched.get(sched_task_id)
        if not rec:
            return
        new_state = "completed" if success else "failed"

        sched.update(sched_task_id, rec.get("version", 0), state=new_state)
        sched.record_execution(
            sched_task_id,
            status=new_state,
            result="success" if success else "failed",
        )
        _log(f"📅 Scheduler task '{rec.get('title', sched_task_id)}' → {new_state}",
             "📅", GREEN if success else RED)
    except Exception as e:
        _log(f"Scheduler sync failed for {sched_task_id}: {e}", "⚠️", YELLOW)


def _process_queue(state: Optional[Dict] = None) -> None:

    if _SHUTDOWN:

        queue = _load_queue()
        remaining = len([t for t in queue if t["status"] in ("queued", "running")])
        if remaining > 0:
            _log(f"Shutdown: draining {remaining} remaining tasks...", "🛑", YELLOW)
        else:
            return

    if not _queue_dispatch_lock.acquire(blocking=False):


        return
    try:
        queue = _load_queue()
        pending = [t for t in queue if t["status"] == "queued"]
        if not pending:
            _record_queue_depth(0)
            return

        _record_queue_depth(len(pending))
        _log(f"Processing {len(pending)} queued tasks...", "▶️", MAGENTA)
        _bridge_emit("queue", f"▶️ Processing {len(pending)} queued task(s)")

        for task in pending:

            if _SHUTDOWN and len([t for t in queue if t["status"] == "queued"]) > 5:

                _log("Shutdown: leaving remaining tasks for next start", "🛑", YELLOW)
                break

            task["status"] = "running"
            task["started_at"] = datetime.now().isoformat()
            _save_queue(queue)
            _record_queue_depth(len([t for t in queue if t["status"] == "queued"]))
            _bridge_emit(
                "task_start",
                f"▶️ Task {task['id']} ({task['type']}) starting — {task.get('prompt') or task.get('command','')[:120]}",
                task_id=task["id"],
                task_type=task["type"],
            )

            try:
                success = _execute_task(task, state)
            except Exception as e:


                _log(f"Task {task['id']} crashed: {e}", "❌", RED)
                _bridge_emit("task_crash", f"❌ Task {task['id']} crashed: {e}",
                             task_id=task["id"])
                success = False

            task["status"] = "completed" if success else "failed"
            task["completed_at"] = datetime.now().isoformat()
            task["result"] = "success" if success else "failed"
            _save_queue(queue)
            _record_queue_depth(len([t for t in queue if t["status"] in ("queued", "running")]))


            _sync_scheduler_result(task, success)

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


def _cleanup_queue() -> None:

    queue = _load_queue()
    now = datetime.now()
    kept = []
    removed = 0
    for task in queue:

        if task["status"] in ("queued", "running"):
            kept.append(task)
            continue

        try:
            completed_at = datetime.fromisoformat(task.get("completed_at", now.isoformat()))
        except Exception:
            kept.append(task)
            continue

        if (now - completed_at).total_seconds() < 3600 or len(kept) < 10:
            kept.append(task)
        else:
            removed += 1
    if removed:
        _save_queue(kept)
        _log(f"Queue cleanup: removed {removed} old completed tasks", "🧹", DIM)






def _load_schedule() -> List[Dict]:
    return _load_json(SCHEDULE_FILE, [])


def _save_schedule(schedule: List[Dict]) -> None:
    _save_json(SCHEDULE_FILE, schedule)


def _cron_matches(expr: str, now: datetime) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, mon, dow = fields

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


def _scheduler() -> Optional[Store]:

    if SCHEDULER_AVAILABLE:
        return Store()
    return None


def _check_schedule_legacy() -> None:

    now = datetime.now()
    schedule = _load_schedule()

    for entry in schedule:
        if not entry.get("enabled", True):
            continue

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


def schedule_add(name: str, task_type: str, schedule_type: str,
                 schedule_value: str, prompt: str = "", command: str = "",
                 output: str = "", system: str = "") -> Dict:

    sched = _scheduler()
    if sched is None:

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


    receipt = sched.create(
        title=name,
        kind="user",
        trigger=schedule_type,
        schedule_value=schedule_value,
        payload_type=task_type,
        payload={"command": command, "prompt": prompt, "output": output, "system": system},
        owner="cli",
        ephemeral=False,
        visible=True,
    )
    if receipt.get("ok"):
        _log(f"📅 Scheduled '{name}' ({schedule_type}: {schedule_value})",
             "📅", CYAN)
        return {"ok": True, "task_id": receipt["task_id"], **receipt}
    _log(f"📅 Failed to schedule '{name}': {receipt.get('error')}", "❌", RED)
    return receipt


def schedule_list() -> List[Dict]:

    sched = _scheduler()
    if sched is None:
        return _load_schedule()
    return sched.list()


def schedule_remove(name: str) -> bool:

    sched = _scheduler()
    if sched is None:
        schedule = _load_schedule()
        before = len(schedule)
        schedule = [s for s in schedule if s["name"] != name]
        _save_schedule(schedule)
        if len(schedule) < before:
            _log(f"Removed schedule '{name}'", "🗑️", YELLOW)
            return True
        return False


    for task in sched.list():
        if task.get("title") == name or name in task.get("title", ""):
            result = sched.cancel(task["id"])
            if result.get("ok"):
                _log(f"🗑️ Removed schedule '{name}'", "🗑️", YELLOW)
                return True
            return False
    _log(f"Schedule '{name}' not found", "🗑️", YELLOW)
    return False


def _check_schedule() -> None:

    sched = _scheduler()
    if sched is None:

        _check_schedule_legacy()
        return


    tasks = sched.list(visible_only=False)
    now = datetime.now()

    for task in tasks:
        if not task.get("enabled", True):
            continue
        if task.get("state") != "scheduled":
            continue


        last_run = task.get("last_run")
        if last_run:
            try:
                if _fromiso(last_run).strftime("%Y%m%d%H%M") == now.strftime("%Y%m%d%H%M"):
                    continue
            except Exception:
                pass


        should_run = False
        trigger = task.get("trigger", "manual")
        sv = task.get("schedule_value", "")

        if trigger == "cron":
            should_run = _cron_matches(sv, now)
        elif trigger == "daily":
            parts = sv.split(":")
            target_hour = int(parts[0])
            target_min = int(parts[1]) if len(parts) > 1 else 0
            should_run = (now.hour == target_hour and now.minute == target_min)
        elif trigger == "weekly":
            parts = sv.split(":")
            days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_day = days.get(parts[0].lower(), -1)
            target_hour = int(parts[1]) if len(parts) > 1 else 0
            target_min = int(parts[2]) if len(parts) > 2 else 0
            should_run = (now.weekday() == target_day and
                         now.hour == target_hour and now.minute == target_min)
        elif trigger == "date":
            try:
                target = _fromiso(sv)
                should_run = (now >= target)
            except Exception:
                pass
        elif trigger == "interval":
            should_run = True

        if should_run:
            payload = task.get("payload", {})
            task_type = task.get("payload_type", "command")
            queue_add(task_type,
                      prompt=payload.get("prompt", ""),
                      command=payload.get("command", ""),
                      output=payload.get("output", ""),
                      scheduler_task_id=task["id"])


            sched.update(task["id"], task.get("version", 0),
                        state="queued", updated_at=now.isoformat())

            _log(f"📅 Scheduled task '{task['title']}' queued ({task_type})",
                 "📅", GREEN)
            _bridge_emit(
                "schedule_fired",
                f"📅 Scheduled task '{task['title']}' queued ({task_type})",
                schedule_name=task["title"],
                task_type=task_type,
            )













def _plan():

    try:
        from slimtoken.memory.plan import Plan as _Plan
        return _Plan(dir=str(STATE_DIR), name="overseer_plan")
    except ImportError:
        return None


def plan_set(name: str, total_steps: int, context: str = "",
             steps: Optional[List[str]] = None) -> Dict:

    plan = _plan()
    if plan is not None:

        result = plan.set(name=name, total_steps=total_steps,
                          steps=steps, context=context)
        _log(f"Plan set: '{name}' ({total_steps} steps)", "📋", CYAN)
        return result

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

    plan = _plan()
    if plan is not None:
        return plan.status()
    data = _load_json(PLAN_FILE)
    if not data:
        return {"error": "No plan set. Use plan-set first."}
    return data


def plan_complete() -> Dict:

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






def _daemon_loop(interval: int) -> None:




    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)

    _log(f"Overseer daemon started (interval: {interval}s, model: :{CFG.big_model_port})", "🚀", CYAN)

    state = _load_state()
    state["started_at"] = datetime.now().isoformat()
    _save_state(state)


    has_llm = _big_model_healthy()

    tick = 0
    while not _SHUTDOWN:
        try:
            tick += 1
            state["total_ticks"] = tick
            now = datetime.now().strftime("%H:%M:%S")
            _log(f"── Tick {tick} @ {now} ─────────────────────", "⏱️", DIM)



            task_steps_publish(state, [
                {"id": 1, "label": "Memory health checks",       "status": "in_progress"},
                {"id": 2, "label": "Watchdog (every 2nd tick)",  "status": "pending"},
                {"id": 3, "label": "Minify stats merge",         "status": "pending"},
                {"id": 4, "label": "Schedule + queue dispatch",  "status": "pending"},
                {"id": 5, "label": "LLM health summary",         "status": "pending"},
            ], current=1)


            overseer_set_state(state, "watching memory health")
            stats = _get_memory_stats()
            _log(f"Memory: {stats['hot']}H / {stats['warm']}W / {stats['cold']}C", "📊", DIM)
            alerts = _check_health(stats)
            alerts += _check_memory_writes()
            alerts += _check_session_health()


            ctx_alerts = _check_context_window()
            alerts += ctx_alerts
            _context_failsafe()
            if ctx_alerts:
                _log("Context: " + " | ".join(ctx_alerts), "📏", YELLOW)



            lat_alerts = _check_latency_alert()
            alerts += lat_alerts
            if lat_alerts:
                _log("Latency: " + " | ".join(lat_alerts), "⏱️", YELLOW)




            if tick % 2 == 0:
                overseer_set_state(state, "watchdogging cortexagent session")
                _watchdog_cortexagent()




            overseer_set_state(state, "merging minify stats")
            _merge_minify_into_state(state)


            if tick % 10 == 0:
                alerts += _check_db_integrity()
                _cleanup_queue()

            if alerts:
                for alert in alerts:
                    _log(f"ALERT: {alert}", "🔴", RED)
                state["health_events"].append({
                    "time": datetime.now().isoformat(),
                    "alerts": alerts,
                })
                state["health_events"] = state["health_events"][-100:]




                if stats["warm"] > WARM_CAP * COMPACT_THRESHOLD:
                    overseer_set_state(
                        state,
                        f"warm at {int(stats['warm']/WARM_CAP*100)}% (advisory only; "
                        f"no auto-compact per hard rule)"
                    )



            _hot_remediation(state, stats)


            last_distill = state.get("last_distill")
            if stats["warm"] > 100 and (
                not last_distill or
                (datetime.now() - _fromiso(last_distill)).total_seconds() > COLD_DISTILL_INTERVAL
            ):
                overseer_set_state(state, "distilling warm → cold")
                _cold_distill()
                state["last_distill"] = datetime.now().isoformat()


            pool = get_worker_pool()
            if pool:
                actions = pool.heartbeat_check()
                for action in actions:
                    _log(f"Worker pool: {action}", "⚠️", YELLOW)


            overseer_set_state(state, "checking schedule + queue")



            _sched = _scheduler()
            sched_count = len(_sched.list(visible_only=False)) if _sched else len(_load_schedule())
            _log(f"Schedule: {sched_count} entries", "📅", DIM)
            _check_schedule()


            q = _load_queue()
            pending = len([t for t in q if t["status"] == "queued"])
            if pending:
                _log(f"Queue: {pending} pending tasks", "📦", DIM)
            _process_queue(state)


            _record_queue_depth(len(q))


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






                if wf_status.get("pending", 0) > 0:
                    threading.Thread(
                        target=_dispatch_workflow, args=(state,),
                        daemon=True,
                    ).start()
            except Exception:
                pass


            if tick % 5 == 0:
                _record_queue_depth(len([t for t in _load_queue()]))

                ctx_alerts = _check_context_alerts()
                if ctx_alerts:
                    for alert in ctx_alerts:
                        _log(f"CONTEXT: {alert}", "🔴", RED)
                    state["health_events"].append({
                        "time": datetime.now().isoformat(),
                        "alerts": ctx_alerts,
                    })






            if has_llm and tick % 10 == 0:
                overseer_set_state(state, "querying LLM for health summary")
                prompt = (
                    f"Memory: {stats['hot']}H/{stats['warm']}W/{stats['cold']}C. "
                    f"Alerts: {len(alerts)}. Ticks: {tick}. "
                    "Is the system healthy? One short sentence."
                )
                summary = _query_llm(prompt, "You are a system monitor. Be concise.", 64)
                if summary:
                    _log(f"LLM health: {summary}", "💬", DIM)
                    state["last_llm_summary"] = summary


            if tick % 5 == 0:
                est = _estimate_tokens(stats)
                _log(f"Memory: {stats['hot']}H/{stats['warm']}W/{stats['cold']}C (~{est} tok)  "
                     f"Alerts: {len(alerts)}  Ticks: {tick}", "📊", DIM)


            overseer_set_state(state, "idle")
            task_steps_publish(state, [], None)
            _save_state(state)

        except Exception as e:



            _log(f"Daemon error: {e}", "❌", RED)
            log_exception(
                e, component="overseer",
                context={"tick": tick, "state": state.get("status", "?")},
                log_file=LOG_FILE,
            )



        for _ in range(interval):
            if _SHUTDOWN:
                break
            time.sleep(1)


    _log("Overseer shutting down...", "🛑", YELLOW)
    state = _load_state()
    state["stopped_at"] = datetime.now().isoformat()
    _save_state(state)


    close_dump(
        component="overseer",
        reason="SIGINT/SIGTERM clean shutdown",
        context={"ticks": tick, "started_at": state.get("started_at")},
        log_file=LOG_FILE,
    )
    PID_FILE.unlink(missing_ok=True)
    _log("Overseer stopped cleanly (exit 0)", "✅", GREEN)
    sys.exit(0)






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


def _start(interval: int) -> None:

    pid = _is_running()
    if pid:
        print(f"Overseer already running (pid {pid})")
        return

    pid = os.fork()
    if pid > 0:

        PID_FILE.write_text(str(pid))
        print(f"Overseer started (pid {pid})")
        return


    os.setsid()





    with open(os.devnull, 'w') as null:
        os.dup2(null.fileno(), 0)
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)
    _daemon_loop(interval)


def _stop() -> None:

    pid = _is_running()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)




            exited = False
            for _ in range(450):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    exited = True
                    break
            if not exited:


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


def _replace_emoji(text: str) -> str:

    replacements = {
        "✅": "✓",
        "❌": "✕",
        "⚠️ ": "▲",
        "📋": "▎",
        "📦": "◻",
        "📅": "◌",
        "🗑️ ": "✕",
        "🛑": "▌",
        "👷": "◉",
        "⚠️": "▲",
        "📊": "◐",
        "🔴": "✕",
        "🟡": "▲",
        "🟠": "▲",
        "🟢": "✓",
    }
    for emoji, glyph in replacements.items():
        text = text.replace(emoji, glyph)
    return text


def _status() -> None:

    pid = _is_running()
    if pid:
        state = _load_state()
        plan = _load_json(PLAN_FILE)
        queue = _load_queue()
        schedule = _load_schedule()

        lines = [
            f"Overseer: RUNNING (pid {pid})",
            f"  Started: {state.get('started_at', 'unknown')}",
            f"  Ticks: {state['total_ticks']}",
            f"  Model: {CFG.big_alias} on :{CFG.big_model_port} "
            f"({'up' if _big_model_healthy() else 'down'})",
        ]

        stats = _get_memory_stats()
        lines.append(f"  Memory: {stats['hot']}H / {stats['warm']}W / {stats['cold']}C")
        lines.append(f"  Last compact: {state.get('last_compact', 'never')}")
        lines.append(f"  Last distill: {state.get('last_distill', 'never')}")

        pending = len([t for t in queue if t["status"] == "queued"])
        lines.append(f"  Queue: {len(queue)} total ({pending} pending)")
        lines.append(f"  Schedule: {len(schedule)} entries")



        m = state.get("minify") or _read_minify_stats()
        if m and m.get("runs", 0):
            lines.append(f"  Minify: {m['tokens_saved']:,} tok saved "
                         f"({m['ratio_pct']:.0f}%) across {m['runs']} runs")
        else:
            lines.append(f"  Minify: no runs yet")


        token_stats = _merge_token_stats()
        total = token_stats.get("total", {})
        if total.get("runs", 0):
            lines.append(f"  Tokens in:  {total.get('tokens_in', 0):,}")
            lines.append(f"  Tokens out: {total.get('tokens_out', 0):,}")
            lines.append(f"  Tokens saved: {total.get('tokens_saved', 0):,} ({total.get('ratio_pct', 0):.1f}%)")
            lines.append(f"  Proxy runs: {token_stats.get('proxy', {}).get('runs', 0)}")
        else:
            lines.append(f"  Token tracking: no data yet")


        latency_stats = _get_latency_stats()
        if latency_stats.get("count", 0):
            lines.append(f"  Latency (ms): avg={latency_stats['avg_ms']:.0f} "
                         f"p95={latency_stats['p95_ms']:.0f} "
                         f"p99={latency_stats.get('p99_ms', 'n/a')}")
        else:
            lines.append(f"  Latency: no data yet")

        queue_depth_stats = _get_queue_depth_stats()
        if queue_depth_stats.get("count", 0):
            lines.append(f"  Queue depth: avg={queue_depth_stats['avg']:.1f} "
                         f"max={queue_depth_stats['max']} "
                         f"current={queue_depth_stats['current']}")
        else:
            lines.append(f"  Queue depth: no data yet")

        ctx_stats = _get_context_stats()
        if ctx_stats.get("count", 0):
            lines.append(f"  Context usage: avg={ctx_stats['avg_pct']:.1f}% "
                         f"max={ctx_stats['max_pct']:.1f}% "
                         f"current={ctx_stats['current_pct']:.1f}%")
        else:
            lines.append(f"  Context usage: no data yet")


        pool = WorkerPool()
        dead_workers = pool.heartbeat_check()
        if dead_workers:
            lines.append(f"  Dead workers: {len(dead_workers)} (replaced)")
        else:
            lines.append(f"  Workers: healthy")

        if plan and "error" not in plan:
            step = plan.get("current_step", 0)
            total = plan.get("total_steps", 0)
            name = plan.get("name", "?")
            done = "✅" if plan.get("completed") else "➡️"
            lines.append(f"  Plan: {done} '{name}' — step {step}/{total}")


        output = "\n".join(lines)
        print(_beautify_status(output))
    else:
        print("Overseer: STOPPED")


def _beautify_status(text: str) -> str:

    try:
        text = _replace_emoji(text)
        from lib.beautify import beautify
        return beautify(text)
    except Exception:
        return text


def _smoke() -> int:

    print(f"{BOLD}Overseer Smoke Test{RST}")
    print(f"{'─'*50}")
    print("  Smoke runner is DISABLED. See _smoke() docstring.")
    print(f"{'─'*50}")
    return 0






def _minify_status_cli(args: List[str]) -> None:

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
        elif sub == "cleanup":
            _cleanup_queue()
            print("Queue cleanup completed")
        elif sub == "prune":

            _cleanup_queue()
            print("Prune completed")
        return 0


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






class WorkerPool:


    def __init__(self, max_workers: int = 5, heartbeat_interval: int = 60):
        self.max_workers = max_workers
        self.heartbeat_interval = heartbeat_interval
        self.workers: List[Dict] = []
        self._stop_event = threading.Event()
        self._metrics = {
            "total_executed": 0,
            "total_failed": 0,
            "last_executions": deque(maxlen=100),
        }
        self._lock = threading.Lock()

    def start(self) -> None:

        self._stop_event.clear()
        for i in range(self.max_workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"worker-{i}",
                daemon=True,
            )
            t.start()
            worker_id = f"w{i}"
            self.workers.append({
                "id": worker_id,
                "thread": t,
                "last_heartbeat": time.time(),
                "status": "alive",
                "current_task": None,
            })
            _log(f"Worker {worker_id} started", "👷", DIM)

    def stop(self) -> None:

        self._stop_event.set()
        for w in self.workers:
            try:
                w["thread"].join(timeout=10)
            except Exception:
                pass
        self.workers.clear()
        _log("Worker pool stopped", "🛑", RED)

    def _worker_loop(self) -> None:

        while not self._stop_event.is_set():
            try:

                queue = _load_queue()
                task = None
                for i, t in enumerate(queue):
                    if t["status"] == "queued":
                        task = t
                        task["status"] = "running"
                        task["started_at"] = datetime.now().isoformat()
                        _save_queue(queue)
                        break

                if task is None:
                    time.sleep(1)
                    continue


                self._update_heartbeat(True, task["id"])

                try:
                    start = time.time()
                    success = _execute_task(task)
                    duration_ms = (time.time() - start) * 1000

                    with self._lock:
                        self._metrics["total_executed"] += 1
                        if success:
                            self._metrics["last_executions"].append(
                                (time.time(), duration_ms))
                        else:
                            self._metrics["total_failed"] += 1


                    queue = _load_queue()
                    for i, t in enumerate(queue):
                        if t["id"] == task["id"]:
                            t["status"] = "succeeded" if success else "failed"
                            t["completed_at"] = datetime.now().isoformat()
                            t["result"] = "ok" if success else "error"
                            queue[i] = t
                            break
                    _save_queue(queue)

                except Exception as e:
                    with self._lock:
                        self._metrics["total_failed"] += 1
                    _log(f"Worker task error: {e}", "❌", RED)

                finally:
                    self._update_heartbeat(True, None)

            except Exception as e:
                _log(f"Worker loop error: {e}", "❌", RED)
                time.sleep(5)

        self._update_heartbeat(False, None)

    def _update_heartbeat(self, alive: bool, current_task: Optional[str]) -> None:

        thread_name = threading.current_thread().name
        for w in self.workers:
            if w["thread"].name == thread_name:
                w["last_heartbeat"] = time.time()
                w["status"] = "alive" if alive else "dead"
                w["current_task"] = current_task
                break

    def heartbeat_check(self) -> List[str]:

        now = time.time()
        actions = []
        dead_workers = []

        for w in self.workers:
            if now - w["last_heartbeat"] > self.heartbeat_interval * 2:
                dead_workers.append(w["id"])

        if dead_workers:

            for dw in dead_workers:

                self.workers = [w for w in self.workers if w["id"] != dw]

                replacement_id = f"w{len(self.workers)}"
                t = threading.Thread(
                    target=self._worker_loop,
                    name=replacement_id,
                    daemon=True,
                )
                t.start()
                self.workers.append({
                    "id": replacement_id,
                    "thread": t,
                    "last_heartbeat": time.time(),
                    "status": "alive",
                    "current_task": None,
                })
                actions.append(f"Replaced dead worker {dw} with {replacement_id}")
                _log(f"Worker pool: replaced dead worker {dw}", "⚠️", YELLOW)

        return actions

    def get_metrics(self) -> Dict:

        with self._lock:
            last_execs = list(self._metrics["last_executions"])
            durations = [d for _, d in last_execs]

            return {
                "total_executed": self._metrics["total_executed"],
                "total_failed": self._metrics["total_failed"],
                "worker_count": len(self.workers),
                "active_workers": len([w for w in self.workers if w["status"] == "alive"]),
                "p95_latency": sorted(durations)[-1] if durations else 0,
                "p50_latency": sorted(durations)[len(durations) // 2] if durations else 0,
            }



_worker_pool: Optional[WorkerPool] = None


def get_worker_pool() -> Optional[WorkerPool]:

    global _worker_pool
    if _worker_pool is None:
        _worker_pool = WorkerPool()
        _worker_pool.start()
    return _worker_pool


def record_queue_depth(depth: int) -> None:

    global _queue_depth_history
    _queue_depth_history.append((time.time(), depth))









if __name__ == "__main__":
    sys.exit(main())


