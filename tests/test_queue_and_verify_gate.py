#!/usr/bin/env python3
"""Regression tests for the prompt queue durability contracts and the
post-verify gate recursion base case."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENVROOT = dict(os.environ)


def _run_cli(cwd: str, *args: str) -> subprocess.CompletedProcess:
    """Run prompt_queue as a CLI with an isolated state dir."""
    env = dict(ENVROOT, CORTEXAGENT_STATE_DIR=cwd)
    return subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from lib.prompt_queue import main; sys.exit(main())", *args],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)


def _with_tmp_state():
    import tempfile
    return tempfile.mkdtemp(prefix="pq-test-")


def test_queue_survives_crash_mid_write(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    # point the module's QUEUE_FILE at the tmp tree
    script = textwrap.dedent("""
        import sys, json, os, glob
        sys.path.insert(0, '.')
        from lib import prompt_queue as pq
        pq.submit("1. alpha task\\n2. beta task")
        res = pq.submit("3. gamma task")
        items = pq.list_items()
        assert len(items) == 3, [i.text for i in items]
        # mid-write crash equivalent: a torn file must be archived, not wiped
        pq._save(items)                      # good file on disk now
        torn = (pq.QUEUE_FILE.read_text()[:-30]) + '"items": [{'
        pq.QUEUE_FILE.write_text(torn)
        loaded = pq._load()
        assert loaded == [], loaded
        archives = glob.glob(str(pq.QUEUE_FILE.parent / "prompt_queue.corrupt-*.json"))
        assert archives, "corrupt file not archived"
        # the torn bytes themselves move aside for forensics (not deleted)
        assert open(archives[0]).read() == torn
        # and the queue keeps operating afterwards
        r = pq.submit("4. recovered task")
        assert r.enqueued and "recovered task" in r.enqueued[0].text
        assert len(pq.list_items()) == 1
        print("QUEUE-OK")
    """)
    env = dict(ENVROOT, CORTEXAGENT_STATE_DIR=str(state))
    r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "QUEUE-OK" in r.stdout


def test_clear_keeps_archive(tmp_path):
    script = textwrap.dedent("""
        import sys, glob, json
        sys.path.insert(0, '.')
        from lib import prompt_queue as pq
        pq.submit("1. one task\\n2. two task")
        n = pq.clear()
        assert n == 2, n
        assert pq.list_items() == []
        archives = glob.glob(str(pq.QUEUE_FILE.parent / "prompt_queue.archived-*.json"))
        assert archives, "archive not written"
        assert len(json.loads(open(archives[0]).read())["items"]) == 2
        print("CLEAR-ARCHIVE-OK")
    """)
    env = dict(ENVROOT, CORTEXAGENT_STATE_DIR=str(tmp_path / "state"))
    r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CLEAR-ARCHIVE-OK" in r.stdout


def test_concurrent_submit_no_lose(tmp_path):
    script = textwrap.dedent("""
        import sys, threading
        sys.path.insert(0, '.')
        from lib import prompt_queue as pq
        def worker(i):
            for _ in range(5):
                pq.submit(f"task-{i}-{_}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        items = pq.list_items()
        texts = [i.text for i in items]
        assert len([t for t in texts if t.startswith("task-")]) == 20, len(texts)
        print("CONCUR-OK")
    """)
    env = dict(ENVROOT, CORTEXAGENT_STATE_DIR=str(tmp_path / "state"))
    r = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CONCUR-OK" in r.stdout


def test_post_verify_gate_clean_when_verifier_healthy():
    import importlib
    mod = importlib.import_module("lib.react_loop")
    r = mod._post_verify_gate("hello response")
    assert r["ok"] is True
    assert "hello response" in r["output"]
    # healthy verifier → no exception surfaces, footer only when it warns
    assert r.get("error") == ""


def test_post_verify_gate_degrades_when_import_fails(monkeypatch):
    import sys
    import lib.react_loop as rl
    monkeypatch.setitem(sys.modules, "lib.post_response_verifier", None)
    r = rl._post_verify_gate("framed text")
    assert r["ok"] is True and "framed text" in r["output"]
    assert "post-verify unavailable" in r["output"], r


def test_post_verify_gate_never_recurses(monkeypatch, tmp_path):
    import lib.react_loop as rl
    import lib.post_response_verifier as pv

    def boom(_text):
        raise RuntimeError("verifier exploded")

    monkeypatch.setattr(pv, "verify", boom)
    r = rl._post_verify_gate("framed text")
    assert r["ok"] is True and "framed text" in r["output"]
    assert "post-verify failed" in r["output"], r