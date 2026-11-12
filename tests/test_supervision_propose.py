"""Task C tests: supervisor_propose.py — one rulebook edit-bundle per run,
replay-gated (in + holdout), provenance for adopt AND reject."""
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
        assert p.returncode == 0
        assert json.loads((pathlib.Path(td) / "rulebook.json").read_text())["version"] == 1
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
        assert p.returncode == 0, p.stdout + p.stderr
        prov = json.loads((pathlib.Path(td) / "rulebook-provenance.jsonl")
                          .read_text().splitlines()[-1])
        rb = json.loads((pathlib.Path(td) / "rulebook.json").read_text())
        assert prov["cls"] == "F4" and "repetition_limit" in prov["change"]
        assert prov["decision"] in ("adopted", "rejected")
        assert rb["repetition_limit"] == (2 if prov["decision"] == "adopted" else 3)

def test_f2_route_picks_burst_knob_from_details():
    with tempfile.TemporaryDirectory() as td:
        setup(td, {"detailCounts": {"F2": {"3/6 recent tool results errored": 9}},
                   "failureCounts": {"F2": 9},
                   "steerEffectiveness": {"F2": {"fired": 9, "resolved": 3, "refired": 6}}})
        p = run(td)
        prov = json.loads((pathlib.Path(td) / "rulebook-provenance.jsonl")
                          .read_text().splitlines()[-1])
        assert prov["knob"] == "error_burst_min"
