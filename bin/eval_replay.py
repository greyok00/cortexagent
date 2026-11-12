#!/usr/bin/env python3
"""eval_replay.py — acceptance gate for rulebook changes (spec 2026-11-11 §5).
Drives the REAL supervision core in a sandbox: RULEBOOK + STEER_FILE patched
to temp paths per scenario; the live state dir is untouched. Exit 0 = all
scenarios pass. The actual runner is eval_replay_worker.py (separate process
so the gate CLI can never import the core into a long-lived parent)."""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path.home() / "cortex-agent"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervision-scenarios.json"))
    ap.add_argument("--dist", choices=["in", "holdout", "both"], default="both")
    ap.add_argument("--rulebook", default="", help="candidate rulebook json")
    ap.add_argument("--override", default="", help="json merged over the rulebook")
    a = ap.parse_args()
    harness = ROOT / "bin" / "eval_replay_worker.py"
    cmd = [sys.executable, str(harness), "--scenarios", a.scenarios,
           "--dist", a.dist, "--default-rulebook", a.rulebook,
           "--override", a.override]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("FAIL gate: replay worker timeout")
        return 1
    sys.stdout.write(p.stdout)
    if p.returncode != 0 and p.stderr:
        sys.stdout.write(p.stderr[-2000:])
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
