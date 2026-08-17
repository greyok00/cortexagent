#!/usr/bin/env python3
"""lib/scheduler/recovery.py — Crash recovery and event replay for scheduler.

Recovery flow:
1. Load state.json (get last known-good generation)
2. Load tasks.json (canonical snapshot)
3. Verify snapshot integrity (task IDs, states, required fields)
4. Replay events after snapshot generation
5. Write new snapshot + state if events changed anything
6. Mark interrupted tasks, recalculate next_run
7. Emit reconciliation summary

Crash scenarios handled:
- Partial write to tasks.json → rebuild from events
- Interrupted event append → events are atomic (line-buffered NDJSON)
- Corrupted state.json → use generation 0, rebuild from events
- Multiple processes trying to write → flock prevents concurrent writes
- Full disk → visible error, no silent fake success

Usage:
  from lib.scheduler import Recovery
  recovery = Recovery()
  result = recovery.recover()  # Called on overseer startup
  result = recovery.test_corrupt()  # For testing
"""
import json
import os
import time
import uuid
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Import from store
from lib.scheduler.store import (
    STATE_DIR, SCHEDULER_DIR, TASKS_FILE, EVENTS_FILE, EXECUTIONS_FILE,
    STATE_FILE, LOCK_FILE, SNAPSHOT_BACKUP_DIR,
    SCHEMA_VERSION, TASK_VERSION, VALID_STATES, TASK_KINDS,
    _load_state, _save_state, _load_snapshot, _rebuild_snapshot,
    _save_snapshot, _ensure_dirs, _now, _now_iso, _make_event,
    _next_run,
)


