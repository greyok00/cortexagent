#!/usr/bin/env python3
"""heartbeat_daemon — tiny LLM-powered memory monitor for CortexLLM.

Runs as a background process. Uses a tiny local model (qwen2.5:0.5b via Ollama)
to monitor memory health, trigger cold distillation, and auto-compact when
context is near the limit.

Designed to fit in ~2 GB free VRAM alongside the main model.

CLI:
  python3 heartbeat_daemon.py start [--interval 30] [--model qwen2.5:0.5b]
  python3 heartbeat_daemon.py stop
  python3 heartbeat_daemon.py status
  python3 heartbeat_daemon.py smoke
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from memory.db import db
from memory.manager import manager

PID_FILE = Path(os.environ.get("CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent"))) / "heartbeat.pid"
LOG_FILE = Path(os.environ.get("CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent"))) / "heartbeat.log"
STATE_FILE = Path(os.environ.get("CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent"))) / "heartbeat_state.json"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_INTERVAL = 30  # seconds
WARM_CAP = 2000
HOT_CAP = 300
COMPACT_THRESHOLD = 0.85  # compact when warm is 85% full


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_compact": None, "last_distill": None, "health_events": []}


def _save_state(state: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _check_ollama() -> bool:
    """Check if Ollama is running and the tiny model is available."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_URL.replace('/generate', '/tags')}",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return any(DEFAULT_MODEL in m for m in models)
    except Exception:
        return False


