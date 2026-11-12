"""Task B tests: eval replay gate driving the REAL supervision core."""
import json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"

def test_baseline_replay_green():
    p = subprocess.run([sys.executable, str(EVAL)], capture_output=True, text=True, timeout=300)
    print(p.stdout)
    assert p.returncode == 0, p.stderr or p.stdout

def test_gate_catches_dead_rule():
    p = subprocess.run([sys.executable, str(EVAL), "--dist", "in", "--override",
                        json.dumps({"repetition_limit": 99})],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode != 0 and "FAIL" in p.stdout

def test_holdout_split_runs():
    with tempfile.TemporaryDirectory() as td:
        src = json.loads((ROOT / "tests/fixtures/supervision-scenarios.json").read_text())
        f = pathlib.Path(td) / "holdout.json"
        f.write_text(json.dumps({"scenarios": [s for s in src["scenarios"]
                                               if s["distribution"] == "holdout"]}))
        p = subprocess.run([sys.executable, str(EVAL), "--scenarios", str(f)],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stdout + p.stderr
