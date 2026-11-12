#!/usr/bin/env python3
"""supervisor_propose.py — the offline improvement loop (spec 2026-11-11 §5,
RRSI-shaped). ONE edit-bundle per run, RULEBOOK-ONLY: never edits fsm.py,
detectors.py, supervisor.py, or any enforcement code (DETACH law).

PROPOSE: rank failure classes by count; pick one knob from the dominant
detail signature. SELECT: eval replay against the REAL core — in-distribution
AND holdout must both pass (critic + pruner: a change that breaks any
scenario is rejected). ADOPT (version bump) or REJECT; both carry provenance.
Absent state = exit 0. Two-timescales note: this procedure itself changes
rarely (owner-edited plan), the rulebook it edits changes per cycle."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
ROOT = HOME / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"
RESOLVED_HEALTHY = 0.80     # pruner: resolved ratio at/above = healthy, refuse

KNOBS = {
    "F4": ["repetition_limit"],                    # tighten downward
    "F2": {"~empty model turns": "storm_min_turns",
           "recent tool results errored": "error_burst_min",
           "truncations": "length_storm_limit"},
    "F3": ["refusal_repeat_limit"],
}
FLOORS = {"repetition_limit": 2, "storm_min_turns": 2, "error_burst_min": 3,
          "refusal_repeat_limit": 2, "length_storm_limit": 2}
STEP = 1


def pick_knob(cls, detail_counts) -> str | None:
    cands = KNOBS.get(cls)
    if not cands:
        return None
    if isinstance(cands, dict):
        if not detail_counts:
            return None
        dominant = max(detail_counts.items(), key=lambda kv: kv[1])[0]
        for marker, knob in cands.items():
            if marker in dominant:
                return knob
        return None
    return cands[0]


def replay(dist: str, rulebook_path: Path) -> bool:
    try:
        p = subprocess.run(
            [sys.executable, str(EVAL), "--dist", dist,
             "--rulebook", str(rulebook_path)],
            capture_output=True, text=True, timeout=300)
        return p.returncode == 0
    except Exception:
        return False   # gate unavailable = candidate can never be proven


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(HOME / "cortex-agent/state/supervision"))
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervision-scenarios.json"))
    a = ap.parse_args()
    sd = Path(a.state_dir)
    try:
        rb_path = sd / "rulebook.json"
        rb = json.loads(rb_path.read_text()) if rb_path.exists() else {"version": 1}
        stats = json.loads((sd / "stats.json").read_text()) if (sd / "stats.json").exists() else {}
    except Exception:
        return 0                      # corrupt state: no-op, never half-apply
    counts = stats.get("failureCounts", {})
    if not counts:
        return 0                      # nothing observed: no proposals
    cls = max(counts.items(), key=lambda kv: kv[1])[0]
    se = stats.get("steerEffectiveness", {}).get(cls, {})
    fired, resolved = se.get("fired", 0), se.get("resolved", 0)
    if fired and resolved / fired >= RESOLVED_HEALTHY:
        print(f"propose: {cls} healthy ({resolved}/{fired} resolved); "
              "critic refuses a change")
        return 0
    knob = pick_knob(cls, stats.get("detailCounts", {}).get(cls, {}))
    if not knob or not isinstance(rb.get(knob), int):
        return 0
    if rb[knob] - STEP < FLOORS.get(knob, 0):
        print(f"propose: {knob} already at floor {FLOORS.get(knob)}; no change")
        return 0
    change = {knob: rb[knob] - STEP}

    import tempfile as _t
    with _t.TemporaryDirectory() as td:
        cand = Path(td) / "candidate-rulebook.json"
        cand.write_text(json.dumps({**rb, **change}))
        in_ok = replay("in", cand)
        out_ok = replay("holdout", cand)
    decision = "adopted" if (in_ok and out_ok) else "rejected"
    rec = {"ts": int(time.time()), "cls": cls, "knob": knob, "change": change,
           "reason": (f"{counts[cls]} fires; {se.get('refired', 0)} refires; "
                      f"resolved {resolved}/{fired}"),
           "replayIn": in_ok, "replayOut": out_ok, "decision": decision}
    if decision == "adopted":
        rb.update(change)
        rb["version"] = int(rb.get("version", 1)) + 1
        rb["provenance"] = (f"propose loop {cls}: {change[knob]} after "
                            f"{counts[cls]} fires ({time.strftime('%Y-%m-%d')})")
        (sd / "rulebook.json").write_text(json.dumps(rb, indent=1))
    with (sd / "rulebook-provenance.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
