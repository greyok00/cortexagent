#!/usr/bin/env python3
"""Supervisory FSM (spec 2026-11-11 §3.1) — the session state machine.

States: IDLE -> WORKING -> DEGRADED -> RECOVERING -> BLOCKED -> IDLE.
Transitions are the ONLY enforcement site; every edge is pure and
unit-testable (AgenticStateMachines pattern; MetaAgent validation).

Failure classes F1-F4 per the self-healing paper (arXiv:2605.06737):
  F1 hallucination, F2 execution error, F3 reasoning inconsistency,
  F4 workflow propagation. Infra classes (model/lane down, storms)
  ride under F2/infra exactly as heal.py already actions them.
"""
from __future__ import annotations
import json, os, time

IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED = (
    "IDLE", "WORKING", "DEGRADED", "RECOVERING", "BLOCKED")

# Exhaustive, explicit, no hidden paths.
TRANSITIONS = {
    (IDLE, "task_started"): WORKING,
    (WORKING, "detector_fire"): DEGRADED,
    (WORKING, "task_ended"): IDLE,
    (DEGRADED, "ladder_act"): RECOVERING,
    (DEGRADED, "recovered_naturally"): WORKING,
    (DEGRADED, "ladder_exhausted"): BLOCKED,
    (RECOVERING, "result_improved"): WORKING,
    (RECOVERING, "ladder_exhausted"): BLOCKED,
    (RECOVERING, "detector_fire"): DEGRADED,
    (BLOCKED, "owner_clear"): IDLE,
    (BLOCKED, "session_end"): IDLE,
}
VALID_STATES = {IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED}


class FSM:
    def __init__(self, state=IDLE):
        self.state = state if state in VALID_STATES else IDLE

    def fire(self, event: str) -> tuple[bool, str]:
        """Returns (ok, new_state). Unknown edges are NO-OPs by design:
        the supervisor never wedges the main loop (spec §8)."""
        key = (self.state, event)
        if key not in TRANSITIONS:
            return False, self.state
        self.state = TRANSITIONS[key]
        return True, self.state

    @property
    def can_enforce(self) -> bool:
        return self.state in (DEGRADED, RECOVERING)


# ---------- task ledger (spec §3.4) — OUTSIDE the model context ----------
LEDGER_PATH = os.path.expanduser(
    "~/cortex-agent/state/supervision/ledger.json")


class Ledger:
    """Per-task working-memory: actions, failures, why, forced alternatives.
    Survives compaction by construction (file-backed, not context)."""

    def __init__(self, path=LEDGER_PATH):
        self.path = path
        self.task_id = None
        self.actions: list[dict] = []
        self.failures: list[dict] = []
        self.alternatives: dict[str, str] = {}

    def start_task(self, task_id: str):
        self.task_id = task_id
        self.actions: list = []
        self.failures: list = []
        self.alternatives: dict = {}
        self._flush()

    def record_action(self, tool: str, digest: str, ok: bool, why: str = ""):
        self.actions.append({"tool": tool, "digest": digest, "ok": ok,
                             "why": why[:200], "ts": time.time()})
        if len(self.actions) > 200:
            self.actions = self.actions[-100:]
        self._flush()

    def record_failure(self, fclass: str, detail: str, detector: str):
        self.failures.append({"class": fclass, "detail": detail[:200],
                              "detector": detector, "ts": time.time()})
        self._flush()

    def forbid(self, action_class: str, reason: str):
        """Ladder node 2: the failing action class is recorded as forbidden
        for THIS task, with the ledger citation the prose rule requires."""
        self.alternatives[action_class] = reason
        self._flush()

    def is_forbidden(self, action_class: str) -> bool:
        return action_class in self.alternatives

    def summary(self) -> dict:
        ok = sum(1 for a in self.actions if a.get("ok"))
        return {"task": self.task_id, "actions": len(self.actions),
                "ok": ok, "failures": len(self.failures),
                "forbidden": dict(self.alternatives)}

    def _flush(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.summary() | {"actions_tail": self.actions[-40:],
                                            "failures": self.failures[-40:]}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass  # never wedge the loop for ledger I/O (spec §8)
