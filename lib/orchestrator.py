#!/usr/bin/env python3
"""orchestrator — task queue, calendar scheduler, and model orchestrator.

Combines the scheduler, model switcher, and a task queue into one system.
Handles long complex tasks that require multiple model switches.

Features:
  - Task queue: queue tasks, they run sequentially
  - Calendar: schedule tasks on specific dates, days of week, or cron
  - Model-aware: auto-switches between coding, image, and video models
  - Persistent: queue and schedule survive restarts

Usage:
  python3 orchestrator.py queue add "generate logo" --type image --prompt "a logo"
  python3 orchestrator.py queue add "make video" --type video --prompt "explainer"
  python3 orchestrator.py queue list
  python3 orchestrator.py queue clear

  python3 orchestrator.py schedule add --name "weekly images" --cron "0 9 * * 1" \
      --type image --prompt "weekly banner"
  python3 orchestrator.py schedule add --name "daily backup" --cron "0 2 * * *" \
      --type command --command "python3 lib/cold_distiller.py run"
  python3 orchestrator.py schedule list
  python3 orchestrator.py schedule remove --name "weekly images"

  python3 orchestrator.py daemon        # run the processing loop
  python3 orchestrator.py status
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

STATE_DIR = Path.home() / ".cortexagent" / "state"
QUEUE_FILE = STATE_DIR / "orchestrator_queue.json"
SCHEDULE_FILE = STATE_DIR / "orchestrator_schedule.json"
LOG_FILE = Path.home() / ".cortexagent" / "logs" / "orchestrator.log"

# ── Colors ────────────────────────────────────────────────────────────────
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
    line = f"{color}{emoji} {BOLD}orchestrator{RST} {DIM}{color}[{ts}]{RST} {color}{msg}{RST}"
    print(line, file=sys.stderr)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")


# ── Queue ──────────────────────────────────────────────────────────────────
def _load_queue() -> List[Dict]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except Exception:
            pass
    return []


def _save_queue(queue: List[Dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, default=str))


def queue_add(task_type: str, prompt: str = "", command: str = "",
              output: str = "", priority: int = 0) -> Dict:
    """Add a task to the queue."""
    queue = _load_queue()
    task = {
        "id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(queue)}",
        "type": task_type,  # "image", "video", "command"
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


# ── Schedule ───────────────────────────────────────────────────────────────
def _load_schedule() -> List[Dict]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return []


def _save_schedule(schedule: List[Dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2, default=str))


def _cron_matches(expr: str, now: datetime) -> bool:
    """Check if `now` matches a 5-field cron expression."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, mon, dow = fields
    values = [now.minute, now.hour, now.day, now.month, now.weekday()]
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
                 output: str = "") -> Dict:
    """Add a scheduled task."""
    schedule = _load_schedule()
    entry = {
        "name": name,
        "type": task_type,  # "image", "video", "command"
        "schedule_type": schedule_type,  # "cron", "daily", "weekly", "date"
        "schedule_value": schedule_value,
        "prompt": prompt,
        "command": command,
        "output": output,
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


# ── Task Execution ─────────────────────────────────────────────────────────
def _execute_task(task: Dict) -> bool:
    """Execute a single task. Returns True on success."""
    task_type = task.get("type", "command")
    prompt = task.get("prompt", "")
    command = task.get("command", "")
    output = task.get("output", "")

    _log(f"Running {task_type} task...", "▶️", MAGENTA)

    if task_type == "image":
        # Use model switcher for image generation
        from lib.model_switcher import gen_image
        return gen_image(prompt, output or f"output_{task['id']}.png")

    elif task_type == "video":
        # Use model switcher for video generation
        from lib.model_switcher import gen_video
        return gen_video(prompt, output or f"output_{task['id']}.mp4")

    elif task_type == "command":
        # Run a shell command
        try:
            result = subprocess.run(
                shlex.split(command), capture_output=True, text=True, timeout=3600
            )
            if result.returncode == 0:
                _log(f"Command succeeded: {command[:60]}", "✅", GREEN)
                return True
            else:
                _log(f"Command failed: {result.stderr[:200]}", "❌", RED)
                return False
        except Exception as e:
            _log(f"Command error: {e}", "❌", RED)
            return False

    return False


def _process_queue() -> None:
    """Process all queued tasks sequentially."""
    queue = _load_queue()
    pending = [t for t in queue if t["status"] == "queued"]
    if not pending:
        return

    _log(f"Processing {len(pending)} queued tasks...", "▶️", MAGENTA)

    for task in pending:
        task["status"] = "running"
        task["started_at"] = datetime.now().isoformat()
        _save_queue(queue)

        success = _execute_task(task)

        task["status"] = "completed" if success else "failed"
        task["completed_at"] = datetime.now().isoformat()
        task["result"] = "success" if success else "failed"
        _save_queue(queue)

        if success:
            _log(f"Task {task['id']} completed", "✅", GREEN)
        else:
            _log(f"Task {task['id']} failed", "❌", RED)


def _check_schedule() -> None:
    """Check scheduled tasks and queue any that are due."""
    now = datetime.now()
    schedule = _load_schedule()

    for entry in schedule:
        if not entry.get("enabled", True):
            continue

        should_run = False
        st = entry["schedule_type"]
        sv = entry["schedule_value"]

        if st == "cron":
            should_run = _cron_matches(sv, now)
        elif st == "daily":
            target_hour = int(sv.split(":")[0])
            target_min = int(sv.split(":")[1])
            should_run = (now.hour == target_hour and now.minute == target_min)
        elif st == "weekly":
            # "mon:09:00" = Monday at 9:00
            parts = sv.split(":")
            days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
            target_day = days.get(parts[0].lower(), -1)
            target_hour = int(parts[1])
            target_min = int(parts[2])
            should_run = (now.weekday() == target_day and
                         now.hour == target_hour and now.minute == target_min)
        elif st == "date":
            try:
                target = datetime.fromisoformat(sv)
                should_run = (now >= target and
                              (entry.get("last_run") is None or
                               datetime.fromisoformat(entry["last_run"]) < target))
            except Exception:
                pass

        if should_run:
            # Queue the scheduled task
            task = {
                "type": entry["type"],
                "prompt": entry.get("prompt", ""),
                "command": entry.get("command", ""),
                "output": entry.get("output", ""),
            }
            queue_add(task["type"], task["prompt"], task["command"], task["output"])
            entry["last_run"] = now.isoformat()
            _save_schedule(schedule)
            _log(f"Scheduled task '{entry['name']}' queued", "📅", GREEN)


# ── Daemon ─────────────────────────────────────────────────────────────────
def _daemon_loop(tick: int = 30) -> None:
    """Main daemon loop: check schedule, process queue, repeat."""
    _log("Orchestrator daemon started", "🚀", CYAN)
    _log(f"Checking every {tick}s", "⏱️", DIM)

    while True:
        try:
            _check_schedule()
            _process_queue()
        except Exception as e:
            _log(f"Daemon error: {e}", "❌", RED)
        time.sleep(tick)


# ── Status ─────────────────────────────────────────────────────────────────
def status() -> Dict:
    queue = _load_queue()
    schedule = _load_schedule()
    pending = len([t for t in queue if t["status"] == "queued"])
    running = len([t for t in queue if t["status"] == "running"])
    completed = len([t for t in queue if t["status"] == "completed"])
    failed = len([t for t in queue if t["status"] == "failed"])

    return {
        "queue": {"total": len(queue), "pending": pending, "running": running,
                  "completed": completed, "failed": failed},
        "schedule": {"total": len(schedule)},
    }


# ── CLI ────────────────────────────────────────────────────────────────────
def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "queue":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py queue <add|list|clear|remove> ...")
            return 1
        sub = sys.argv[2]
        if sub == "add":
            task_type = input("Task type (image/video/command): ") if len(sys.argv) < 4 else sys.argv[3]
            prompt = input("Prompt: ") if task_type in ("image", "video") and len(sys.argv) < 5 else ""
            command = input("Command: ") if task_type == "command" and len(sys.argv) < 5 else ""
            if len(sys.argv) >= 5:
                prompt = sys.argv[4] if task_type in ("image", "video") else ""
                command = sys.argv[4] if task_type == "command" else ""
            output = input("Output file: ") if len(sys.argv) < 6 else (sys.argv[5] if len(sys.argv) > 5 else "")
            queue_add(task_type, prompt, command, output)
        elif sub == "list":
            for t in queue_list():
                print(f"  [{t['status']}] {t['type']}: {t.get('prompt','')[:60] or t.get('command','')[:60]}")
        elif sub == "clear":
            queue_clear()
        elif sub == "remove":
            tid = sys.argv[3] if len(sys.argv) > 3 else ""
            queue_remove(tid)

    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: orchestrator.py schedule <add|list|remove> ...")
            return 1
        sub = sys.argv[2]
        if sub == "add":
            name = sys.argv[3] if len(sys.argv) > 3 else input("Name: ")
            task_type = sys.argv[4] if len(sys.argv) > 4 else input("Type (image/video/command): ")
            sched_type = sys.argv[5] if len(sys.argv) > 5 else input("Schedule type (cron/daily/weekly/date): ")
            sched_val = sys.argv[6] if len(sys.argv) > 6 else input("Schedule value: ")
            prompt = sys.argv[7] if len(sys.argv) > 7 else ""
            command = sys.argv[8] if len(sys.argv) > 8 else ""
            schedule_add(name, task_type, sched_type, sched_val, prompt, command)
        elif sub == "list":
            for s in schedule_list():
                status = "ON" if s.get("enabled", True) else "OFF"
                print(f"  [{status}] {s['name']}: {s['schedule_type']} {s['schedule_value']}")
        elif sub == "remove":
            name = sys.argv[3] if len(sys.argv) > 3 else input("Name: ")
            schedule_remove(name)

    elif cmd == "daemon":
        tick = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        _daemon_loop(tick)

    elif cmd == "status":
        s = status()
        q = s["queue"]
        print(f"Queue: {q['pending']} pending, {q['running']} running, "
              f"{q['completed']} done, {q['failed']} failed")
        print(f"Schedule: {s['schedule']['total']} entries")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
