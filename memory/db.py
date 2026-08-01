#!/usr/bin/env python3
"""memory/db.py — SQLite-native storage for CortexAgent memory.

Tables:
  - Checkpoints: session restore points (profile, last_command, context)
  - Memory_Hot: FIFO per-profile, capped at 300 rows
  - Memory_Warm: per-profile context buffer (managed by manager)
  - Memory_Cold: distilled facts (category, confidence, source, tags)
  - Logs: event log for observability

Connection model:
  - One writer connection (singleton)
  - Per-thread read-only connections
  - WAL mode, busy_timeout 5000
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_DIR = Path.home() / ".cortexagent" / "memory"
DB_PATH = DB_DIR / "cortexagent.db"

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA wal_autocheckpoint = 500;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Checkpoints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile      TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_command TEXT    NOT NULL,
    context      TEXT    DEFAULT '{}',
    session_id   TEXT,
    UNIQUE(profile, session_id)
);

CREATE TABLE IF NOT EXISTS Memory_Hot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    role        TEXT    NOT NULL DEFAULT 'user',
    content     TEXT    NOT NULL,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    metadata    TEXT    DEFAULT '{}',
    platform    TEXT    DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS Memory_Warm (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    role        TEXT    NOT NULL DEFAULT 'user',
    content     TEXT    NOT NULL,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    metadata    TEXT    DEFAULT '{}',
    platform    TEXT    DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS Memory_Cold (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    category    TEXT    NOT NULL,
    fact        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'unknown',
    confidence  REAL    NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    tags        TEXT    DEFAULT '[]',
    metadata    TEXT    DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS Logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    event_type  TEXT    NOT NULL,
    event_data  TEXT    DEFAULT '{}',
    task_id     TEXT,
    session_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_hot_profile ON Memory_Hot(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_warm_profile ON Memory_Warm(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_cold_profile ON Memory_Cold(profile, category);
CREATE INDEX IF NOT EXISTS idx_logs_profile ON Logs(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoints_profile ON Checkpoints(profile, timestamp DESC);
"""


