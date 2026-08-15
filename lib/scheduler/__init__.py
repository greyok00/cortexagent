#!/usr/bin/env python3
"""lib/scheduler/__init__.py — Scheduler package for CortexAgent.

Event-sourced NDJSON scheduler backed by CortexLLM file persistence model.
Single-writer: only the overseer process may mutate scheduler state.

Schema:
  tasks.json          ← canonical snapshot (atomic replace)
  tasks.events.jsonl  ← immutable event log (append-only NDJSON)
  executions.jsonl    ← execution receipts (append-only NDJSON)
  state.json          ← cursor/checkpoint (generation, schema_version)
  lock                ← POSIX single-instance lock (fcntl)

Usage:
  from lib.scheduler import Store
  store = Store()
  receipt = store.create(title="backup", kind="user", trigger="cron",
                         schedule_value="0 9 * * *", payload_type="command",
                         payload={"command": "rsync /home /backup"})
  store.pause(receipt["id"])
  store.list()
  store.reconcile()
"""
from .store import Store
from .recovery import Recovery
from .ui import SchedulerUI

__all__ = ["Store", "Recovery", "SchedulerUI"]
__version__ = "1.0.0"
