#!/usr/bin/env python3
"""Supervisory core (spec 2026-11-11) — FSM + tier-1 detectors + escalation
ladder + ledger, folding heal.py (infra ref lexes) and watch.py (incidents)
into ONE state machine that tracks state instead of firing scattered reflexes.

Wire contract (consumed by the runtime's event pump):
  supervisor.on_event(ev)  — one dict per observable:
    {"kind": "tool_call", "tool": ..., "args": ..., "digest": ...}
    {"kind": "tool_result", "tool": ..., "error": bool, "result_hash": ...}
    {"kind": "model_turn", "tokens": n}
    {"kind": "stop_reason", "reason": "end"|"length"|...}
    {"kind": "refusal", "reason_family": "gate"|"guard"|...}
    {"kind": "task_started", "task": "..."} | {"kind": "task_ended"}
  supervisor.decisions — list of prose decisions since last drain (the TUI
    pumps these through the supervised-steer channel; §5 prose rule).

PROSE RULE (§3.5): every steering/blocking string is one plain sentence.
No error codes, no exception objects, ever.

CANNOT-FAIL (§8): on_event never raises; internal errors degrade the
supervisor to observe-only and log to supervision.log.
"""
from __future__ import annotations
import collections
import hashlib
import json
import os
import sys
import time
import typing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fsm import FSM, Ledger, IDLE, WORKING, DEGRADED, RECOVERING, BLOCKED
from detectors import (STRUCTURED_TOOLS, args_conform, error_burst,
                       one_token_storm, refusal_repeat, repetition_tool_loop,
                       length_storm, _digest)

STATE = os.path.expanduser("~/cortex-agent/state/supervision")
STEER_FILE = os.path.join(STATE, "steer.jsonl")          # heal.py channel
SIDECAR_STREAM = os.path.join(STATE, "supervision_events.jsonl")
SUPERVISOR_LOG = os.path.join(STATE, "supervisor.log")
RULEBOOK = os.path.join(STATE, "rulebook.json")

DETACH = True  # rulebook-only enforcement; FSM/ladder code frozen from RRSI loop


def _load_rulebook() -> dict:
    """Declarative thresholds/live; committed defaults win if unreadable."""
    defaults = {
        "repetition_limit": 3,
        "storm_min_turns": 3,
        "error_burst_min": 4,
        "error_burst_window": 6,
        "refusal_repeat_limit": 3,
        "length_storm_limit": 3,
        "steer_effectiveness_max": 3,   # same lesson key re-fires → escalate
    }
    try:
        with open(RULEBOOK) as f:
            user = json.load(f)
        defaults.update({k: v for k, v in user.items() if isinstance(k, str)})
        defaults["provenance"] = user.get("provenance", "file rulebook")
    except FileNotFoundError:
        defaults["provenance"] = "in-tree defaults"
    except Exception:
        pass  # corrupt rulebook -> defaults; supervision survives
    return defaults


class LadderResult(typing.NamedTuple):
    node: int            # 1 steer lesson, 2 forced alternative, 3 cancel task,
    prose: str           # 4 respawn lane, 5 stop+surface
    fclass: str


