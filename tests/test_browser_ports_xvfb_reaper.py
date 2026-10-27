#!/usr/bin/env python3
"""Focused tests for the orphan-Xvfb reaper (2026-10-20).

The reaper inspects a candidate display's real Xvfb process and its X11
socket/lock. An Xvfb with NEITHER socket nor lock is an orphan and may be
terminated; a display with a live socket/lock belongs to another session and
is skipped; :0 is never killed. No Xvfb or real signal is involved: the ps
snapshot, socket/lock paths, kill, and liveness probe are injected.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

import browser_ports  # noqa: E402


def _snap(n, pid=4242):
    return [{"pid": pid, "comm": "Xvfb",
             "args": f"Xvfb :{n} -screen 0 1400x1000x24 -nolisten tcp"}]


def test_orphan_xvfb_is_reclaimed_and_reused(tmp_path):
    killed = []
    result = browser_ports.reap_orphan_display(
        93,
        ps_snapshot=_snap(93),
        socket_path=str(tmp_path / "no-socket"),
        lock_path=str(tmp_path / "no-lock"),
        kill=lambda pid, sig: killed.append((pid, sig)),
        alive=lambda pid: False,
        wait_s=0.01,
    )
    assert result["reclaimed"] is True
    assert result["pids"] == [4242]
    assert result["killed"] == [4242]
    assert killed and killed[0][0] == 4242
    assert "reclaimed" in result["reason"]


def test_live_socket_display_is_skipped(tmp_path):
    sock = tmp_path / "X95"
    sock.write_text("")
    killed = []
    result = browser_ports.reap_orphan_display(
        95,
        ps_snapshot=_snap(95, pid=5151),
        socket_path=str(sock),
        lock_path=str(tmp_path / "no-lock"),
        kill=lambda pid, sig: killed.append(pid),
        alive=lambda pid: True,
        wait_s=0.01,
    )
    assert result["reclaimed"] is False
    assert result["killed"] == []
    assert killed == []
    assert "socket/lock" in result["reason"]


def test_live_lock_display_is_skipped(tmp_path):
    lock = tmp_path / "X96-lock"
    lock.write_text("5151")
    killed = []
    result = browser_ports.reap_orphan_display(
        96,
        ps_snapshot=_snap(96),
        socket_path=str(tmp_path / "no-socket"),
        lock_path=str(lock),
        kill=lambda pid, sig: killed.append(pid),
        alive=lambda pid: True,
        wait_s=0.01,
    )
    assert result["reclaimed"] is False
    assert killed == []


def test_display_zero_is_never_killed(tmp_path):
    killed = []
    result = browser_ports.reap_orphan_display(
        0,
        ps_snapshot=_snap(0, pid=1),
        socket_path=str(tmp_path / "no-socket"),
        lock_path=str(tmp_path / "no-lock"),
        kill=lambda pid, sig: killed.append(pid),
        alive=lambda pid: True,
        wait_s=0.01,
    )
    assert result["reclaimed"] is False
    assert killed == []
    assert ":0" in result["reason"]


def test_no_xvfb_process_is_not_reclaimed(tmp_path):
    killed = []
    result = browser_ports.reap_orphan_display(
        94,
        ps_snapshot=[{"pid": 777, "comm": "bash", "args": "bash -c 'Xvfb :94'"}],
        socket_path=str(tmp_path / "no-socket"),
        lock_path=str(tmp_path / "no-lock"),
        kill=lambda pid, sig: killed.append(pid),
        alive=lambda pid: True,
        wait_s=0.01,
    )
    assert result["reclaimed"] is False
    assert killed == []


def test_young_xvfb_is_not_reaped(tmp_path):
    """A just-spawned Xvfb may not have created its socket yet."""
    killed = []
    snap = [{"pid": 6161, "comm": "Xvfb", "etimes": 0.2,
             "args": "Xvfb :97 -screen 0 1400x1000x24"}]
    result = browser_ports.reap_orphan_display(
        97,
        ps_snapshot=snap,
        socket_path=str(tmp_path / "no-socket"),
        lock_path=str(tmp_path / "no-lock"),
        kill=lambda pid, sig: killed.append(pid),
        alive=lambda pid: True,
        wait_s=0.01,
    )
    assert result["reclaimed"] is False
    assert killed == []


def test_inspect_display_flags_only_socketless_lockless_process(tmp_path):
    info = browser_ports.inspect_display(
        92, ps_snapshot=_snap(92),
        socket_path=str(tmp_path / "none"), lock_path=str(tmp_path / "none2"))
    assert info["orphan"] is True
    assert info["pids"] == [4242]

    sock = tmp_path / "X92"
    sock.write_text("")
    info2 = browser_ports.inspect_display(
        92, ps_snapshot=_snap(92),
        socket_path=str(sock), lock_path=str(tmp_path / "none2"))
    assert info2["orphan"] is False
