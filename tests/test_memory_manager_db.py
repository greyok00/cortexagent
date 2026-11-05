#!/usr/bin/env python3
"""Regression tests for the memory manager and db contract.

Each scenario runs in a fresh subprocess with CORTEXAGENT_MEMORY_DIR pointed
at a temporary store, because memory/db.py binds its store path at import
time. Name-indexed rows (row["profile"]) and legacy-schema migration are
exercised here as well.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ROUNDTRIP = r"""
import os
import sqlite3
from memory.manager import manager, get_resume, get_stats
manager.add_to_hot("t1", "hello probe", role="user")
manager.add_to_hot("t1", "follow-up", role="assistant", metadata={"context": {"k": 1}})
manager.add_to_hot("t1", "third note", role="user")
msgs = manager.get_hot_messages("t1", limit=5)
assert len(msgs) == 3, msgs
assert msgs[0]["content"] == "third note", msgs[0]
assert msgs[0]["role"] == "user" and msgs[2]["content"] == "hello probe", msgs
resume = get_resume("t1")
assert resume.get("command") == "third note", resume
assert resume.get("context") == {}, resume
assert get_resume("nope") == {}, get_resume("nope")
manager.save_to_cold("facts", {"note": "alpha"})
assert manager.get_all_cold_categories("t1") == ["facts"], manager.get_all_cold_categories("t1")
kn = manager.get_cold_knowledge("t1", "facts")
assert kn["total_entries"] == 1, kn
assert "note" in kn["entries"][0]["fact"], kn
stats = get_stats("t1")
assert stats["hot"] == {"platform:t1": 3}, stats
assert stats["cold_total"] == 1, stats
db_path = os.environ["CORTEXAGENT_MEMORY_DIR"] + "/memory.db"
conn = sqlite3.connect(db_path)
cols = {n for (n, _t) in conn.execute("SELECT name, type FROM pragma_table_info('Memory_Hot')")}
assert {"profile", "key", "value", "timestamp"} <= cols, cols
print("ROUNDTRIP-OK")
"""


def _run(script: str, store: str, *argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CORTEXAGENT_MEMORY_DIR=store)
    return subprocess.run(
        [sys.executable, "-c", script, *argv], cwd=str(REPO), env=env,
        capture_output=True, text=True, timeout=120,
    )


def test_manager_roundtrip_and_resume(tmp_path):
    r = _run(ROUNDTRIP, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "ROUNDTRIP-OK" in r.stdout


def test_call_cli_write_search_recent(tmp_path):
    env = dict(os.environ, CORTEXAGENT_MEMORY_DIR=str(tmp_path))

    r = subprocess.run(
        [sys.executable, "lib/cortexagent_call.py", "write",
         "--content", "searchable marker", "--role", "user"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr

    r = subprocess.run(
        [sys.executable, "lib/cortexagent_call.py", "search", "searchable"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip(), r.stdout + r.stderr
    assert "searchable marker" in r.stdout and "user:" in r.stdout

    r = subprocess.run(
        [sys.executable, "lib/cortexagent_call.py", "recent", "--limit", "5"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Last request:" in r.stdout, r.stdout + r.stderr


def test_reader_rows_support_name_access(tmp_path):
    r = _run(
        "import memory.db as mdb\n"
        "db = mdb.MemoryDB()\n"
        "db.write_memory_hot(profile='platform:x', key='chat', value={'a': 1})\n"
        "row = db.reader().execute('SELECT profile, key FROM Memory_Hot').fetchone()\n"
        "assert row['profile'] == 'platform:x' and row['key'] == 'chat', row\n"
        "print('ROWNAME-OK')\n",
        str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "ROWNAME-OK" in r.stdout


LEGACY_CREATE = r"""
import sqlite3
conn = sqlite3.connect("memory.db")
conn.executescript('''
CREATE TABLE IF NOT EXISTS Checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL,
    timestamp TEXT NOT NULL, last_command TEXT NOT NULL,
    context TEXT, session_id TEXT);
CREATE TABLE IF NOT EXISTS Memory_Hot (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL,
    timestamp TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    tokens_in INTEGER, tokens_out INTEGER, metadata TEXT, platform TEXT);
CREATE TABLE IF NOT EXISTS Memory_Cold (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL,
    timestamp TEXT NOT NULL, category TEXT NOT NULL, fact TEXT NOT NULL,
    source TEXT, confidence REAL, tags TEXT, metadata TEXT);
CREATE TABLE IF NOT EXISTS Logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL,
    timestamp TEXT NOT NULL, event_type TEXT NOT NULL, event_data TEXT,
    task_id TEXT, session_id TEXT);
''')
conn.commit(); conn.close()
"""

VERIFY_MIGRATED = r"""
import sqlite3
import memory.db as mdb  # noqa: F401 — module-level db migrates/initializes the store
store = os.environ["CORTEXAGENT_MEMORY_DIR"]
conn = sqlite3.connect(store + "/memory.db")
cols = {n for (n, _t) in conn.execute("SELECT name, type FROM pragma_table_info('Memory_Hot')")}
conn.close()
assert {"key", "value"} <= cols, cols
print("MIGRATED-OK")
"""

VERIFY_PRESERVED = r"""
import sys
import memory.db as mdb  # noqa: F401 — prints a loud warning for non-empty legacy tables
from memory.manager import get_resume  # noqa: F401 — must import clean
assert "--legacy-nonempty" in sys.argv
print("LEGACY-PRESERVED-OK")
"""


def test_legacy_empty_tables_are_recreated(tmp_path):
    r = subprocess.run([sys.executable, "-c", LEGACY_CREATE], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    r = _run("import os\n" + VERIFY_MIGRATED, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "MIGRATED-OK" in r.stdout


def test_legacy_nonempty_tables_are_preserved(tmp_path):
    r = subprocess.run([sys.executable, "-c", LEGACY_CREATE], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    seed = subprocess.run(
        [sys.executable, "-c",
         "import sqlite3; c = sqlite3.connect('memory.db'); "
         "c.execute(\"INSERT INTO Memory_Hot (profile, timestamp, role, content) "
         "VALUES ('platform:t1', '2020-01-01', 'user', 'legacy row')\"); c.commit()"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert seed.returncode == 0, seed.stderr
    r = _run(VERIFY_PRESERVED, str(tmp_path), "--legacy-nonempty")
    assert r.returncode == 0, r.stderr
    assert "LEGACY-PRESERVED-OK" in r.stdout
    # the legacy row survives untouched
    import sqlite3
    conn = sqlite3.connect(tmp_path / "memory.db")
    n = conn.execute("SELECT COUNT(*) FROM Memory_Hot WHERE content='legacy row'").fetchone()[0]
    conn.close()
    assert n == 1