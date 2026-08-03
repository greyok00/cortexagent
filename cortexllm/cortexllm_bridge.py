#!/usr/bin/env python3
"""
CortexLLM Memory Bridge — direct database access for CortexAgent.
Uses the SAME database as Claude's CortexLLM MCP server.
No duplicate memory, no second database.

Usage:
    from cortexllm_bridge import memory
    memory.write("profile", "user", "content")
    results = memory.search("query")
    context = memory.get_context(limit=50)
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

CORTEXLLM_DB = Path.home() / ".config/cortexllm/cortexllm.db"


class CortexLLM:
    """Direct CortexLLM database access — same DB as Claude's MCP server."""

    def __init__(self, db_path: Path = CORTEXLLM_DB):
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def write(self, profile: str, role: str, content: str,
              tokens_in: int = 0, tokens_out: int = 0,
              metadata: Optional[dict] = None, platform: str = "cortexagent"):
        """Write to CortexLLM hot memory (same table Claude uses)."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO Memory_Hot (profile, role, content, tokens_in,
                   tokens_out, metadata, platform)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (profile, role, content, tokens_in, tokens_out,
                 json.dumps(metadata or {}), platform)
            )
            conn.commit()
        finally:
            conn.close()

    def write_warm(self, profile: str, role: str, content: str,
                   tokens_in: int = 0, tokens_out: int = 0,
                   metadata: Optional[dict] = None, platform: str = "cortexagent"):
        """Write to CortexLLM warm memory."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO Memory_Warm (profile, role, content, tokens_in,
                   tokens_out, metadata, platform)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (profile, role, content, tokens_in, tokens_out,
                 json.dumps(metadata or {}), platform)
            )
            conn.commit()
        finally:
            conn.close()

    def write_cold(self, category: str, data: dict, platform: str = "cortexagent"):
        """Write to CortexLLM cold memory."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO Memory_Cold (profile, content, metadata, platform)
                   VALUES (?, ?, ?, ?)""",
                (category, json.dumps(data), json.dumps({
                    "discovered_at": datetime.now().isoformat()
                }), platform)
            )
            conn.commit()
        finally:
            conn.close()

    def search(self, query: str, limit: int = 10, table: str = "Memory_Warm"):
        """Search across CortexLLM memory (same as MCP search)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""SELECT id, profile, role, content, timestamp, metadata,
                    platform FROM {table}
                    WHERE content LIKE ? ORDER BY id DESC LIMIT ?""",
                (f"%{query}%", limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_context(self, limit: int = 50, platform: str = "cortexagent"):
        """Get recent context from CortexLLM warm memory."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT id, profile, role, content, timestamp, platform
                   FROM Memory_Warm
                   WHERE platform = ? OR platform = 'default'
                   ORDER BY id DESC LIMIT ?""",
                (platform, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_recent(self, limit: int = 20, platform: str = "cortexagent"):
        """Get most recent memory entries."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT id, profile, role, substr(content, 1, 200) as content,
                   timestamp, platform FROM Memory_Hot
                   WHERE platform = ? OR platform = 'default'
                   ORDER BY id DESC LIMIT ?""",
                (platform, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self):
        """Get memory statistics."""
        conn = self._connect()
        try:
            hot = conn.execute("SELECT COUNT(*) as c FROM Memory_Hot").fetchone()
            warm = conn.execute("SELECT COUNT(*) as c FROM Memory_Warm").fetchone()
            cold = conn.execute("SELECT COUNT(*) as c FROM Memory_Cold").fetchone()
            return {
                "hot": hot["c"],
                "warm": warm["c"],
                "cold": cold["c"],
                "database": str(self.db_path)
            }
        finally:
            conn.close()


# Singleton — CortexAgent memory bridge instance
memory = CortexLLM()