class Supervisor:
    def __init__(self, task_id: str = "adhoc"):
        self.rb = _load_rulebook()
        self.fsm = FSM(IDLE)
        self.ledger = Ledger()
        self.task_id = task_id
        self.window: collections.deque = collections.deque(maxlen=40)
        self.steer_counts: dict[str, int] = collections.Counter()
        self.reliability = {"C": 1.0, "S": 1.0, "E": 1.0}  # ω-weighted proxy
        self.sidecar_ok = os.path.isdir(STATE)
        self.fsm.fire("task_started") if False else None  # starts IDLE
        self.observe_only = False
        self._armed_signature = None
        self._sig_count = collections.Counter()
        self._last_call_digest = None

    # ---------- event pump ----------
    def on_event(self, ev: dict):
        try:
            self._on_event(ev)
        except Exception as e:  # cannot-fail: observe-only degrade
            self.observe_only = True
            self._log(f"supervisor internal error → observe-only: {e}")

    def _on_event(self, ev: dict):
        kind = ev.get("kind")
        if kind == "task_started":
            self.task_id = str(ev.get("task") or "adhoc")[:80]
            self.ledger.start_task(self.task_id)
            self.fsm = FSM(WORKING)
        elif kind == "task_ended":
            if self.fsm.state != IDLE:
                self.fsm.fire("task_ended")
        self.window.append(ev)
        self.ledger.record_action(
            ev.get("tool", kind), ev.get("digest", ""), not ev.get("error"))

        # --- tier-1 detectors (pure, cost-ordered) ---
        det = (repetition_tool_loop(self.window, self.rb["repetition_limit"])
               or one_token_storm(self.window, self.rb["storm_min_turns"])
               or error_burst(self.window, self.rb["error_burst_min"],
                              self.rb["error_burst_window"])
               or refusal_repeat(self.window, self.rb["refusal_repeat_limit"])
               or length_storm(self.window, self.rb["length_storm_limit"]))

        # --- tier-2 CFG (pre-execution): every tool whose args we carry;
        # bash included (multiline/one-command grammar lives in args_conform,
        # the exec-gate still owns the live allowlist path) ---
        if kind == "tool_call" and ev.get("args") is not None:
            ok, why = args_conform(ev.get("tool") or "", ev.get("args") or {})
            if not ok:
                det = ("F1", why, "medium")  # malformed call pre-run

        # EDGE-TRIGGER + BUDGETED RE-FIRE: a standing condition escalates
        # once per `limit` new confirmations, not once per event and not
        # forever-suppressed. Round 2 of an identical loop = ladder node 2,
        # round 3 = node 3, matching the behavior-tree contract while
        # keeping one node per escalation (spec §3.3).
        if det and kind in ("tool_call", "tool_result", "model_turn",
                            "refusal", "stop_reason"):
            fclass, detail, severity = det
            sig = f"{fclass}:{detail[:48]}"
            self._sig_count[sig] += 1
            should_fire = (self._sig_count[sig] == 1
                           or (self._sig_count[sig] - 1) % max(
                               self.rb["repetition_limit"], 1) == 0)
            if should_fire:
                self._armed_signature = sig
                self._escalate(fclass, detail, severity, ev)
        else:
            # Pattern break is defined on TOOL_CALLS only: other event kinds
            # with det=None just mean "no condition for that kind" — clearing
            # there re-fired the ladder every half-round.
            if kind == "tool_call":
                d = ev.get("digest")
                if d != self._last_call_digest:
                    self._armed_signature = None
                    self._sig_count.clear()
                self._last_call_digest = d
        self._reliability_tick()
        self._sidecar_stream(ev, det)

    # ---------- escalation ladder (behavior tree, one node per firing) ----------
    def _escalate(self, fclass: str, detail: str, severity: str, ev: dict):
        # BLOCKED is terminal per task (set by node 5 only): surface ONCE,
        # then silence. After owner_clear / new_task the ladder re-arms.
        if self.fsm.state == BLOCKED:
            return
        # detector fires are legal from ANY live state: sessions stream
        # events before any task_started marker arrives.
        self.fsm.state = DEGRADED
        self.ledger.record_failure(fclass, detail, "tier1")
        key = f"{fclass}:{detail[:48]}"

        # ladder position = how many times THIS failure signature has fired
        # in the task. One node per firing, strictly ordered (spec §3.3).
        n = self.steer_counts[key]
        self.steer_counts[key] = n + 1
        if n < 1:
            # node 1 — steer lesson (plain prose the model can act on)
            prose = self._lesson(fclass, detail, ev)
            lres = LadderResult(1, prose, fclass)
        elif n < 2:
            # node 2 — forced alternative (ledger citation in prose)
            action_class = ev.get("tool") or ev.get("reason_family") or "the failing action"
            reason = f"already failed {fclass}: {detail}"
            self.ledger.forbid(action_class, reason)
            prose = (f"Stop using {action_class} for this task — it already "
                     f"failed ({detail}). Take a different approach.")
            lres = LadderResult(2, prose, fclass)
        elif n < 3:
            # node 3 — cancel task: command the turn to end (announced,
            # NOT blocked yet: node 4-5 exist because the model may ignore it)
            self.fsm.fire("ladder_act")
            prose = (f"Task cancelled by supervision: {detail}. "
                     "Report what is blocked to the owner and end the turn.")
            lres = LadderResult(3, prose, fclass)
        elif n < 4:
            # node 4 — respawn locked lane (heal.py's existing mechanism):
            # infra recovery for the lane the repetition may have wedged.
            self._heal_respawn(detail)
            prose = (f"This task still looped after cancellation ({detail}). "
                     "A recovery cycle is running; change approach now.")
            lres = LadderResult(4, prose, fclass)
        else:
            # node 5 — stop and surface: terminal BLOCKED for this task.
            self.fsm.fire("ladder_exhausted")
            prose = (f"Supervision halted this task after repeated failures "
                     f"(last: {detail}). Owner attention required.")
            lres = LadderResult(5, prose, fclass)
            self._log(f"LADDER-5 surface: {detail}")
        # node 1 is an advisory lesson: state stays DEGRADED (nothing is
        # "in flight"). Nodes 2-4 act → RECOVERING (node 3/5 already fired
        # their own edges in-branch; node 2 fires here).
        if lres.node == 2:
            self.fsm.fire("ladder_act")
        self._emit(lres.prose)
        self._log(f"LADDER-{lres.node} [{fclass}/{self.fsm.state}] "
                  f"{lres.prose[:90]}")

    def _lesson(self, fclass: str, detail: str, ev: dict) -> str:
        """Node 1: prose lesson keyed by failure class (readable, actionable)."""
        lessons = {
            "F1": f"That call was structurally invalid: {detail}. Fix the "
                  "arguments and retry once.",
            "F2": f"The last commands keep failing: {detail}. Change the "
                  "approach or write the steps into one script and run it once.",
            "F3": f"You repeated the same refused action: {detail}. Read the "
                  "earlier reason and do something different.",
            "F4": f"You are repeating identical work: {detail}. Do the "
                  "iteration in ONE command (shell loop to a file) or a "
                  "background subagent, then read the single result.",
        }
        return lessons.get(fclass, f"Supervision note: {detail}.")

    # ---------- sidecar stream + stats (spec §4: sidecar has NO authority) ----------
    def _sidecar_stream(self, ev: dict, det):
        if not self.sidecar_ok:
            return
        try:
            rec = {"ts": time.time(), "kind": ev.get("kind"), "state": self.fsm.state}
            if det:
                rec["detector"] = {"class": det[0], "detail": det[1][:120],
                                   "severity": det[2]}
            with open(SIDECAR_STREAM, "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            self.sidecar_ok = False  # sidecar death degrades to nothing (§8)
            self._log("sidecar stream lost — continuing observe-only")

    def _heal_respawn(self, detail: str):
        """Ladder node 4: reuse heal.py's lane restart (spec §3.3 node 4).
        Fire-and-forget systemctl; a failure here is only logged (§8)."""
        try:
            import subprocess
            subprocess.run(["systemctl", "--user", "restart",
                            "cortex-agent-lane.service"],
                           capture_output=True, timeout=20)
            self._log("LADDER-4 respawn cortex-agent-lane")
        except Exception as e:
            self._log(f"LADDER-4 respawn failed (logged only): {e}")

    def new_task(self, task_id: str):
        """Owner cleared (or new task): reset FSM + budgets (BLOCKED→IDLE)."""
        self.task_id = str(task_id)[:80]
        self.ledger.start_task(self.task_id)
        self.fsm = FSM(WORKING)
        self.steer_counts.clear()
        self._sig_count.clear()
        self._armed_signature = None
        self._last_call_digest = None
        self._log(f"new task {self.task_id} — ladder re-armed at node 1")

    def _reliability_tick(self):
        """R = ω1·C + ω2·S + ω3·E proxy over the current window (§3.2 tier 5)."""
        w = list(self.window)
        if not w:
            return
        errs = [r for r in w if r.get("kind") == "tool_result"]
        self.reliability["E"] = (sum(1 for r in errs if not r.get("error"))
                                 / len(errs)) if errs else 1.0
        unique = len({(r.get("tool"), r.get("digest")) for r in w
                      if r.get("kind") == "tool_call"})
        self.reliability["S"] = unique / max(len(w) // 2, 1) if w else 1.0
        self.reliability["S"] = min(1.0, self.reliability["S"])
        self.reliability["C"] = 1.0 if self.fsm.state in (WORKING, IDLE) else (
            0.5 if self.fsm.state == RECOVERING else 0.2)

    # ---------- outputs ----------
    def _emit(self, prose: str):
        """Real steering into the LIVE session (steer.jsonl channel) and
        recorded for drain()-pullers (decisions contract)."""
        self._pending = getattr(self, "_pending", [])
        self._pending.append(prose)
        try:
            with open(STEER_FILE, "a") as f:
                f.write(json.dumps({"ts": time.time(), "msg": prose}) + "\n")
        except OSError:
            self._log("steer write failed: " + prose[:80])

    @staticmethod
    def _log(msg: str):
        try:
            with open(SUPERVISOR_LOG, "a") as f:
                f.write(time.strftime("[%m-%d %H:%M:%S] ") + msg + "\n")
        except OSError:
            pass

    def drain(self) -> list[str]:
        """Steering issued since last drain (wiring contract: a pump may
        either rely on _emit's steer.jsonl channel or pull decisions here;
        both stay true because _emit appends AND records)."""
        out = getattr(self, "_pending", [])
        self._pending = []
        return out
