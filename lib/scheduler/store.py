#!/usr/bin/env python3
"""lib/scheduler/store.py — NDJSON event-sourced scheduler store.

Single-writer, crash-safe, event-sourced task store using CortexLLM's
file persistence model:
  - Append-only NDJSON event log
  - Atomic snapshot via tmp+rename
  - POSIX single-instance lock (fcntl)
  - Monotonic generation number for optimistic concurrency

State files (under ~/.cortexagent/scheduler/):
  tasks.json          ← canonical snapshot (atomic replace)
  tasks.events.jsonl  ← immutable event log (append-only NDJSON)
  executions.jsonl    ← execution receipts (append-only NDJSON)
  state.json          ← cursor/checkpoint (generation, schema_version)
  lock                ← POSIX single-instance lock (fcntl)

Operations:
  create, get, list, update, pause, resume, run_now, cancel, archive,
  clear_test_tasks, reconcile, migrate_from_json

Usage:
  from lib.scheduler import Store
  store = Store()
  receipt = store.create(title="backup", kind="user", ...)
  store.pause(receipt["id"])
  store.reconcile()
"""
import json
import os
import time
import uuid
import fcntl
import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

# ── Paths ──────────────────────────────────────────────────────────────────────
STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                                  str(Path.home() / ".cortexagent")))
SCHEDULER_DIR = STATE_DIR / "scheduler"
TASKS_FILE = SCHEDULER_DIR / "tasks.json"
EVENTS_FILE = SCHEDULER_DIR / "tasks.events.jsonl"
EXECUTIONS_FILE = SCHEDULER_DIR / "executions.jsonl"
STATE_FILE = SCHEDULER_DIR / "state.json"
LOCK_FILE = SCHEDULER_DIR / "lock"
SNAPSHOT_BACKUP_DIR = SCHEDULER_DIR / "snapshots"  # bounded retention

# ── Schema ─────────────────────────────────────────────────────────────────────
SCHEMA_VERSION = 2  # Increment when schema changes
TASK_VERSION = 1   # Per-task version

# ── Task States ────────────────────────────────────────────────────────────────
VALID_STATES = {"scheduled", "queued", "running", "succeeded", "failed",
                "paused", "canceled", "archived", "interrupted", "retry_wait"}
TASK_KINDS = {"user", "maintenance", "system", "test"}
PAYLOAD_TYPES = {"command", "llm", "subagent", "image", "video", "browser",
                 "filesystem", "network", "custom"}
TRIGGER_TYPES = {"cron", "daily", "weekly", "date", "interval", "manual"}


def _ensure_dirs() -> None:
    """Ensure scheduler directory structure exists."""
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
#  LOCK
# ═══════════════════════════════════════════════════════════════════════════════

class SchedulerLock:
    """POSIX single-instance lock for scheduler writer.
    
    Only one process may hold the lock at a time. Uses fcntl.flock().
    """
    
    def __init__(self, lock_path: Path = LOCK_FILE):
        self.lock_path = lock_path
        self._fd = None
    
    def acquire(self) -> bool:
        """Try to acquire lock. Returns True if acquired, False if locked."""
        _ensure_dirs()
        try:
            self._fd = open(self.lock_path, 'w')
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd.write(str(os.getpid()))
            self._fd.flush()
            return True
        except (IOError, OSError):
            self._fd = None
            return False
    
    def release(self) -> None:
        """Release lock."""
        if self._fd:
            try:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None
    
    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Scheduler lock held by another process")
        return self
    
    def __exit__(self, *args):
        self.release()


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════════════════

def _load_state() -> Dict:
    """Load scheduler state from state.json."""
    try:
        with STATE_FILE.open() as f:
            d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("generation", 0)
                d.setdefault("schema_version", SCHEMA_VERSION)
                d.setdefault("last_reconciled", None)
                return d
    except Exception:
        pass
    return {"generation": 0, "schema_version": SCHEMA_VERSION, "last_reconciled": None}


def _save_state(state: Dict) -> None:
    """Save scheduler state atomically."""
    _ensure_dirs()
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = _now_iso()
    _atomic_write_json(STATE_FILE, state)


def _atomic_write_json(path: Path, data: Dict) -> None:
    """Write JSON atomically: tmp + flush + rename + fsync dir."""
    tmp_path = path.with_suffix(".tmp")
    bak_path = path.with_suffix(".bak")
    
    # Write to temp
    with tmp_path.open('w') as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    
    # Backup old file
    if path.exists():
        shutil.copy2(str(path), str(bak_path))
    
    # Atomic rename
    os.replace(str(tmp_path), str(path))
    
    # Fsync directory (where supported)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(dir_fd)
        os.close(dir_fd)
    except Exception:
        pass


