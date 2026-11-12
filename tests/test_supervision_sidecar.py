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