def _query_llm(prompt: str, system: str = "") -> Optional[str]:
    """Query the tiny LLM via Ollama."""
    payload = {
        "model": DEFAULT_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "num_predict": 256,
            "temperature": 0.1,
        },
    }
    try:
        import urllib.request
        data = json.dumps(payload).encode()
        req = urllib.request.Request(OLLAMA_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        log(f"LLM query failed: {e}")
        return None


def _get_memory_stats() -> Dict:
    """Get current memory counts from SQLite."""
    try:
        reader = db.reader()
        hot = reader.execute(
            "SELECT COUNT(*) FROM Memory_Hot"
        ).fetchone()[0]
        warm = reader.execute(
            "SELECT COUNT(*) FROM Memory_Warm"
        ).fetchone()[0]
        cold = reader.execute(
            "SELECT COUNT(*) FROM Memory_Cold"
        ).fetchone()[0]
        return {"hot": hot, "warm": warm, "cold": cold}
    except Exception as e:
        log(f"Memory stats error: {e}")
        return {"hot": 0, "warm": 0, "cold": 0}


def _check_health(stats: Dict) -> List[str]:
    """Check memory health and return alerts."""
    alerts = []
    if stats["warm"] > WARM_CAP * COMPACT_THRESHOLD:
        pct = int(stats["warm"] / WARM_CAP * 100)
        alerts.append(f"Warm memory at {pct}% ({stats['warm']}/{WARM_CAP})")
    if stats["hot"] > HOT_CAP * COMPACT_THRESHOLD:
        pct = int(stats["hot"] / HOT_CAP * 100)
        alerts.append(f"Hot memory at {pct}% ({stats['hot']}/{HOT_CAP})")
    return alerts


def _auto_compact() -> bool:
    """Trigger warm memory compaction via the memory manager."""
    try:
        # The manager's _update_warm_buffer prunes and deduplicates
        manager._update_warm_buffer()
        log("Auto-compact: warm memory pruned and deduplicated")
        return True
    except Exception as e:
        log(f"Auto-compact failed: {e}")
        return False


def _cold_distill() -> bool:
    """Run cold distillation using the tiny LLM for summarization."""
    try:
        from lib.cold_distiller import ColdDistiller
        d = ColdDistiller(min_confidence=0.3)
        stats = d.run()
        log(f"Cold distill: scanned={stats['scanned']} extracted={stats['extracted']}")
        return True
    except Exception as e:
        log(f"Cold distill failed: {e}")
        return False


def _llm_summarize() -> Optional[str]:
    """Use the tiny LLM to generate a memory health summary."""
    stats = _get_memory_stats()
    prompt = (
        f"Memory stats: {stats['hot']} hot entries, {stats['warm']} warm entries, "
        f"{stats['cold']} cold entries. "
        f"Warm cap is {WARM_CAP}, hot cap is {HOT_CAP}. "
        "Is the system healthy? Reply with one short sentence."
    )
    return _query_llm(prompt, system="You are a memory monitor. Be concise.")


def _heartbeat_loop(interval: int) -> None:
    """Main heartbeat loop."""
    log(f"Heartbeat started (interval: {interval}s, model: {DEFAULT_MODEL})")
    state = _load_state()
    has_llm = _check_ollama()
    log(f"Tiny LLM available: {has_llm}")

    while True:
        try:
            stats = _get_memory_stats()
            alerts = _check_health(stats)

            if alerts:
                for alert in alerts:
                    log(f"ALERT: {alert}")
                state["health_events"].append({
                    "time": datetime.now().isoformat(),
                    "alerts": alerts,
                })
                # Keep last 100 events
                state["health_events"] = state["health_events"][-100:]

                # Auto-compact if warm is near cap
                if stats["warm"] > WARM_CAP * COMPACT_THRESHOLD:
                    _auto_compact()
                    state["last_compact"] = datetime.now().isoformat()

                # Cold distill if we have warm data and haven't run recently
                last_distill = state.get("last_distill")
                if stats["warm"] > 100 and (
                    not last_distill or
                    (datetime.now() - datetime.fromisoformat(last_distill)).total_seconds() > 3600
                ):
                    _cold_distill()
                    state["last_distill"] = datetime.now().isoformat()

            # Periodic LLM health summary (every 10th tick)
            if has_llm and int(time.time()) % (interval * 10) < interval:
                summary = _llm_summarize()
                if summary:
                    log(f"LLM health: {summary}")

            _save_state(state)

        except Exception as e:
            log(f"Heartbeat error: {e}")

        time.sleep(interval)


def _start(interval: int) -> None:
    """Start the heartbeat daemon."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Heartbeat already running (pid {pid})")
            return
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    pid = os.fork()
    if pid > 0:
        # Parent
        PID_FILE.write_text(str(pid))
        print(f"Heartbeat started (pid {pid})")
        return

    # Child
    os.setsid()
    _heartbeat_loop(interval)


def _stop() -> None:
    """Stop the heartbeat daemon."""
    if not PID_FILE.exists():
        print("Heartbeat not running")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink()
        print(f"Heartbeat stopped (pid {pid})")
    except ProcessLookupError:
        PID_FILE.unlink()
        print("Heartbeat was not running (stale PID file removed)")
    except Exception as e:
        print(f"Error stopping heartbeat: {e}")


def _status() -> None:
    """Show heartbeat status."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            stats = _get_memory_stats()
            state = _load_state()
            print(f"Heartbeat: RUNNING (pid {pid})")
            print(f"  Memory: {stats['hot']} hot, {stats['warm']} warm, {stats['cold']} cold")
            print(f"  Last compact: {state.get('last_compact', 'never')}")
            print(f"  Last distill: {state.get('last_distill', 'never')}")
            print(f"  Events logged: {len(state.get('health_events', []))}")
            return
        except ProcessLookupError:
            PID_FILE.unlink(missing_ok=True)
    print("Heartbeat: STOPPED")


def _smoke() -> int:
    """Smoke test."""
    db.initialize()
    stats = _get_memory_stats()
    print(f"Memory stats: {stats}")

    has_llm = _check_ollama()
    print(f"Tiny LLM available: {has_llm}")

    if has_llm:
        summary = _llm_summarize()
        print(f"LLM health summary: {summary}")

    alerts = _check_health(stats)
    print(f"Alerts: {alerts}")

    print("heartbeat_daemon: OK")
    return 0


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    interval = DEFAULT_INTERVAL
    if len(sys.argv) > 2:
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg == "--interval" and i + 1 < len(sys.argv):
                interval = int(sys.argv[i + 1])

    db.initialize()

    if cmd == "start":
        _start(interval)
    elif cmd == "stop":
        _stop()
    elif cmd == "status":
        _status()
    elif cmd == "smoke":
        sys.exit(_smoke())
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