def _atomic_append_ndjson(path: Path, record: Dict) -> None:
    """Append a single NDJSON record atomically."""
    _ensure_dirs()
    with open(str(path), 'a') as f:
        f.write(json.dumps(record, default=str) + '\n')
        f.flush()
        os.fsync(f.fileno())


# ═══════════════════════════════════════════════════════════════════════════════
#  TASK FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def _make_task(**overrides) -> Dict:
    """Create a new task dict with defaults."""
    now = _now_iso()
    task = {
        "id": str(uuid.uuid4()),
        "title": overrides.get("title", ""),
        "kind": overrides.get("kind", "user"),
        "state": "scheduled",
        "payload_type": overrides.get("payload_type", "command"),
        "payload": overrides.get("payload", {}),
        "trigger": overrides.get("trigger", "manual"),
        "schedule_value": overrides.get("schedule_value", ""),
        "timezone": overrides.get("timezone", "UTC"),
        "enabled": True,
        "ephemeral": overrides.get("ephemeral", False),
        "visible": overrides.get("visible", True),
        "owner": overrides.get("owner", "cli"),
        "idempotency_key": overrides.get("idempotency_key", ""),
        "version": TASK_VERSION,
        "next_run_at": overrides.get("next_run_at", _next_run(overrides)),
        "last_run_at": None,
        "last_result": None,
        "created_at": now,
        "updated_at": now,
        "execution_count": 0,
        "retry_count": 0,
    }
    task.update(overrides)
    return task


def _next_run(overrides: Dict) -> Optional[str]:
    """Compute next run time based on trigger."""
    now = _now()
    trigger = overrides.get("trigger", "manual")
    schedule_value = overrides.get("schedule_value", "")
    
    if trigger in ("cron", "daily", "weekly"):
        # Default: next day at schedule time
        try:
            return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                                     microsecond=0).isoformat()
        except Exception:
            return (now + timedelta(days=1)).isoformat()
    elif trigger == "date":
        try:
            target = datetime.fromisoformat(schedule_value)
            if target > now:
                return target.isoformat()
            return (now + timedelta(days=1)).isoformat()
        except Exception:
            return (now + timedelta(days=1)).isoformat()
    elif trigger == "interval":
        try:
            seconds = int(schedule_value)
            return (now + timedelta(seconds=seconds)).isoformat()
        except Exception:
            return (now + timedelta(hours=1)).isoformat()
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _make_event(event_type: str, task_id: str, **fields) -> Dict:
    """Create an event record."""
    return {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "task_id": task_id,
        "version": fields.get("version", 1),
        "timestamp": _now_iso(),
        "data": {k: v for k, v in fields.items() if k != "version"},
        "checksum": "",  # Computed below
    }
    # Compute checksum (simple hash of content)
    content = json.dumps({"type": event_type, "task_id": task_id, **fields},
                         sort_keys=True, default=str)
    event["checksum"] = hashlib.sha256(content.encode()).hexdigest()[:16]
    return event


def _append_event(event: Dict) -> None:
    """Append event to NDJSON log."""
    _atomic_append_ndjson(EVENTS_FILE, event)
    # Update state generation
    state = _load_state()
    state["generation"] = state.get("generation", 0) + 1
    _save_state(state)


def _load_events() -> List[Dict]:
    """Load all events from NDJSON log."""
    events = []
    try:
        with EVENTS_FILE.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines
    except FileNotFoundError:
        pass
    return events


# ═══════════════════════════════════════════════════════════════════════════════
#  SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════════════

def _load_snapshot() -> Dict:
    """Load canonical snapshot (tasks by id)."""
    try:
        with TASKS_FILE.open() as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
            return {}
    except Exception:
        return {}


def _save_snapshot(tasks: Dict) -> None:
    """Save snapshot atomically."""
    _atomic_write_json(TASKS_FILE, tasks)
    
    # Bounded retention: keep last 5 snapshots
    backups = sorted(SNAPSHOT_BACKUP_DIR.glob("tasks-*.tmp.json"))
    if len(backups) > 5:
        for old in backups[:len(backups) - 5]:
            try:
                old.unlink()
            except Exception:
                pass