class Database:
    """Single-writer / multi-reader SQLite manager."""

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "Database":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._writer: Optional[sqlite3.Connection] = None
        self._readers = threading.local()
        self._init_lock = threading.Lock()

    def initialize(self) -> None:
        with self._init_lock:
            if self._writer is not None:
                return
            self._writer = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._writer.row_factory = sqlite3.Row
            self._writer.executescript(SCHEMA_SQL)
            self._writer.commit()

    @property
    def writer(self) -> sqlite3.Connection:
        if self._writer is None:
            self.initialize()
        return self._writer

    def reader(self) -> sqlite3.Connection:
        if not hasattr(self._readers, "conn") or self._readers.conn is None:
            conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON;")
            self._readers.conn = conn
        return self._readers.conn

    def close(self) -> None:
        if self._writer:
            self._writer.close()
            self._writer = None
        if hasattr(self._readers, "conn") and self._readers.conn:
            self._readers.conn.close()
            self._readers.conn = None

    # ------------------------------------------------------------------
    # Hot
    # ------------------------------------------------------------------
    def add_to_hot(self, profile: str, role: str, content: str,
                   tokens_in: int = 0, tokens_out: int = 0,
                   metadata: Optional[dict] = None,
                   platform: str = "default") -> int:
        w = self.writer
        cur = w.execute(
            "INSERT INTO Memory_Hot (profile, role, content, tokens_in, tokens_out, metadata, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, role, content, tokens_in, tokens_out,
             json.dumps(metadata or {}), platform)
        )
        w.execute(
            "DELETE FROM Memory_Hot WHERE id IN ("
            "  SELECT id FROM Memory_Hot WHERE profile = ? ORDER BY timestamp DESC LIMIT -1 OFFSET 300"
            ")",
            (profile,)
        )
        w.commit()
        return cur.lastrowid or 0

    def get_hot(self, profile: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.reader().execute(
            "SELECT * FROM Memory_Hot WHERE profile = ? ORDER BY timestamp DESC LIMIT ?",
            (profile, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_command(self, profile: str) -> Optional[str]:
        row = self.reader().execute(
            "SELECT content FROM Memory_Hot WHERE profile = ? AND role = 'user' ORDER BY timestamp DESC LIMIT 1",
            (profile,)
        ).fetchone()
        return row["content"] if row else None

    # ------------------------------------------------------------------
    # Warm
    # ------------------------------------------------------------------
    def add_to_warm(self, profile: str, role: str, content: str,
                    tokens_in: int = 0, tokens_out: int = 0,
                    metadata: Optional[dict] = None,
                    platform: str = "default") -> int:
        w = self.writer
        cur = w.execute(
            "INSERT INTO Memory_Warm (profile, role, content, tokens_in, tokens_out, metadata, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, role, content, tokens_in, tokens_out,
             json.dumps(metadata or {}), platform)
        )
        w.commit()
        return cur.lastrowid or 0

    def get_warm(self, profile: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.reader().execute(
            "SELECT * FROM Memory_Warm WHERE profile = ? ORDER BY timestamp DESC LIMIT ?",
            (profile, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_warm(self, profile: str) -> None:
        w = self.writer
        w.execute("DELETE FROM Memory_Warm WHERE profile = ?", (profile,))
        w.commit()

    # ------------------------------------------------------------------
    # Cold
    # ------------------------------------------------------------------
    def add_to_cold(self, profile: str, category: str, fact: str,
                    source: str = "unknown", confidence: float = 0.5,
                    tags: Optional[List[str]] = None,
                    metadata: Optional[dict] = None) -> int:
        w = self.writer
        cur = w.execute(
            "INSERT INTO Memory_Cold (profile, category, fact, source, confidence, tags, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, category, fact, source, confidence,
             json.dumps(tags or []), json.dumps(metadata or {}))
        )
        w.commit()
        return cur.lastrowid or 0

    def get_cold(self, profile: str, category: Optional[str] = None,
                 limit: int = 50) -> List[Dict[str, Any]]:
        if category:
            rows = self.reader().execute(
                "SELECT * FROM Memory_Cold WHERE profile = ? AND category = ? ORDER BY timestamp DESC LIMIT ?",
                (profile, category, limit)
            ).fetchall()
        else:
            rows = self.reader().execute(
                "SELECT * FROM Memory_Cold WHERE profile = ? ORDER BY timestamp DESC LIMIT ?",
                (profile, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cold_categories(self, profile: str) -> List[str]:
        rows = self.reader().execute(
            "SELECT DISTINCT category FROM Memory_Cold WHERE profile = ? ORDER BY category",
            (profile,)
        ).fetchall()
        return [r["category"] for r in rows]

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------
    def save_checkpoint(self, profile: str, last_command: str,
                        context: Optional[dict] = None,
                        session_id: Optional[str] = None) -> int:
        w = self.writer
        cur = w.execute(
            "INSERT OR REPLACE INTO Checkpoints (profile, last_command, context, session_id) "
            "VALUES (?, ?, ?, ?)",
            (profile, last_command, json.dumps(context or {}), session_id)
        )
        w.commit()
        return cur.lastrowid or 0

    def get_checkpoint(self, profile: str) -> Optional[Dict[str, Any]]:
        row = self.reader().execute(
            "SELECT * FROM Checkpoints WHERE profile = ? ORDER BY timestamp DESC LIMIT 1",
            (profile,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------
    def log_event(self, profile: str, event_type: str,
                  event_data: Optional[dict] = None,
                  task_id: Optional[str] = None,
                  session_id: Optional[str] = None) -> None:
        try:
            w = self.writer
            w.execute(
                "INSERT INTO Logs (profile, event_type, event_data, task_id, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (profile, event_type, json.dumps(event_data or {}), task_id, session_id)
            )
            w.commit()
        except Exception:
            pass


db = Database()
