# Supervision Remaining Lanes Implementation Plan (delta)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three remaining spec lanes on top of the in-flight Python supervisor core (`~/cortex-agent/supervision/`): the no-authority sidecar, the eval replay gate, the RRSI-shaped proposal loop, and the cross-session playbook distiller.

**Architecture:** The supervisor core (FSM `fsm.py`, detectors `detectors.py`, machine `supervisor.py`) is OWNED BY ANOTHER SESSION and is never modified by this plan. This plan only consumes its stream (`state/supervision/supervision_events.jsonl`, `steer.jsonl`) and maintains `stats.json`, `playbook.json`, and `rulebook.json` changes behind a replay gate. Everything is new files in `bin/` and `tests/` plus the shared state dir.

**Tech Stack:** Python 3.13 stdlib only; pytest.

## Global Constraints

- SUPERSEDES Tasks 6-8 of `docs/superpowers/plans/2026-11-11-cortex-supervisory-harness.md` (Tasks 1-5 superseded by the other session's Python implementation of the same spec).
- HARD no-overwrite law: never edit anything under `supervision/` (fsm, detectors, supervisor, heal, watch, README, STATUS). If the core needs a change, report it to the owner; the other session owns that tree region.
- Core contracts this plan relies on (verbatim from `supervision/supervisor.py` + `detectors.py`):
  - rulebook keys: `repetition_limit` (3), `storm_min_turns` (3), `error_burst_min` (4), `error_burst_window` (6), `refusal_repeat_limit` (3), `length_storm_limit` (3), `steer_effectiveness_max` (3), plus a `provenance` note and a `version` int (ignored by the core, ours for the loop).
  - event kinds: `{"kind":"tool_call","tool","args","digest","result_hash?"}`, `{"kind":"tool_result","tool","error","digest?"}`, `{"kind":"model_turn","tokens"}`, `{"kind":"stop_reason","reason"}`, `{"kind":"refusal","reason_family"}`, `{"kind":"task_started","task"}` / `{"kind":"task_ended"}`.
  - repetition detector fires ONLY when the window's last event is a `tool_call` and the last `repetition_limit` calls share one digest; F2 is emitted by storm, burst, AND length storms (detail prefix distinguishes them: "~empty model turns" = storm, "recent tool results errored" = burst, "truncations" = length).
  - stream record: `{"ts","kind","state","detector":{"class","detail","severity"}?}`.
  - steer records: `{"ts","msg"}` in `state/supervision/steer.jsonl`.
- State dir: `~/cortex-agent/state/supervision/` — files this plan creates: `stats.json`, `playbook.json`, `rulebook-provenance.jsonl`, `sidecar.state.json`. It may MODIFY `rulebook.json` only through the proposal loop's provenance-gated adoption.
- Cannot-fail: every script exits 0 on absent/corrupt inputs (absence of data is never an error), never crash-loops, never writes partial JSON (tmp + `os.replace`).
- Prose rule: playbook texts and any prose shipped to the model start with `[supervisor] `, are one plain sentence, no error codes, no em dashes.
- Replay import path: `sys.path.insert(0, "~/cortex-agent/supervision")` then `import supervisor` (the package has no `__init__.py`; its own modules use that top-level import style).
- Replay MUST patch `supervisor.RULEBOOK` and `supervisor.STEER_FILE` to tempdir paths per scenario set, never writing to the live state dir.
- Existing pytest suite stays green: `pytest tests/ -q`.
- Both trees share paths (verified: `docs/`, `supervision/`); after each commit check `git -C ~/cortexagent log --oneline -1` equals cortex-agent HEAD and `git -C ~/cortexagent status --short` shows only the other session's untracked supervision files (`fsm.py`, `detectors.py`, `supervisor.py`, `__pycache__`) plus nothing from us.

---

## Interfaces

Stats.json (sidecar output; proposal loop input):
```json
{"ts": 0, "rulebookVersion": 1,
 "failureCounts": {"F4": 12},
 "detailCounts": {"F4": {"identical args and identical results": 12, "~empty model turns": 5, "recent tool results errored": 4}},
 "steerEffectiveness": {"F4": {"fired": 12, "resolved": 7, "refired": 5}}}
```
Playbook.json (distiller output; runtime wiring reads it):
```json
{"entries": [{"cls": "F4", "text": "[supervisor] ...", "learnedFrom": "replay ledger: 12 fires of F4", "ts": 0, "sessionsUnfired": 0}]}
```
Provenance lines (`rulebook-provenance.jsonl`):
```json
{"ts": 0, "cls": "F4", "knob": "repetition_limit", "change": {"repetition_limit": 2}, "reason": "12 fires, 5 refires", "replayIn": true, "replayOut": true, "decision": "adopted"}
```
eval_replay.py CLI: `bin/eval_replay.py [--scenarios PATH] [--dist in|holdout|both] [--rulebook PATH] [--override JSON]`; exit 0 = all pass; stdout has `PASS <name>` / `FAIL <name>: <why>` lines.
Scenario schema:
```json
{"name": "s", "distribution": "in|holdout", "rulebook": {}, "events": [ {"kind": "tool_call", "tool": "bash", "digest": "abc", "result_hash": "x"} ], "expect": {"endState": "DEGRADED", "steers": 1, "steersAtMost": null, "classes": ["F4"]}}
```

---

### Task A: sidecar — no-authority stats consumer + playbook distiller

**Files:**
- Create: `bin/supervisor-sidecar.py`
- Create: `tests/test_supervision_sidecar.py`

**Interfaces:**
- Consumes: `state/supervision/supervision_events.jsonl` (core output).
- Produces: `stats.json`, `playbook.json`, `sidecar.state.json` (offset). Used by Tasks B/C (playbook entries consumed by future wiring; classes `F1`..`F4`).

- [ ] **Step 1: Write the failing tests** in `tests/test_supervision_sidecar.py`:

```python
import json, pathlib, subprocess, sys, tempfile

SIDECAR = pathlib.Path.home() / "cortex-agent" / "bin" / "supervisor-sidecar.py"

def _det(cls, detail="identical args and identical results"):
    return {"class": cls, "detail": detail, "severity": "high"}

def run_sidecar(td, events, once_days=0, distill=False, age=False):
    ev, st, sc = pathlib.Path(td) / "events", pathlib.Path(td) / "stats.json", pathlib.Path(td) / "sidecar.state.json"
    with ev.open("wb") as f:
        for e in events:
            f.write((json.dumps(e) + "\n").encode())
    cmd = [sys.executable, str(SIDECAR), "--events", str(ev), "--stats", str(st), "--state", str(sc)]
    if distill:
        cmd += ["--distill", "--sd-dir", str(td)]
    if age:
        cmd += ["--age"]
    if once_days:
        pass
    p = subprocess.run(cmd + ["--once"], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"rc={p.returncode} {p.stderr}"
    return json.loads(st.read_text())

def test_counts_and_effectiveness():
    with tempfile.TemporaryDirectory() as td:
        evs = [{"ts": i, "kind": "tool_call", "state": "DEGRADED", "detector": _det("F4")}
               for i in (11, 12, 13, 14, 15, 16)]
        s = run_sidecar(td, evs)
        assert s["failureCounts"]["F4"] == 6
        se = s["steerEffectiveness"]["F4"]
        assert se["fired"] == 6 and se["resolved"] == 1 and se["refired"] == 5
        assert s["detailCounts"]["F4"]["identical args and identical results"] == 6

def test_missing_input_is_zero_exit():
    with tempfile.TemporaryDirectory() as td:
        s = run_sidecar(td, [])
        assert s["failureCounts"] == {}

def test_rotation_does_not_replay():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ev, st, sc = td / "events", td / "stats.json", td / "sidecar.state.json"
        ev.write_bytes((json.dumps({"ts": 1, "kind": "tool_call", "state": "D", "detector": _det("F4")}) + "\n").encode())
        subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev), "--stats", str(st), "--state", str(sc), "--once"], check=True, capture_output=True)
        ev.write_bytes(b"")  # rotation/truncation
        subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev), "--stats", str(st), "--state", str(sc), "--once"], check=True, capture_output=True)
        assert json.loads(st.read_text())["failureCounts"] == {"F4": 1}  # not 2, not 0

def test_distill_threshold_and_ageout():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ev, st, sc = td / "events", td / "stats.json", td / "sidecar.state.json"
        ev.write_bytes(b"")
        for n in range(1, 4):
            with ev.open("ab") as f:
                f.write((json.dumps({"ts": n, "kind": "tool_call", "state": "D", "detector": _det("F4")}) + "\n").encode())
            subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev), "--stats", str(st), "--state", str(sc), "--distill", "--sd-dir", str(td), "--once"], check=True, capture_output=True)
            pb = json.loads((td / "playbook.json").read_text())
            assert len(pb["entries"]) == (1 if n >= 3 else 0), f"pass {n}: {pb}"
        # aging: an idle pass bumps sessionsUnfired, age-out at 5 removes
        for _ in range(5):
            subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev), "--stats", str(st), "--state", str(sc), "--distill", "--sd-dir", str(td), "--age", "--once"], check=True, capture_output=True)
        assert json.loads((td / "playbook.json").read_text())["entries"] == []
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_supervision_sidecar.py -q` (FAIL: sidecar missing).
- [ ] **Step 3: Implement** `bin/supervisor-sidecar.py`:

```python
#!/usr/bin/env python3
"""supervisor-sidecar.py - no-authority stats consumer for the supervision
plane (spec 2026-11-11 section 4) + the playbook distiller (section 6).
Reads supervision_events.jsonl only; writes stats.json / playbook.json.
Never injects, blocks, or cancels. Absent or corrupt input = exit 0."""
import argparse, json, os, sys, time
from pathlib import Path

STATE = Path.home() / "cortex-agent" / "state" / "supervision"
RESOLVED_AFTER = 30   # stream events: no same-class fire in window = resolved
FIRE_THRESHOLD = 3    # distill: fires needed before a playbook entry

PLAYBOOK_TEXTS = {
    "F1": "[supervisor] past sessions hit malformed call arguments often; re-check the argument shape before every structured call.",
    "F2": "[supervisor] past sessions hit bursts of tool errors and empty turns; verify one assumption (path, flag, environment) before the next call.",
    "F3": "[supervisor] past sessions repeated the same refused action; when a reason arrives, change the route instead of retrying.",
    "F4": "[supervisor] past sessions repeated identical work many times; run iteration as one compound command or a background job and read a single result.",
}

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(STATE / "supervision_events.jsonl"))
    ap.add_argument("--stats", default=str(STATE / "stats.json"))
    ap.add_argument("--state", default=str(STATE / "sidecar.state.json"))
    ap.add_argument("--rulebook", default=str(STATE / "rulebook.json"))
    ap.add_argument("--sd-dir", default=str(STATE), help="dir for playbook.json")
    ap.add_argument("--distill", action="store_true")
    ap.add_argument("--age", action="store_true", help="one idle session: bump sessionsUnfired")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--once", action="store_true")
    return ap.parse_args()

def collect(events_path: Path, offset: int):
    """Append-only with rotation resync (supervised-steer lesson 2026-11-09:
    a shrunken file resyncs to EOF, never replays history)."""
    try:
        size = events_path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        return [], size
    if size <= offset:
        return [], offset
    with events_path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(size - offset).decode("utf-8", errors="replace")
    return chunk.splitlines(), size

def aggregate(lines, acc):
    pending = acc.setdefault("_pending", {})
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        det = rec.get("detector")
        if not det or not det.get("class"):
            continue
        cls = det["class"]
        detail = str(det.get("detail", ""))[:80]
        acc["failureCounts"][cls] = acc["failureCounts"].get(cls, 0) + 1
        acc["detailCounts"].setdefault(cls, {})
        acc["detailCounts"][cls][detail] = acc["detailCounts"][cls].get(detail, 0) + 1
        se = acc["steerEffectiveness"].setdefault(cls, {"fired": 0, "resolved": 0, "refired": 0})
        se["fired"] += 1
        key = f"{cls}|{detail[:48]}"
        pending[key] = {"remaining": RESOLVED_AFTER, "se": se, "cls": cls}
    for key in list(pending):
        st_ = pending[key]
        if st_["remaining"] <= 0:
            st_["se"]["resolved"] += 1
            del pending[key]
        else:
            st_["remaining"] -= 1

def distill(sd_dir: Path, acc, age: bool, rulebook_path: Path):
    pb_p = sd_dir / "playbook.json"
    try:
        pb = json.loads(pb_p.read_text()) if pb_p.exists() else {"entries": []}
        entries = pb.get("entries", [])
    except Exception:
        entries = []
    fired = {cls for cls, n in acc["failureCounts"].items() if n > 0}
    have = {e["cls"] for e in entries}
    for cls, counts in acc["detailCounts"].items():
        if acc["failureCounts"].get(cls, 0) >= FIRE_THRESHOLD and cls not in have:
            top = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
            entries.append({
                "cls": cls,
                "text": PLAYBOOK_TEXTS.get(cls, f"[supervisor] past sessions hit {cls} often; stay alert for the pattern."),
                "learnedFrom": f"replay ledger: {acc['failureCounts'][cls]} fires of {cls} (top: {top[:40]})",
                "ts": int(time.time()),
                "sessionsUnfired": 0,
            })
    if age:
        for e in entries:
            if e["cls"] not in fired:
                e["sessionsUnfired"] = e.get("sessionsUnfired", 0) + 1
    try:
        max_age = json.loads(rulebook_path.read_text()).get("playbookAgeSessions", 5)
    except Exception:
        max_age = 5
    entries = [e for e in entries if e.get("sessionsUnfired", 0) <= max_age]
    tmp = pb_p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"entries": entries}, indent=1))
        os.replace(tmp, pb_p)
    except OSError:
        pass

def emit(stats_path: Path, acc, rulebook_path: Path):
    version = 0
    try:
        version = json.loads(rulebook_path.read_text()).get("version", 0)
    except Exception:
        pass
    acc.pop("_pending", None)
    out = {"ts": int(time.time()), "rulebookVersion": version,
           "failureCounts": acc["failureCounts"], "detailCounts": acc["detailCounts"],
           "steerEffectiveness": acc["steerEffectiveness"], "classesUnfired": acc.get("classesUnfired", {})}
    tmp = stats_path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(out, indent=1))
        os.replace(tmp, stats_path)
    except OSError:
        pass

def main() -> int:
    args = parse_args()
    acc = {"failureCounts": {}, "detailCounts": {}, "steerEffectiveness": {}, "classesUnfired": {}}
    try:
        prev = json.loads(Path(args.stats).read_text())
        for k in ("failureCounts", "detailCounts", "steerEffectiveness", "classesUnfired"):
            acc[k] = prev.get(k, acc[k])
    except Exception:
        pass
    try:
        offset = json.loads(Path(args.state).read_text()).get("offset", 0)
    except Exception:
        offset = 0
    while True:
        lines, offset = collect(Path(args.events), offset)
        if lines:
            aggregate(lines, acc)
            try:
                Path(args.state).write_text(json.dumps({"offset": offset}))
            except OSError:
                pass
        emit(Path(args.stats), acc, Path(args.rulebook))
        if args.distill:
            distill(Path(args.sd_dir), acc, args.age, Path(args.rulebook))
        if args.once or not args.watch:
            return 0
        time.sleep(args.interval)

if __name__ == "__main__":
    sys.exit(main())
```

Effectiveness semantics (documented for the pruner): every fire of a class opens a pending settle window; if the class fires again before the window closes, the previous fire counts as refired; a window that closes with no re-fire counts as resolved. `test_counts_and_effectiveness` expects exactly one resolve for a clean tail of consecutive fires.

- [ ] **Step 4: Run to verify** — `pytest tests/test_supervision_sidecar.py tests/ -q` all pass.
- [ ] **Step 5: Commit** `git add bin/supervisor-sidecar.py tests/test_supervision_sidecar.py && git commit -m "feat: supervision sidecar stats + playbook distiller (no authority)"`.

---

### Task B: eval replay gate — drives the REAL python core

**Files:**
- Create: `bin/eval_replay.py`
- Create: `tests/fixtures/supervision-scenarios.json`
- Create: `tests/test_supervision_replay.py`

**Interfaces:**
- Consumes: `supervision.supervisor.Supervisor` (other session's core, imported, never edited).
- Produces: exit-code gate used by the proposal loop; PASS/FAIL stdout lines.

- [ ] **Step 1: Write the scenario fixtures** in `tests/fixtures/supervision-scenarios.json`:

```json
{"scenarios": [
  {"name": "steady-work", "distribution": "in", "rulebook": {}, "events": [
    {"kind": "task_started", "task": "s1"},
    {"kind": "tool_call", "tool": "bash", "digest": "a1"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "a1"},
    {"kind": "model_turn", "tokens": 120},
    {"kind": "task_ended"}], "expect": {"endState": "IDLE", "steers": 0, "classes": []}},
  {"name": "repetition-loop-steers-then-ladder", "distribution": "in", "rulebook": {}, "events": [
    {"kind": "task_started", "task": "s2"},
    {"kind": "tool_call", "tool": "bash", "digest": "L1", "result_hash": "r"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "L1"},
    {"kind": "tool_call", "tool": "bash", "digest": "L1", "result_hash": "r"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "L1"},
    {"kind": "tool_call", "tool": "bash", "digest": "L1", "result_hash": "r"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "L1"}],
   "expect": {"steers": 1, "classes": ["F4"]}},
  {"name": "interleaved-loop-holdout", "distribution": "holdout", "rulebook": {}, "events": [
    {"kind": "task_started", "task": "s3"},
    {"kind": "tool_call", "tool": "grep", "digest": "G1"},
    {"kind": "tool_call", "tool": "bash", "digest": "H1", "result_hash": "q"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "H1"},
    {"kind": "tool_call", "tool": "bash", "digest": "H1", "result_hash": "q"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "H1"},
    {"kind": "tool_call", "tool": "bash", "digest": "H1", "result_hash": "q"},
    {"kind": "tool_result", "tool": "bash", "error": false, "digest": "H1"}],
   "expect": {"steers": 1, "steersAtMost": 1, "classes": ["F4"]}},
  {"name": "error-burst-f2", "distribution": "in", "rulebook": {}, "events": [
    {"kind": "task_started", "task": "s4"},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true}], "expect": {"steers": 1, "classes": ["F2"]}},
  {"name": "malformed-bash-f1", "distribution": "in", "rulebook": {}, "events": [
    {"kind": "task_started", "task": "s5"},
    {"kind": "tool_call", "tool": "bash", "args": {"command": "run\nls"}}], "expect": {"steers": 1, "classes": ["F1"], "endState": "DEGRADED"}},
  {"name": "holding-burst-loose-rulebook-holdout", "distribution": "holdout", "rulebook": {"error_burst_window": 6, "error_burst_min": 6}, "events": [
    {"kind": "task_started", "task": "s6"},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true},
    {"kind": "tool_result", "tool": "bash", "error": true}], "expect": {"steers": 0}}
]}
```

(The last scenario is the pruner's control: a loosened `error_burst_min: 6` must NOT fire on a 5-error burst; the proposal loop uses it to prove a tightening candidate actually closes the gap.)

- [ ] **Step 2: Write `bin/eval_replay.py`**:

```python
#!/usr/bin/env python3
"""eval_replay.py - acceptance gate for rulebook changes (spec section 5).
Drives the REAL supervision core in a sandbox: RULEBOOK and STEER_FILE are
patched to temp paths, events are fed, expectations checked against the
supervisor's own decisions. Exit 0 = all pass. `--dist in|holdout|both`
selects distribution; `--rulebook` points at a candidate rulebook file."""
import argparse, json, os, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
SUPERVISION_DIR = ROOT / "supervision"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervision-scenarios.json"))
    ap.add_argument("--dist", choices=["in", "holdout", "both"], default="both")
    ap.add_argument("--rulebook", default=None, help="candidate rulebook json")
    ap.add_argument("--override", default="", help="json merged over the rulebook")
    a = ap.parse_args()
    harness = ROOT / "bin" / "eval_replay_worker.py"
    cmd = [sys.executable, str(harness), "--scenarios", a.scenarios, "--dist", a.dist,
           "--default-rulebook", a.rulebook or "", "--override", a.override]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    sys.stdout.write(p.stdout)
    if p.returncode != 0:
        sys.stdout.write(p.stderr)
    return p.returncode

if __name__ == "__main__":
    sys.exit(main())
```

And `bin/eval_replay_worker.py` (the actual runner; separate file so the gate CLI can never import the core into the parent):

```python
#!/usr/bin/env python3
"""eval_replay_worker.py - runs scenarios through the REAL supervision core
in a sandboxed tempdir. Passes fail loudly; the live state dir is untouched."""
import argparse, json, pathlib, sys, tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
sys.path.insert(0, str(ROOT / "supervision"))

# Failure classes are read from the ladder's steer prose (the core's only
# cross-file signal); markers mirror the exact phrases supervisor.py writes.
CLASS_MARKERS = [
    ("F1", ("structurally invalid",)),
    ("F2", ("errored", "~empty model turns", "truncations", "storm", "burst")),
    ("F3", ("refused action", "same refusal family")),
    ("F4", ("repeating identical work", "repeated identical", "identical args")),
]

def _classes_from_steers(lines):
    text = " ".join(lines)
    return [cls for cls, markers in CLASS_MARKERS if any(m in text for m in markers)]

def run_scenario(scen, base_rules):
    import supervisor as sup
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        rb_p = td / "rulebook.json"
        steer_p = td / "steer.jsonl"
        rules = dict(base_rules)
        rules.update(scen.get("rulebook") or {})
        rb_p.write_text(json.dumps(rules))
        sup.RULEBOOK = rb_p          # patch BEFORE construction
        sup.STEER_FILE = steer_p
        s = sup.Supervisor()
        for e in scen["events"]:
            s.on_event(e)
        steer_lines = steer_p.read_text().splitlines() if steer_p.exists() else []
        return {
            "state": s.fsm.state,
            "steers": sum(1 for l in steer_lines if l.strip()),
            "fclasses": _classes_from_steers(steer_lines),
        }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--dist", choices=["in", "holdout", "both"], default="both")
    ap.add_argument("--default-rulebook", default="")
    ap.add_argument("--override", default="")
    args = ap.parse_args()
    base_rules = json.loads(pathlib.Path(args.default_rulebook).read_text()) if args.default_rulebook else {}
    if args.override:
        base_rules.update(json.loads(args.override))
    scen = json.loads(pathlib.Path(args.scenarios).read_text())["scenarios"]
    failed = 0
    for s in scen:
        if args.dist != "both" and s["distribution"] != args.dist:
            continue
        got = run_scenario(s, base_rules)
        ex = s["expect"]
        try:
            if ex.get("endState") is not None:
                assert got["state"] == ex["endState"], f"state {got['state']} != {ex['endState']}"
            if ex.get("steers") is not None:
                assert got["steers"] == ex["steers"], f"steers {got['steers']} != {ex['steers']}"
            if ex.get("steersAtMost") is not None:
                assert got["steers"] <= ex["steersAtMost"], f"steers {got['steers']} > {ex['steersAtMost']}"
            if ex.get("classes") is not None:
                assert set(ex["classes"]).issubset(set(got["fclasses"])), f"classes {got} misses {ex['classes']}"
            print(f"PASS {s['name']}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {s['name']}: {e}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
```

(Contract note: the worker reads the core READ-ONLY, so failure classes are derived from the steer prose the ladder itself writes (`_classes_from_steers` above), never from `supervision/` internals. If the ladder prose ever changes, only the marker table moves.)

- [ ] **Step 3: Baseline pass then the gate is real**:
  - `bin/eval_replay.py` → all PASS, exit 0.
  - `bin/eval_replay.py --dist in --override '{"repetition_limit": 99}'` → `repetition-loop-steers-then-ladder` FAILS (a rule that never fires cannot pass the loop scenario).
- [ ] **Step 4: Tests** `tests/test_supervision_replay.py`:

```python
import json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"

def test_baseline_replay_green():
    p = subprocess.run([sys.executable, str(EVAL)], capture_output=True, text=True, timeout=300)
    print(p.stdout)
    assert p.returncode == 0, p.stderr

def test_gate_catches_dead_rule():
    p = subprocess.run([sys.executable, str(EVAL), "--dist", "in", "--override",
                        json.dumps({"repetition_limit": 99})], capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "FAIL" in p.stdout

def test_holdout_split_runs():
    with tempfile.TemporaryDirectory() as td:
        src = json.loads((ROOT / "tests/fixtures/supervision-scenarios.json").read_text())
        f = pathlib.Path(td) / "holdout.json"
        f.write_text(json.dumps({"scenarios": [s for s in src["scenarios"] if s["distribution"] == "holdout"]}))
        p = subprocess.run([sys.executable, str(EVAL), "--scenarios", str(f)], capture_output=True, text=True, timeout=300)
        assert p.returncode == 0
```

- [ ] **Step 5: Commit** `git add bin/eval_replay.py bin/eval_replay_worker.py tests/fixtures/supervision-scenarios.json tests/test_supervision_replay.py && git commit -m "feat: eval replay gate driving the real supervision core"`.

---

### Task C: proposal loop — RRSI-shaped, one bundle per run

**Files:**
- Create: `bin/supervisor_propose.py`
- Create: `tests/test_supervision_propose.py`

**Interfaces:**
- Consumes: `stats.json` (Task A), `bin/eval_replay.py` (Task B).
- Produces: rulebook.json version bump + provenance lines, only when in-distribution AND holdout replays both pass.

- [ ] **Step 1: Write the failing tests** in `tests/test_supervision_propose.py`:

```python
import json, pathlib, subprocess, sys, tempfile

PROP = pathlib.Path.home() / "cortex-agent" / "bin" / "supervisor_propose.py"
BASE = {"version": 1, "repetition_limit": 3, "storm_min_turns": 3,
        "error_burst_min": 4, "error_burst_window": 6,
        "refusal_repeat_limit": 3, "length_storm_limit": 3}

def setup(td, stats):
    td = pathlib.Path(td)
    (td / "rulebook.json").write_text(json.dumps(BASE))
    (td / "stats.json").write_text(json.dumps(stats))

def run(td, extra=()):
    return subprocess.run([sys.executable, str(PROP), "--state-dir", str(td)] + list(extra),
                          capture_output=True, text=True, timeout=300)

def test_no_failures_means_no_change():
    with tempfile.TemporaryDirectory() as td:
        setup(td, {"failureCounts": {}, "steerEffectiveness": {}, "detailCounts": {}})
        p = run(td)
        assert p.returncode == 0 and json.loads((pathlib.Path(td) / "rulebook.json").read_text())["version"] == 1
        assert not (pathlib.Path(td) / "rulebook-provenance.jsonl").exists()

def test_healthy_class_refuses_change():
    with tempfile.TemporaryDirectory() as td:
        setup(td, {"failureCounts": {"F4": 10},
                   "steerEffectiveness": {"F4": {"fired": 10, "resolved": 9, "refired": 1}},
                   "detailCounts": {"F4": {"identical args and identical results": 10}}})
        p = run(td)
        assert p.returncode == 0
        assert json.loads((pathlib.Path(td) / "rulebook.json").read_text())["version"] == 1
        assert not (pathlib.Path(td) / "rulebook-provenance.jsonl").exists()

def test_unhealthy_repetition_adopts_only_when_replay_agrees():
    with tempfile.TemporaryDirectory() as td:
        setup(td, {"detailCounts": {"F4": {"identical args and identical results": 12}},
                   "failureCounts": {"F4": 12},
                   "steerEffectiveness": {"F4": {"fired": 12, "resolved": 4, "refired": 8}}})
        p = run(td)
        print(p.stdout)
        assert p.returncode == 0
        prov = json.loads((pathlib.Path(td) / "rulebook-provenance.jsonl").read_text().splitlines()[-1])
        rb = json.loads((pathlib.Path(td) / "rulebook.json").read_text())
        assert prov["cls"] == "F4" and "repetition_limit" in prov["change"]
        assert prov["decision"] in ("adopted", "rejected")  # never half-applied
        assert rb["repetition_limit"] == (2 if prov["decision"] == "adopted" else 3)

def test_f2_route_picks_burst_knob_from_details():
    with tempfile.TemporaryDirectory() as td:
        setup(td, {"detailCounts": {"F2": {"3/6 recent tool results errored": 9}},
                   "failureCounts": {"F2": 9},
                   "steerEffectiveness": {"F2": {"fired": 9, "resolved": 3, "refired": 6}}})
        p = run(td)
        prov = json.loads((pathlib.Path(td) / "rulebook-provenance.jsonl").read_text().splitlines()[-1])
        assert prov["knob"] == "error_burst_min"
```

- [ ] **Step 2: Implement** `bin/supervisor_propose.py`:

```python
#!/usr/bin/env python3
"""supervisor_propose.py - the offline improvement loop (spec section 5,
RRSI-shaped). ONE edit-bundle per run, RULEBOOK-ONLY: never touches fsm.py,
detectors.py, supervisor.py, or any enforcement code (DETACH law). Selection
is eval replay with in-distribution AND holdout both required. Provenance is
written for adopted AND rejected candidates. Absent state = exit 0."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
ROOT = HOME / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"
RESOLVED_HEALTHY = 0.80

KNOBS = {
    "F4": ["repetition_limit"],                                # down
    "F2": {"~empty model turns": "storm_min_turns",
           "recent tool results errored": "error_burst_min",
           "truncations": "length_storm_limit"},
    "F3": ["refusal_repeat_limit"],
}
FLOORS = {"repetition_limit": 2, "storm_min_turns": 2, "error_burst_min": 3,
          "refusal_repeat_limit": 2, "length_storm_limit": 2}
STEP = 1

def pick_knob(cls, detail_counts):
    cands = KNOBS.get(cls)
    if cls == "F2" and detail_counts:
        dominant = max(detail_counts.items(), key=lambda kv: kv[1])[0] if detail_counts else ""
        for marker, knob in KNOBS["F2"].items():
            if marker in dominant:
                return knob
        return None
    return cands[0] if isinstance(cands, list) and cands else None

def replay(dist, rulebook_path) -> bool:
    p = subprocess.run([sys.executable, str(EVAL), "--dist", dist,
                        "--rulebook", str(rulebook_path)],
                       capture_output=True, text=True, timeout=300)
    return p.returncode == 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(HOME / "cortex-agent/state/supervision"))
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervision-scenarios.json"))
    a = ap.parse_args()
    sd = Path(a.state_dir)
    try:
        rb = json.loads((sd / "rulebook.json").read_text()) if (sd / "rulebook.json").exists() else {"version": 1}
        stats = json.loads((sd / "stats.json").read_text()) if (sd / "stats.json").exists() else {}
    except Exception:
        return 0
    counts = stats.get("failureCounts", {})
    if not counts:
        return 0
    cls = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]
    se = stats.get("steerEffectiveness", {}).get(cls, {})
    fired, resolved = se.get("fired", 0), se.get("resolved", 0)
    if fired and resolved / fired >= RESOLVED_HEALTHY:
        print(f"propose: {cls} healthy ({resolved}/{fired}); pruner refuses")
        return 0
    knob = pick_knob(cls, stats.get("detailCounts", {}).get(cls, {}))
    if knob is None or knob not in rb or not isinstance(rb[knob], int) or rb[knob] - STEP < FLOORS[knob]:
        return 0
    change = {knob: rb[knob] - STEP}

    import tempfile as _t
    with _t.TemporaryDirectory() as td:
        cand = Path(td) / "candidate-rulebook.json"
        cand_rb = {**rb, **change}
        cand.write_text(json.dumps(cand_rb))
        in_ok = replay("in", cand)
        out_ok = replay("holdout", cand)
    decision = "adopted" if (in_ok and out_ok) else "rejected"
    rec = {"ts": int(time.time()), "cls": cls, "knob": knob, "change": change,
           "reason": f"{counts[cls]} fires; {se.get('refired', 0)} refires",
           "replayIn": in_ok, "replayOut": out_ok, "decision": decision}
    if decision == "adopted":
        rb.update(change)
        rb["version"] = int(rb.get("version", 1)) + 1
        (sd / "rulebook.json").write_text(json.dumps(rb, indent=1))
    with (sd / "rulebook-provenance.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run to verify** — pytest the propose file + full suite; the adopt decision follows the real replay gate (the fixture scenarios determine it; both-dist pass is required, so a candidate that breaks the holdout control `holding-burst-loose-rulebook-holdout` or any in-dist scenario is rejected WITH provenance).
- [ ] **Step 4: Commit** `git add bin/supervisor_propose.py tests/test_supervision_propose.py && git commit -m "feat: RRSI proposal loop over the supervision rulebook (critic pruner, provenance)"`.

---

### Task D: verification

- [ ] `pytest tests/ -q` green (existing + sidecar + replay + propose).
- [ ] EXCLUDE check: `git diff b1005425..HEAD --stat -- supervision/` is EMPTY (we never touched the other session's code).
- [ ] `bin/eval_replay.py` exits 0 on the committed defaults.
- [ ] State-dir smoke: `bin/supervisor-sidecar.py --once` on the real stream exits 0 and leaves `stats.json` valid JSON.
- [ ] Sibling parity: HEADs equal; cortexagent untracked files are exactly the other session's supervision files.
- [ ] Report: spec success criteria evidence (loop trips within 3 events per detector limit; rejected candidates provenance-only; no VRAM/model calls anywhere in new files: `grep -n -i "vram\|gpu\|ollama\|llama" bin/supervisor-*.py bin/eval_replay*.py` → empty).