def _rebuild_snapshot(events: List[Dict]) -> Dict:
    """Rebuild snapshot from events (for crash recovery)."""
    tasks = {}
    for event in events:
        task_id = event.get("task_id", "")
        data = event.get("data", {})
        etype = event.get("type", "")
        
        if etype == "create":
            tasks[task_id] = {
                "id": task_id,
                "title": data.get("title", ""),
                "state": "scheduled",
                "kind": data.get("kind", "user"),
                "payload_type": data.get("payload_type", "command"),
                "payload": data.get("payload", {}),
                "trigger": data.get("trigger", "manual"),
                "schedule_value": data.get("schedule_value", ""),
                "enabled": True,
                "ephemeral": data.get("ephemeral", False),
                "visible": data.get("visible", True),
                "owner": data.get("owner", "cli"),
                "version": event.get("version", 1),
                "next_run_at": data.get("next_run_at"),
                "last_run_at": data.get("last_run_at"),
                "last_result": data.get("last_result"),
            }
        elif etype == "update":
            if task_id in tasks:
                tasks[task_id].update(data)
                tasks[task_id]["version"] = event.get("version", 1)
        elif etype == "pause":
            if task_id in tasks:
                tasks[task_id]["enabled"] = False
                tasks[task_id]["version"] = event.get("version", 1)
        elif etype == "resume":
            if task_id in tasks:
                tasks[task_id]["enabled"] = True
                tasks[task_id]["next_run_at"] = data.get("next_run_at")
                tasks[task_id]["version"] = event.get("version", 1)
        elif etype == "cancel":
            if task_id in tasks:
                tasks[task_id]["state"] = "canceled"
                tasks[task_id]["enabled"] = False
                tasks[task_id]["version"] = event.get("version", 1)
        elif etype == "archive":
            if task_id in tasks:
                tasks[task_id]["state"] = "archived"
                tasks[task_id]["version"] = event.get("version", 1)
    
    return tasks