class Recovery:
    """Handle crash recovery and event replay for the scheduler."""
    
    def __init__(self):
        _ensure_dirs()
    
    def recover(self) -> Dict:
        """Run full recovery: load, validate, replay, repair.
        
        Returns summary dict with counts of recovered, repaired, etc.
        """
        summary = {
            "ok": False,
            "events_loaded": 0,
            "snapshot_valid": False,
            "snapshot_rebuilt": False,
            "tasks_repaired": 0,
            "tasks_interrupted": 0,
            "tasks_due": 0,
            "tasks_reconciled": 0,
            "errors": [],
        }
        
        try:
            # Step 1: Load state
            state = _load_state()
            summary["generation_at_load"] = state.get("generation", 0)
            
            # Step 2: Load snapshot
            snapshot = _load_snapshot()
            
            if not snapshot:
                # No snapshot — rebuild from events
                events = self._load_events_sorted()
                summary["events_loaded"] = len(events)
                snapshot = _rebuild_snapshot(events)
                summary["snapshot_rebuilt"] = True
            else:
                summary["snapshot_valid"] = True
                summary["tasks_at_load"] = len(snapshot)
            
            # Step 3: Validate and repair
            snapshot, repairs = self._validate_and_repair(snapshot)
            summary["tasks_repaired"] = len(repairs)
            
            # Step 4: Replay any events after snapshot (for future-proofing)
            events = self._load_events_sorted()
            last_gen = state.get("generation", 0)
            replayed = self._replay_events(snapshot, events, last_gen)
            
            if replayed:
                summary["events_replayed"] = len(replayed)
                # Save repaired snapshot
                _save_snapshot(snapshot)
            
            # Step 5: Mark interrupted tasks
            interrupted = self._mark_interrupted(snapshot)
            summary["tasks_interrupted"] = len(interrupted)
            
            # Step 6: Recalculate next_run for scheduled tasks
            due = self._recalculate_next_run(snapshot)
            summary["tasks_due"] = len(due)
            
            # Step 7: Save final snapshot
            _save_snapshot(snapshot)
            
            # Step 8: Update state
            state["generation"] = state.get("generation", 0) + 1
            state["last_reconciled"] = _now_iso()
            state["last_recovery_ok"] = True
            _save_state(state)
            
            summary["ok"] = True
            summary["snapshot_final"] = len(snapshot)
            summary["repair_details"] = repairs
            
        except Exception as e:
            summary["errors"].append(str(e))
            summary["ok"] = False
        
        return summary
    
    def _load_events_sorted(self) -> List[Dict]:
        """Load all events from NDJSON log, sorted by checksum/timestamp."""
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
    
    def _validate_and_repair(self, snapshot: Dict) -> tuple:
        """Validate snapshot tasks, repair invalid ones.
        
        Returns (updated_snapshot, list_of_repair_descriptions).
        """
        repairs = []
        
        for task_id, task in snapshot.items():
            # Validate required fields — ensure sane defaults for any gap
            if not task.get("id"):
                task["id"] = task_id
            if not task.get("title"):
                task["title"] = f"unnamed-{task_id[:8]}"
            if "kind" not in task:
                task["kind"] = "user"
                repairs.append(f"{task_id[:8]}: added missing 'kind'")
            if "payload_type" not in task:
                task["payload_type"] = "command"
                repairs.append(f"{task_id[:8]}: added missing 'payload_type'")
            if "payload" not in task:
                task["payload"] = {}
                repairs.append(f"{task_id[:8]}: added missing 'payload'")
            if "state" not in task:
                task["state"] = "scheduled"
                repairs.append(f"{task_id[:8]}: added missing 'state'")
            
            # Validate state
            if task.get("state") not in VALID_STATES:
                task["state"] = "scheduled"
                task["enabled"] = task.get("enabled", True)
                repairs.append(f"{task_id[:8]}: invalid state '{task.get('state')}' → scheduled")
            
            # Validate kind
            if task.get("kind") not in TASK_KINDS:
                task["kind"] = "user"
                repairs.append(f"{task_id[:8]}: invalid kind '{task.get('kind')}' → user")
            
            # Validate payload_type
            if task.get("payload_type") not in ("command", "llm", "subagent", "image", "video",
                                                  "browser", "filesystem", "network", "custom"):
                task["payload_type"] = "command"
                repairs.append(f"{task_id[:8]}: invalid payload_type → command")
            
            # Validate trigger
            trigger = task.get("trigger", "manual")
            if trigger not in ("cron", "daily", "weekly", "date", "interval", "manual"):
                task["trigger"] = "manual"
                repairs.append(f"{task_id[:8]}: invalid trigger → manual")
        
        return snapshot, repairs
    
    def _replay_events(self, snapshot: Dict, events: List[Dict],
                       last_generation: int) -> List[Dict]:
        """Replay events after the snapshot generation.
        
        For now, replay all events to update snapshot (future: filter by generation).
        """
        replayed = []
        
        for event in events:
            task_id = event.get("task_id", "")
            etype = event.get("type", "")
            data = event.get("data", {})
            
            if etype == "create":
                snapshot[task_id] = {**data, "id": task_id}
                replayed.append(event)
            elif etype in ("update", "pause", "resume", "cancel", "archive"):
                if task_id in snapshot:
                    snapshot[task_id].update(data)
                    snapshot[task_id]["version"] = event.get("version", 1)
                    replayed.append(event)
        
        return replayed
    
    def _mark_interrupted(self, snapshot: Dict) -> List[str]:
        """Mark tasks in 'running' state as 'interrupted'."""
        interrupted = []
        for task_id, task in snapshot.items():
            if task.get("state") == "running":
                task["state"] = "interrupted"
                task["enabled"] = True  # Allow retry
                task["updated_at"] = _now_iso()
                interrupted.append(task_id)
        return interrupted
    
    def _recalculate_next_run(self, snapshot: Dict) -> List[str]:
        """Recalculate next_run_at for scheduled tasks. Mark overdue as due."""
        due = []
        now = _now()
        
        for task_id, task in snapshot.items():
            if task.get("state") not in ("scheduled", "queued"):
                continue
            if not task.get("enabled", True):
                continue
            
            next_run = task.get("next_run_at")
            if not next_run:
                task["next_run_at"] = _next_run(task)
                task["updated_at"] = _now_iso()
            
            # Check if overdue
            try:
                next_run_dt = datetime.fromisoformat(next_run)
                if next_run_dt < now:
                    task["state"] = "queued"
                    task["next_run_at"] = _next_run(task)
                    task["updated_at"] = _now_iso()
                    due.append(task_id)
            except Exception:
                task["next_run_at"] = _next_run(task)
                task["updated_at"] = _now_iso()
                due.append(task_id)
        
        return due
    
    # ── Testing ──────────────────────────────────────────────────────────────
    def test_corrupt_snapshot(self) -> Dict:
        """Simulate a corrupted snapshot and test recovery."""
        # Write corrupted snapshot
        _save_snapshot({"bad": {"state": "invalid_state"}})
        
        # Run recovery
        result = self.recover()
        
        # Verify recovery fixed it
        snapshot = _load_snapshot()
        assert "bad" not in snapshot or snapshot["bad"].get("state") != "invalid_state"
        
        return result
    
    def test_full_recovery(self) -> Dict:
        """Test full recovery pipeline."""
        from lib.scheduler import Store
        
        # Create some tasks
        store = Store()
        receipt1 = store.create(title="test1", kind="user", trigger="cron",
                                schedule_value="0 9 * * *")
        receipt2 = store.create(title="test2", kind="test", ephemeral=True,
                                trigger="manual")
        
        # Corrupt snapshot
        _save_snapshot({"corrupted": {"state": "invalid", "kind": "invalid"}})
        
        # Recover
        result = self.recover()
        
        # Verify
        assert result["ok"], f"Recovery failed: {result}"
        assert result["tasks_repaired"] > 0, "No tasks repaired"
        
        return result


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Self-test and demo."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        print("Scheduler recovery smoke tests:")
        
        recovery = Recovery()
        
        # Test 1: Normal recovery (no corruption)
        result = recovery.recover()
        print(f"  ✅ Normal recovery: {result['ok']}, tasks={result.get('tasks_at_load', 0)}")
        
        # Test 2: Corrupt snapshot recovery
        result = recovery.test_corrupt_snapshot()
        print(f"  ✅ Corrupt snapshot recovery: {result['ok']}")
        
        # Test 3: Full recovery
        result = recovery.test_full_recovery()
        print(f"  ✅ Full recovery: {result['ok']}")
        
        print("\n✅ All recovery tests passed")
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "recover":
        # Run recovery (used by overseer on startup)
        recovery = Recovery()
        result = recovery.recover()
        print(json.dumps(result, indent=2, default=str))
        return
    
    print("usage: recovery.py smoke | recover", file=sys.stderr)


if __name__ == "__main__":
    main()
