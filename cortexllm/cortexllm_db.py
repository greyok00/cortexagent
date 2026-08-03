#!/usr/bin/env python3
"""
CortexLLM Database Layer — SQLite-native, WAL mode, single-writer/multi-reader.

Tables:
  - Checkpoints:     Session restore points (profile, timestamp, last_command, context)
  - Memory_Hot:      FIFO per-profile, capped at 300 rows (user prompts + responses)
  - Memory_Warm:     Per-profile context buffer, no hard cap (managed by distillation)
  - Memory_Cold:     Distilled facts only — source, confidence, tags required
  - Active_Tasks:    Currently running tasks per profile
  - Logs:            Event log for observability

Connection model:
  - Exactly one writer connection (owned by the Dispatcher)
  - All other components use read-only connections
  - No shared connections across async tasks
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_DIR = Path.home() / ".config/cortexllm"
DB_PATH = DB_DIR / "cortexllm.db"
MEMORY_DIR = DB_DIR / "memory"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA wal_autocheckpoint = 500;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Checkpoints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    last_command TEXT   NOT NULL,
    context     TEXT    DEFAULT '{}',
    session_id  TEXT,
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

CREATE TABLE IF NOT EXISTS Active_Tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT    NOT NULL,
    task_id     TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    progress    REAL    DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    error       TEXT,
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

CREATE TABLE IF NOT EXISTS Worker_State (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL DEFAULT '{}',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(worker, key)
);

CREATE TABLE IF NOT EXISTS Worker_Config (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    value       TEXT    NOT NULL DEFAULT '{}',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(worker, key)
);

CREATE TABLE IF NOT EXISTS Earnings_Log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker      TEXT    NOT NULL,
    site        TEXT    NOT NULL,
    amount      REAL    NOT NULL DEFAULT 0,
    job_type    TEXT    DEFAULT 'unknown',
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    metadata    TEXT    DEFAULT '{}'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_hot_profile ON Memory_Hot(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_warm_profile ON Memory_Warm(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_cold_profile ON Memory_Cold(profile, category);
CREATE INDEX IF NOT EXISTS idx_tasks_profile ON Active_Tasks(profile, status);
CREATE INDEX IF NOT EXISTS idx_logs_profile ON Logs(profile, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoints_profile ON Checkpoints(profile, timestamp DESC);
"""

# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class Database:
    """Single-writer / multi-reader database connection manager.

    Usage:
        db = Database()
        db.initialize()              # Create schema
        db.writer.execute(...)       # One writer connection
        with db.reader() as conn:    # Read-only connections
            conn.execute(...)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._writer: Optional[sqlite3.Connection] = None
        self._readers = threading.local()
        self._init_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self):
        """Create the database and schema. Safe to call multiple times."""
        with self._init_lock:
            if self._writer is not None:
                return
            self._writer = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._writer.row_factory = sqlite3.Row
            self._writer.executescript(SCHEMA_SQL)
            self._writer.commit()

    @property
    def writer(self) -> sqlite3.Connection:
        """Return the single writer connection. Caller must commit."""
        if self._writer is None:
            self.initialize()
        return self._writer

    def reader(self) -> sqlite3.Connection:
        """Return a read-only connection for this thread."""
        if not hasattr(self._readers, 'conn') or self._readers.conn is None:
            conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON;")
            self._readers.conn = conn
        return self._readers.conn

    def close(self):
        """Close all connections."""
        if self._writer:
            self._writer.close()
            self._writer = None
        if hasattr(self._readers, 'conn') and self._readers.conn:
            self._readers.conn.close()
            self._readers.conn = None

    # ------------------------------------------------------------------
    # Memory_Hot (FIFO per-profile, capped at 300)
    # ------------------------------------------------------------------

    def add_to_hot(self, profile: str, role: str, content: str,
                   tokens_in: int = 0, tokens_out: int = 0,
                   metadata: dict = None, platform: str = "default") -> int:
        """Add a message to Memory_Hot. Enforces 300-row FIFO cap per profile."""
        w = self.writer
        cursor = w.execute(
            "INSERT INTO Memory_Hot (profile, role, content, tokens_in, tokens_out, metadata, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, role, content, tokens_in, tokens_out,
             json.dumps(metadata or {}), platform)
        )
        row_id = cursor.lastrowid

        # FIFO cap: delete oldest rows beyond 300 for this profile
        w.execute(
            "DELETE FROM Memory_Hot WHERE id IN ("
            "  SELECT id FROM Memory_Hot WHERE profile = ? "
            "  ORDER BY timestamp DESC LIMIT -1 OFFSET 300"
            ")",
            (profile,)
        )
        w.commit()
        return row_id

    def get_hot(self, profile: str, limit: int = 50) -> List[Dict]:
        """Get most recent Memory_Hot rows for a profile."""
        rows = self.reader().execute(
            "SELECT * FROM Memory_Hot WHERE profile = ? ORDER BY timestamp DESC LIMIT ?",
            (profile, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_command(self, profile: str) -> Optional[str]:
        """Get the most recent user command for a profile."""
        row = self.reader().execute(
            "SELECT content FROM Memory_Hot "
            "WHERE profile = ? AND role = 'user' "
            "ORDER BY timestamp DESC LIMIT 1",
            (profile,)
        ).fetchone()
        return row["content"] if row else None

    # ------------------------------------------------------------------
    # Memory_Warm
    # ------------------------------------------------------------------

    def add_to_warm(self, profile: str, role: str, content: str,
                    tokens_in: int = 0, tokens_out: int = 0,
                    metadata: dict = None, platform: str = "default") -> int:
        """Add a message to Memory_Warm."""
        w = self.writer
        cursor = w.execute(
            "INSERT INTO Memory_Warm (profile, role, content, tokens_in, tokens_out, metadata, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, role, content, tokens_in, tokens_out,
             json.dumps(metadata or {}), platform)
        )
        w.commit()
        return cursor.lastrowid

    def get_warm(self, profile: str, limit: int = 100) -> List[Dict]:
        """Get most recent Memory_Warm rows for a profile."""
        rows = self.reader().execute(
            "SELECT * FROM Memory_Warm WHERE profile = ? ORDER BY timestamp DESC LIMIT ?",
            (profile, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Memory_Cold (distilled facts only)
    # ------------------------------------------------------------------

    def add_to_cold(self, profile: str, category: str, fact: str,
                    source: str = "unknown", confidence: float = 0.5,
                    tags: list = None, metadata: dict = None) -> int:
        """Add a distilled fact to Memory_Cold. Source/confidence/tags required."""
        w = self.writer
        cursor = w.execute(
            "INSERT INTO Memory_Cold (profile, category, fact, source, confidence, tags, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (profile, category, fact, source, confidence,
             json.dumps(tags or []), json.dumps(metadata or {}))
        )
        w.commit()
        return cursor.lastrowid

    def get_cold(self, profile: str, category: str = None, limit: int = 50) -> List[Dict]:
        """Get Memory_Cold facts for a profile, optionally filtered by category."""
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

    # ------------------------------------------------------------------
    # Worker_State (per-worker key-value store)
    # ------------------------------------------------------------------

    def set_worker_state(self, worker: str, key: str, value: Any):
        """Set a worker state value (upsert)."""
        w = self.writer
        w.execute(
            "INSERT OR REPLACE INTO Worker_State (worker, key, value, updated_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (worker, key, json.dumps(value))
        )
        w.commit()

    def get_worker_state(self, worker: str, key: str, default: Any = None) -> Any:
        """Get a worker state value."""
        row = self.reader().execute(
            "SELECT value FROM Worker_State WHERE worker = ? AND key = ?",
            (worker, key)
        ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

    def get_all_worker_state(self, worker: str) -> Dict:
        """Get all state for a worker."""
        rows = self.reader().execute(
            "SELECT key, value FROM Worker_State WHERE worker = ?",
            (worker,)
        ).fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    # ------------------------------------------------------------------
    # Worker_Config (per-worker configuration)
    # ------------------------------------------------------------------

    def set_worker_config(self, worker: str, key: str, value: Any):
        """Set a worker config value (upsert)."""
        w = self.writer
        w.execute(
            "INSERT OR REPLACE INTO Worker_Config (worker, key, value, updated_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (worker, key, json.dumps(value))
        )
        w.commit()

    def get_worker_config(self, worker: str, key: str, default: Any = None) -> Any:
        """Get a worker config value."""
        row = self.reader().execute(
            "SELECT value FROM Worker_Config WHERE worker = ? AND key = ?",
            (worker, key)
        ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

    def get_all_worker_config(self, worker: str) -> Dict:
        """Get all config for a worker."""
        rows = self.reader().execute(
            "SELECT key, value FROM Worker_Config WHERE worker = ?",
            (worker,)
        ).fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    # ------------------------------------------------------------------
    # Earnings_Log
    # ------------------------------------------------------------------

    def log_earnings(self, worker: str, site: str, amount: float,
                     job_type: str = "unknown", metadata: dict = None):
        """Log an earnings entry."""
        w = self.writer
        w.execute(
            "INSERT INTO Earnings_Log (worker, site, amount, job_type, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (worker, site, amount, job_type, json.dumps(metadata or {}))
        )
        w.commit()

    def get_earnings(self, worker: str = None, site: str = None,
                     since: str = None) -> List[Dict]:
        """Get earnings entries, optionally filtered."""
        conditions = []
        params = []
        if worker:
            conditions.append("worker = ?")
            params.append(worker)
        if site:
            conditions.append("site = ?")
            params.append(site)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        where = " AND ".join(conditions) if conditions else "1"
        rows = self.reader().execute(
            f"SELECT * FROM Earnings_Log WHERE {where} ORDER BY timestamp DESC",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    def get_earnings_summary(self, worker: str = None,
                              since: str = None) -> Dict:
        """Get earnings summary (total per site)."""
        conditions = []
        params = []
        if worker:
            conditions.append("worker = ?")
            params.append(worker)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        where = " AND ".join(conditions) if conditions else "1"
        rows = self.reader().execute(
            f"SELECT site, SUM(amount) as total, COUNT(*) as count "
            f"FROM Earnings_Log WHERE {where} GROUP BY site ORDER BY total DESC",
            params
        ).fetchall()
        return {r["site"]: {"total": r["total"], "count": r["count"]} for r in rows}

    # ------------------------------------------------------------------
    # Checkpoints (restore/resume)
    # ------------------------------------------------------------------

    def save_checkpoint(self, profile: str, last_command: str,
                        context: dict = None, session_id: str = None) -> int:
        """Save a checkpoint for restore/resume."""
        w = self.writer
        cursor = w.execute(
            "INSERT OR REPLACE INTO Checkpoints (profile, last_command, context, session_id) "
            "VALUES (?, ?, ?, ?)",
            (profile, last_command, json.dumps(context or {}), session_id)
        )
        w.commit()
        return cursor.lastrowid

    def get_checkpoint(self, profile: str) -> Optional[Dict]:
        """Get the latest checkpoint for a profile."""
        row = self.reader().execute(
            "SELECT * FROM Checkpoints WHERE profile = ? ORDER BY timestamp DESC LIMIT 1",
            (profile,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Active_Tasks
    # ------------------------------------------------------------------

    def add_task(self, profile: str, task_id: str, description: str,
                 metadata: dict = None) -> int:
        """Register a new task."""
        w = self.writer
        cursor = w.execute(
            "INSERT OR IGNORE INTO Active_Tasks (profile, task_id, description, metadata) "
            "VALUES (?, ?, ?, ?)",
            (profile, task_id, description, json.dumps(metadata or {}))
        )
        w.commit()
        return cursor.lastrowid

    def update_task(self, task_id: str, status: str = None,
                    progress: float = None, error: str = None) -> bool:
        """Update task status/progress/error."""
        updates = []
        params = []
        if status:
            updates.append("status = ?")
            params.append(status)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if not updates:
            return False
        updates.append("updated_at = datetime('now')")
        params.append(task_id)
        w = self.writer
        w.execute(
            f"UPDATE Active_Tasks SET {', '.join(updates)} WHERE task_id = ?",
            params
        )
        w.commit()
        return True

    def get_tasks(self, profile: str = None, status: str = None) -> List[Dict]:
        """Get tasks, optionally filtered by profile and/or status."""
        conditions = []
        params = []
        if profile:
            conditions.append("profile = ?")
            params.append(profile)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions) if conditions else "1"
        rows = self.reader().execute(
            f"SELECT * FROM Active_Tasks WHERE {where} ORDER BY created_at DESC",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def log_event(self, profile: str, event_type: str,
                  event_data: dict = None, task_id: str = None,
                  session_id: str = None) -> int:
        """Write an event to the Logs table."""
        w = self.writer
        cursor = w.execute(
            "INSERT INTO Logs (profile, event_type, event_data, task_id, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (profile, event_type, json.dumps(event_data or {}), task_id, session_id)
        )
        w.commit()
        return cursor.lastrowid

    def get_logs(self, profile: str = None, event_type: str = None,
                 limit: int = 100) -> List[Dict]:
        """Get recent log entries."""
        conditions = []
        params = []
        if profile:
            conditions.append("profile = ?")
            params.append(profile)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        where = " AND ".join(conditions) if conditions else "1"
        rows = self.reader().execute(
            f"SELECT * FROM Logs WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

db = Database()