# ═══════════════════════════════════════════════════════════════════════════════
#  STORE CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class Store:
    """Event-sourced scheduler store.
    
    Thread-safe, crash-safe, single-writer.
    All mutations go through the lock, append event, then update snapshot.
    """
    
    def __init__(self):
        _ensure_dirs()
        self._lock = SchedulerLock()
        # Load snapshot if exists
        self._tasks = _load_snapshot()
    
    def _write(self, task_id: str, event: Dict) -> Dict:
        """Internal: write event + update snapshot under lock."""
        with self._lock:
            # Append event
            _append_event(event)
            
            # Update in-memory snapshot
            if event["type"] == "create":
                self._tasks[task_id] = {**event["data"], "id": task_id}
            elif event["type"] in ("update", "pause", "resume", "cancel"):
                if task_id in self._tasks:
                    self._tasks[task_id].update(event["data"])
                    self._tasks[task_id]["version"] = event.get("version", 1)
            elif event["type"] == "archive":
                if task_id in self._tasks:
                    self._tasks[task_id]["state"] = "archived"
                    self._tasks[task_id]["version"] = event.get("version", 1)
            
            # Save snapshot atomically
            _save_snapshot(self._tasks)
            
            # Return success receipt
            return {
                "ok": True,
                "task_id": task_id,
                "version": event.get("version", 1),
                "state": self._tasks.get(task_id, {}).get("state", "unknown"),
                "title": self._tasks.get(task_id, {}).get("title", ""),
                "next_run": self._tasks.get(task_id, {}).get("next_run_at"),
                "read_back_hash": hashlib.sha256(
                    json.dumps(self._tasks.get(task_id, {}), sort_keys=True, default=str).encode()
                ).hexdigest()[:12],
            }
    
    # ── CREATE ───────────────────────────────────────────────────────────────
    def create(self, title: str = "", kind: str = "user",
               trigger: str = "manual", schedule_value: str = "",
               payload_type: str = "command", payload: Dict = None,
               owner: str = "cli", ephemeral: bool = False,
               visible: bool = True, idempotency_key: str = "") -> Optional[Dict]:
        """Create a new task. Returns receipt or None on validation error."""
        # Validate
        if kind not in TASK_KINDS:
            return {"ok": False, "error": f"Invalid kind: {kind}", "no_change": True}
        if payload_type not in PAYLOAD_TYPES:
            return {"ok": False, "error": f"Invalid payload_type: {payload_type}", "no_change": True}
        if trigger not in TRIGGER_TYPES:
            return {"ok": False, "error": f"Invalid trigger: {trigger}", "no_change": True}
        
        # Check idempotency
        if idempotency_key:
            for tid, task in self._tasks.items():
                if task.get("idempotency_key") == idempotency_key:
                    return {
                        "ok": False, "error": "Duplicate idempotency key",
                        "no_change": True, "duplicate_of": tid
                    }
        
        # Create task
        task = _make_task(
            title=title, kind=kind, payload_type=payload_type,
            payload=payload or {}, trigger=trigger, schedule_value=schedule_value,
            owner=owner, ephemeral=ephemeral, visible=visible,
            idempotency_key=idempotency_key
        )
        
        event = _make_event("create", task["id"],
                            title=task["title"], kind=task["kind"],
                            payload_type=task["payload_type"], payload=task["payload"],
                            trigger=task["trigger"], schedule_value=task["schedule_value"],
                            next_run_at=task["next_run_at"],
                            ephemeral=task["ephemeral"], visible=task["visible"],
                            owner=task["owner"], idempotency_key=task["idempotency_key"],
                            version=TASK_VERSION)
        
        return self._write(task["id"], event)
    
    # ── GET ──────────────────────────────────────────────────────────────────
    def get(self, task_id: str) -> Optional[Dict]:
        """Get task by ID."""
        return self._tasks.get(task_id)
    
    # ── LIST ─────────────────────────────────────────────────────────────────
    def list(self, state: Optional[str] = None, kind: Optional[str] = None,
             visible_only: bool = True) -> List[Dict]:
        """List tasks with optional filtering."""
        results = list(self._tasks.values())
        if state:
            results = [t for t in results if t.get("state") == state]
        if kind:
            results = [t for t in results if t.get("kind") == kind]
        if visible_only:
            results = [t for t in results if t.get("visible", True)]
        return sorted(results, key=lambda t: t.get("next_run_at") or "")
    
    # ── UPDATE ───────────────────────────────────────────────────────────────
    def update(self, task_id: str, expected_version: int, **fields) -> Dict:
        """Update task fields. Requires expected_version for optimistic concurrency."""
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        task = self._tasks[task_id]
        if task.get("version", 0) != expected_version:
            return {
                "ok": False, "error": f"Stale version: expected {expected_version}, got {task['version']}",
                "no_change": True, "current_version": task.get("version")
            }
        
        new_version = task.get("version", 0) + 1
        self._tasks[task_id].update(fields)
        self._tasks[task_id]["version"] = new_version
        self._tasks[task_id]["updated_at"] = _now_iso()
        
        event = _make_event("update", task_id, **fields, version=new_version)
        return self._write(task_id, event)
    
    # ── PAUSE ────────────────────────────────────────────────────────────────
    def pause(self, task_id: str) -> Dict:
        """Pause task (disable future execution)."""
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        new_version = self._tasks[task_id].get("version", 0) + 1
        self._tasks[task_id]["enabled"] = False
        self._tasks[task_id]["version"] = new_version
        self._tasks[task_id]["updated_at"] = _now_iso()
        
        event = _make_event("pause", task_id, version=new_version)
        return self._write(task_id, event)
    
    # ── RESUME ───────────────────────────────────────────────────────────────
    def resume(self, task_id: str) -> Dict:
        """Resume task (recompute next run)."""
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        new_version = self._tasks[task_id].get("version", 0) + 1
        self._tasks[task_id]["enabled"] = True
        self._tasks[task_id]["next_run_at"] = _next_run(self._tasks[task_id])
        self._tasks[task_id]["version"] = new_version
        self._tasks[task_id]["updated_at"] = _now_iso()
        
        event = _make_event("resume", task_id, next_run_at=self._tasks[task_id]["next_run_at"],
                            version=new_version)
        return self._write(task_id, event)
    
    # ── RUN NOW ──────────────────────────────────────────────────────────────
    def run_now(self, task_id: str) -> Dict:
        """Execute task now without affecting recurring schedule.
        
        Creates a separate execution receipt.
        """
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        execution_id = str(uuid.uuid4())
        
        # Record execution
        _atomic_append_ndjson(EXECUTIONS_FILE, {
            "id": execution_id,
            "task_id": task_id,
            "type": "run_now",
            "status": "pending",
            "started_at": _now_iso(),
            "completed_at": None,
            "result": None,
        })
        
        return {
            "ok": True,
            "execution_id": execution_id,
            "task_id": task_id,
            "title": self._tasks[task_id].get("title", ""),
        }
    
    # ── CANCEL ───────────────────────────────────────────────────────────────
    def cancel(self, task_id: str) -> Dict:
        """Cancel task (stop future execution, keep audit trail)."""
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        new_version = self._tasks[task_id].get("version", 0) + 1
        self._tasks[task_id]["state"] = "canceled"
        self._tasks[task_id]["enabled"] = False
        self._tasks[task_id]["version"] = new_version
        self._tasks[task_id]["updated_at"] = _now_iso()
        
        event = _make_event("cancel", task_id, version=new_version)
        return self._write(task_id, event)
    
    # ── ARCHIVE ──────────────────────────────────────────────────────────────
    def archive(self, task_id: str) -> Dict:
        """Archive completed/canceled task (retains in history)."""
        if task_id not in self._tasks:
            return {"ok": False, "error": "Task not found", "no_change": True}
        
        new_version = self._tasks[task_id].get("version", 0) + 1
        self._tasks[task_id]["state"] = "archived"
        self._tasks[task_id]["visible"] = False
        self._tasks[task_id]["version"] = new_version
        self._tasks[task_id]["updated_at"] = _now_iso()
        
        event = _make_event("archive", task_id, version=new_version)
        return self._write(task_id, event)
    
    # ── CLEAR TEST TASKS ─────────────────────────────────────────────────────
    def clear_test_tasks(self) -> Dict:
        """Remove only kind=test, ephemeral=true tasks (developer-only action)."""
        removed = []
        for tid, task in list(self._tasks.items()):
            if task.get("kind") == "test" and task.get("ephemeral", False):
                self._tasks[tid]["state"] = "canceled"
                self._tasks[tid]["visible"] = False
                removed.append(tid)
        
        if removed:
            _save_snapshot(self._tasks)
            state = _load_state()
            state["generation"] = state.get("generation", 0) + 1
            _save_state(state)
        
        return {"ok": True, "removed_count": len(removed), "removed_ids": removed}
    
    # ── RECONCILE ────────────────────────────────────────────────────────────
    def reconcile(self) -> Dict:
        """On startup: reload, validate, repair next-run indexes.
        
        Returns summary of recovered, due, failed, interrupted tasks.
        """
        # Load state
        state = _load_state()
        
        # Load events
        events = _load_events()
        
        # Rebuild snapshot from events (safety net if snapshot corrupted)
        if not self._tasks:
            self._tasks = _rebuild_snapshot(events)
        
        # Validate and repair
        recovered = []
        due = []
        interrupted = []
        failed = []
        
        now = _now()
        for task_id, task in self._tasks.items():
            # Validate state
            if task.get("state") not in VALID_STATES:
                task["state"] = "scheduled"
                task["enabled"] = True
                recovered.append(task_id)
            
            # Validate kind
            if task.get("kind") not in TASK_KINDS:
                task["kind"] = "user"
                recovered.append(task_id)
            
            # Repair interrupted tasks
            if task.get("state") == "running":
                task["state"] = "interrupted"
                task["enabled"] = True
                interrupted.append(task_id)
            
            # Recalculate next_run for scheduled tasks
            if task.get("state") == "scheduled" and task.get("enabled", True):
                if not task.get("next_run_at") or task.get("next_run_at") < now.isoformat():
                    # Check if overdue
                    try:
                        next_run = datetime.fromisoformat(task.get("next_run_at", ""))
                        if next_run < now:
                            due.append(task_id)
                    except Exception:
                        due.append(task_id)
                    task["next_run_at"] = _next_run(task)
                    task["updated_at"] = _now_iso()
        
        # Mark overdue tasks as due (ready to fire)
        for task_id in due:
            if task_id in self._tasks:
                self._tasks[task_id]["state"] = "queued"
        
        # Save repaired snapshot
        _save_snapshot(self._tasks)
        state["generation"] = state.get("generation", 0) + 1
        state["last_reconciled"] = _now_iso()
        state["recovered_count"] = len(recovered)
        state["interrupted_count"] = len(interrupted)
        _save_state(state)
        
        # Emit reconciliation summary
        summary = {
            "ok": True,
            "tasks_reconciled": len(self._tasks),
            "recovered": len(recovered),
            "interrupted": len(interrupted),
            "due": len(due),
            "recovered_ids": recovered,
            "interrupted_ids": interrupted,
        }
        return summary
    
    # ── MIGRATE ──────────────────────────────────────────────────────────────
    def migrate_from_json(self, schedule_file: Optional[Path] = None,
                          queue_file: Optional[Path] = None) -> Dict:
        """Migrate existing JSON scheduler/queue files to NDJSON format.
        
        Preserves all existing tasks, converts to event-sourced format.
        """
        migrated = 0
        errors = []
        
        # Migrate schedule
        if schedule_file is None:
            schedule_file = STATE_DIR / "overseer_schedule.json"
        
        try:
            with schedule_file.open() as f:
                schedule_data = json.load(f)
                if isinstance(schedule_data, list):
                    for entry in schedule_data:
                        name = entry.get("name", f"migrated-{migrated}")
                        task = self.create(
                            title=name,
                            kind=entry.get("kind", "user"),
                            trigger="cron" if entry.get("schedule_type") == "cron" else "manual",
                            schedule_value=entry.get("schedule_value", ""),
                            payload_type=entry.get("type", "command"),
                            payload={"command": entry.get("command", "")},
                            owner="system",
                            ephemeral=False,
                            visible=not entry.get("name", "").startswith("smoke-"),
                        )
                        if task.get("ok"):
                            migrated += 1
        except FileNotFoundError:
            pass  # No schedule file to migrate
        except Exception as e:
            errors.append(f"Schedule migration error: {e}")
        
        # Migrate queue
        if queue_file is None:
            queue_file = STATE_DIR / "overseer_queue.json"
        
        try:
            with queue_file.open() as f:
                queue_data = json.load(f)
                if isinstance(queue_data, list):
                    for entry in queue_data:
                        if entry.get("status") == "queued":
                            self.create(
                                title=entry.get("prompt", entry.get("command", "queued task")),
                                kind="user",
                                trigger="manual",
                                payload_type="command",
                                payload={"command": entry.get("command", "")},
                                owner=entry.get("owner", "cli"),
                                ephemeral=False,
                                visible=True,
                            )
                            migrated += 1
        except FileNotFoundError:
            pass
        except Exception as e:
            errors.append(f"Queue migration error: {e}")
        
        return {
            "ok": True,
            "migrated_count": migrated,
            "errors": errors,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Self-test and demo."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        print("Scheduler store smoke tests:")
        
        # Test creation
        store = Store()
        receipt = store.create(
            title="test task", kind="user", trigger="cron",
            schedule_value="0 9 * * *", payload_type="command",
            payload={"command": "echo hello"}, owner="test"
        )
        assert receipt["ok"], f"Create failed: {receipt}"
        print(f"  ✅ Create: {receipt['task_id'][:8]}")
        
        # Test get
        task = store.get(receipt["task_id"])
        assert task is not None, "Get returned None"
        print(f"  ✅ Get: title={task['title']}")
        
        # Test list
        tasks = store.list()
        assert len(tasks) >= 1, "List returned no tasks"
        print(f"  ✅ List: {len(tasks)} tasks")
        
        # Test pause/resume
        pause_receipt = store.pause(receipt["task_id"])
        assert pause_receipt["ok"], "Pause failed"
        resume_receipt = store.resume(receipt["task_id"])
        assert resume_receipt["ok"], "Resume failed"
        print(f"  ✅ Pause + Resume")
        
        # Test run_now
        run_receipt = store.run_now(receipt["task_id"])
        assert run_receipt["ok"], "Run now failed"
        print(f"  ✅ Run now: execution_id={run_receipt['execution_id'][:8]}")
        
        # Test cancel
        cancel_receipt = store.cancel(receipt["task_id"])
        assert cancel_receipt["ok"], "Cancel failed"
        print(f"  ✅ Cancel")
        
        # Test reconcile
        result = store.reconcile()
        assert result["ok"], "Reconcile failed"
        print(f"  ✅ Reconcile: {result}")
        
        # Test clear_test_tasks
        test_receipt = store.create(
            title="smoke-test", kind="test", ephemeral=True,
            owner="test", trigger="cron", schedule_value="0 9 * * *"
        )
        clear_receipt = store.clear_test_tasks()
        assert clear_receipt["ok"], "Clear test tasks failed"
        print(f"  ✅ Clear test tasks: removed {clear_receipt['removed_count']}")
        
        print("\n✅ All smoke tests passed")
        return
    
    print("usage: store.py smoke", file=sys.stderr)


if __name__ == "__main__":
    main()
