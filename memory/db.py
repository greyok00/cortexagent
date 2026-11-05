#!/usr/bin/env python3


"""Memory database: sqlite-backed store for sessions and platform memory behind the append-only JSONL tiers."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG


def _store_dir() -> Path:
    env = os.environ.get("CORTEXAGENT_MEMORY_DIR")
    if env:
        return Path(os.path.expanduser(env))


    session_id = os.environ.get("CORTEXAGENT_SESSION_ID")
    base_dir = Path(CFG.memory_dir)

    if session_id:

        session_dir = base_dir / "sessions" / session_id

        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    return base_dir


STORE_DIR = _store_dir()
DB_PATH = STORE_DIR / "memory.db"
DB_DIR = STORE_DIR
DAEMON_SOCKET = Path.home() / ".cortexagent" / "memory.sock"

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA wal_autocheckpoint = 500;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Checkpoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile      TEXT    NOT NULL,
    last_command TEXT    NOT NULL,
    context      JSON    NOT NULL,
    timestamp    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS Memory_Hot (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile      TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    value        JSON    NOT NULL,
    timestamp    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS Memory_Cold (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category     TEXT    NOT NULL,
    confidence   REAL    NOT NULL,
    source       TEXT    NOT NULL,
    tags         JSON    NOT NULL,
    entry        JSON    NOT NULL,
    timestamp    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS Logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    level        TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL
);
"""


class MemoryDB:

    _connection = None

    def __init__(self):
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:

        if not hasattr(MemoryDB, "_initialized"):

            self._get_writer()

            MemoryDB._initialized = True

    @classmethod
    def _get_connection(cls) -> sqlite3.Connection:

        if cls._connection is None:
            DB_DIR.mkdir(parents=True, exist_ok=True)
            cls._connection = sqlite3.connect(
                DB_PATH,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
            )
            cls._connection.execute("PRAGMA journal_mode=WAL")
            cls._connection.execute("PRAGMA busy_timeout=5000")
            cls._connection.execute("PRAGMA synchronous=NORMAL")
            cls._connection.execute("PRAGMA wal_autocheckpoint=500")
            cls._connection.execute("PRAGMA foreign_keys=ON")
            cls._migrate_legacy_tables(cls._connection)
            cls._connection.executescript(SCHEMA_SQL)
        return cls._connection

    # Tables an older schema version left on disk (flat message columns).
    _REQUIRED_COLUMNS = {
        "Checkpoints": {"last_command", "context"},
        "Memory_Hot": {"key", "value"},
        "Memory_Cold": {"entry"},
        "Logs": {"message"},
    }

    @classmethod
    def _migrate_legacy_tables(cls, conn: sqlite3.Connection) -> None:
        for table, required in cls._REQUIRED_COLUMNS.items():
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not cols or required <= cols:
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if count:
                # Never destroy data: leave the legacy table in place and say
                # so loudly; subsequent writes will raise visible sqlite errors.
                print(
                    f"cortexagent memory: '{table}' uses a legacy schema and "
                    f"holds {count} rows — leaving it untouched; manual "
                    f"migration required",
                    file=sys.stderr,
                )
                continue
            conn.execute(f"DROP TABLE {table}")

    def _get_writer(self) -> sqlite3.Connection:

        return self._get_connection()

    def reader(self) -> sqlite3.Connection:

        if not hasattr(threading.current_thread(), "_memory_reader"):
            DB_DIR.mkdir(parents=True, exist_ok=True)
            # Row factory: readers index by column name (row["profile"], …).
            threading.current_thread()._memory_reader = sqlite3.connect(
                DB_PATH,
                timeout=30,
                isolation_level=None,
                check_same_thread=False,
                uri=True,
            )

            threading.current_thread()._memory_reader.row_factory = sqlite3.Row
            threading.current_thread()._memory_reader.execute("PRAGMA query_only=ON")
        return threading.current_thread()._memory_reader

    def write_checkpoint(self, profile: str, last_command: str, context: Dict) -> None:

        db = self._get_writer()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO Checkpoints (profile, last_command, context, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (profile, last_command, json.dumps(context), datetime.now().isoformat()),
        )
        db.commit()

    def write_memory_hot(self, profile: str, key: str, value: Any) -> None:

        db = self._get_writer()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO Memory_Hot (profile, key, value, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (profile, key, json.dumps(value), datetime.now().isoformat()),
        )
        db.commit()


        self._mirror_to_jsonl("hot", profile, key, value)

    def read_memory_hot(self, profile: str, key: str) -> Optional[Any]:

        db = self.reader()
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT value FROM Memory_Hot
            WHERE profile = ? AND key = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (profile, key),
        )
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None

    def write_memory_cold(
        self, category: str, confidence: float, source: str, tags: List[str], entry: Dict
    ) -> None:

        db = self._get_writer()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO Memory_Cold (category, confidence, source, tags, entry, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (category, confidence, source, json.dumps(tags), json.dumps(entry), datetime.now().isoformat()),
        )
        db.commit()

    def read_memory_cold(self, category: str) -> List[Dict]:

        db = self.reader()
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT entry FROM Memory_Cold
            WHERE category = ?
            ORDER BY timestamp DESC
            """,
            (category,),
        )
        return [json.loads(row[0]) for row in cursor.fetchall()]

    def write_log(self, level: str, message: str) -> None:

        db = self._get_writer()
        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO Logs (level, message, timestamp)
            VALUES (?, ?, ?)
            """,
            (level, message, datetime.now().isoformat()),
        )
        db.commit()

    def _mirror_to_jsonl(self, tier: str, platform: str, key: str, value: Any) -> None:

        data = {
            "tier": tier,
            "platform": platform,
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
        }
        line = json.dumps(data) + "\n"


        daemon_socket = Path.home() / ".cortexagent" / "memory.sock"
        if daemon_socket.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1.0)
                    sock.connect(str(daemon_socket))
                    sock.sendall(line.encode("utf-8"))
                    return
            except (socket.error, FileNotFoundError, ConnectionRefusedError):

                pass


        hot_dir = STORE_DIR / "hot"
        hot_dir.mkdir(parents=True, exist_ok=True)
        jsonl_file = hot_dir / f"{platform}.jsonl"
        try:

            fd = os.open(
                str(jsonl_file),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:

            with open(jsonl_file, "a", encoding="utf-8") as f:
                f.write(line)

    def get_stats(self) -> Dict[str, Any]:

        db = self.reader()
        cursor = db.cursor()


        cursor.execute(
            """
            SELECT COUNT(*), SUM(LENGTH(value))
            FROM Memory_Hot
            """
        )
        hot_count, hot_size = cursor.fetchone()
        hot_size = hot_size or 0


        cursor.execute(
            """
            SELECT COUNT(DISTINCT category)
            FROM Memory_Cold
            """
        )
        cold_count = cursor.fetchone()[0] or 0

        return {
            "hot": hot_count,
            "warm": 0,
            "cold": cold_count,
            "hot_bytes": hot_size,
            "warm_bytes": 0,
        }

    def cleanup_old_entries(self, days: int = 30) -> None:

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        db = self._get_writer()
        cursor = db.cursor()


        cursor.execute(
            """
            DELETE FROM Memory_Hot
            WHERE timestamp < ?
            """,
            (cutoff,),
        )


        cursor.execute(
            """
            DELETE FROM Memory_Cold
            WHERE timestamp < ?
            """,
            (cutoff,),
        )


        cursor.execute(
            """
            DELETE FROM Logs
            WHERE timestamp < ?
            """,
            (cutoff,),
        )

        db.commit()

        db.execute("VACUUM")



db = MemoryDB()