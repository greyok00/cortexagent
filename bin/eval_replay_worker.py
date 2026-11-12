#!/usr/bin/env python3
"""eval_replay_worker.py — runs scenario events through the REAL supervision
core (imported READ-ONLY, never edited by this plane) in a tempdir sandbox.
Failure classes are derived from the steer prose the ladder itself writes,
so the core's internals are never touched. Passes fail loudly."""
import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
sys.path.insert(0, str(ROOT / "supervision"))

# mirror of supervisor._lesson phrases (only this table moves if prose changes)
CLASS_MARKERS = [
    ("F1", ("structurally invalid", "must be one single-line command",
            "missing a file path")),
    ("F2", ("keep failing", "burst", "truncations", "storm")),
    ("F3", ("repeated the same refused action", "same refusal family",
            "already failed")),
    ("F4", ("repeating identical work", "repeated identical work",
            "identical args and")),
]


def _classes_from_steers(lines) -> list:
    text = " ".join(lines)
    return [cls for cls, markers in CLASS_MARKERS if any(m in text for m in markers)]


def run_scenario(scen: dict, base_rules: dict) -> dict:
    import supervisor as sup
    state_before = set(dir(sup))
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        rules = dict(base_rules)
        rules.update(scen.get("rulebook") or {})
        rb_p = td / "rulebook.json"
        rb_p.write_text(json.dumps(rules))
        steer_p = td / "steer.jsonl"
        sup.RULEBOOK = rb_p      # patched BEFORE Supervisor() construction
        sup.STEER_FILE = steer_p
        # ensure state/sidecar paths never touch the live dir
        sup.STATE = td
        sup.SIDECAR_STREAM = td / "supervision_events.jsonl"
        sup.SUPERVISOR_LOG = td / "supervisor.log"
        s = sup.Supervisor(scen.get("name", "scenario"))
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
    base_rules = {}
    if args.default_rulebook:
        try:
            base_rules = json.loads(pathlib.Path(args.default_rulebook).read_text())
        except Exception as e:
            print(f"FAIL gate: unreadable rulebook {e}")
            return 1
    if args.override:
        base_rules.update(json.loads(args.override))
    try:
        scen = json.loads(pathlib.Path(args.scenarios).read_text())["scenarios"]
    except Exception as e:
        print(f"FAIL gate: unreadable scenarios {e}")
        return 1
    failed = 0
    for s in scen:
        if args.dist != "both" and s.get("distribution", "in") != args.dist:
            continue
        try:
            got = run_scenario(s, base_rules)
            ex = s.get("expect", {})
            assert ex.get("endState") is None or got["state"] == ex["endState"], (
                f"state {got['state']} != {ex['endState']}")
            assert ex.get("steers") is None or got["steers"] == ex["steers"], (
                f"steers {got['steers']} != {ex['steers']}")
            assert ex.get("steersAtMost") is None or got["steers"] <= ex["steersAtMost"], (
                f"steers {got['steers']} > {ex['steersAtMost']}")
            if ex.get("classes") is not None:
                assert set(ex["classes"]).issubset(set(got["fclasses"])), (
                    f"classes {got['fclasses']} misses {ex['classes']}")
            print(f"PASS {s['name']}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {s['name']}: {e}")
        except Exception as e:
            failed += 1
            print(f"FAIL {s['name']}: worker error {type(e).__name__}: {e}")
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
