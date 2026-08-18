# tests/test_sec_controls.py
"""Unit tests for the pure-logic helpers in lib/sec_controls.

These functions take only plain data (lists of alert dicts) and return
strings — no tkinter, no display, so they're safe to test headlessly.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from lib import sec_controls as sc  # noqa: E402


def test_severity_bar_empty():
    assert sc._severity_bar([]) == "All clear"


def test_severity_bar_counts_only_nonzero():
    alerts = [
        {"severity": "critical", "detail": "x"},
        {"severity": "critical", "detail": "y"},
        {"severity": "high", "detail": "z"},
        {"severity": "info", "detail": "i"},
    ]
    bar = sc._severity_bar(alerts)
    assert "2 critical" in bar
    assert "1 high" in bar
    assert "1 info" in bar
    assert "medium" not in bar
    assert "0 medium" not in bar


def test_severity_bar_order_is_critical_first():
    alerts = [{"severity": "low", "detail": "a"}, {"severity": "critical", "detail": "b"}]
    bar = sc._severity_bar(alerts)
    assert bar.index("critical") < bar.index("low")


def test_human_frame_port_scan_has_block_action():
    title, body, actions = sc._human_frame(
        {"kind": "port-scan", "detail": "Port scan from 1.2.3.4: 12 distinct ports"}
    )
    assert title == "Port scan detected"
    assert "recon" in body.lower() or "probing" in body.lower()
    keys = [k for k, _ in actions]
    assert "block" in keys


def test_human_frame_unknown_kind_falls_back_to_default():
    title, body, actions = sc._human_frame({"kind": "weird.thing", "detail": "d"})
    assert "something" in body.lower() or "flag" in body.lower()
    assert isinstance(actions, list)


def test_block_feedback_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "FIREWALL_COMMANDS",
                        tmp_path / "nonexistent_dir" / "cmds.jsonl")
    out = sc._block_feedback("1.2.3.4", "test")
    assert "fail" in out.lower() or "⚠" in out
