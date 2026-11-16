#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from memory.db import db

HOT_LIMIT = 300

class MemoryManager:
    def __init__(self):
        db._ensure_initialized()
        self.last_commands: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        try:
            rows = db.reader().execute(
                "SELECT profile, last_command, context FROM Checkpoints "
                "WHERE id IN (SELECT MAX(id) FROM Checkpoints GROUP BY profile)"
            ).fetchall()
            for row in rows:
                self.last_commands[row["profile"]] = {
                    "command": row["last_command"],
                    "context": json.loads(row["context"]) if row["context"] else {},
                }
        except Exception:
            self.last_commands = {}

    def add_to_hot(self, platform: str, content: str, role: str = "user",
                   tokens_in: int = 0, tokens_out: int = 0,
                   metadata: Optional[Dict[str, Any]] = None,
                   is_code: bool = False):
        profile = f"platform:{platform}"

        # Memory_Hot schema is (profile, key, value, timestamp): a chat
        # message is one insert with a stable key and the message itself as
        # the JSON value.
        db.write_memory_hot(
            profile=profile, key="chat",
            value={
                "role": role, "content": content,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "metadata": metadata or {}, "platform": platform,
            },
        )

        try:
            db.write_log(
                "info",
                json.dumps({
                    "profile": profile,
                    "event": "agent_started" if role == "user" else "llm_response",
                    "role": role, "content_length": len(content),
                    "platform": platform, "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                }),
            )
        except Exception:
            pass

        if role == "user":
            self.last_commands[platform] = {
                "command": content,
                "timestamp": datetime.now().isoformat(),
                "context": (metadata or {}).get("context", {}),
            }
            db.write_checkpoint(
                profile=profile,
                last_command=content,
                context=(metadata or {}).get("context", {}),
            )

        return {
            "status": "saved_to_hot",
            "profile": profile,
            "role": role,
            "timestamp": datetime.now().isoformat(),
        }

    def save_to_cold(self, category: str, knowledge: Any, immediate: bool = True,
                     platform: str = "shared"):
        fact = json.dumps(knowledge) if isinstance(knowledge, dict) else str(knowledge)
        # Memory_Cold schema is (category, confidence, source, tags, entry);
        # the entry JSON carries the fact plus its platform.
        db.write_memory_cold(
            category=category,
            confidence=0.8,
            source="auto-discovered" if immediate else "manual",
            tags=[category],
            entry={"fact": fact, "platform": platform,
                   "source": "auto" if immediate else "manual"},
        )
        try:
            db.write_log(
                "info",
                json.dumps({
                    "profile": f"platform:{platform}",
                    "event": "cold_write",
                    "category": category, "fact_length": len(fact),
                }),
            )
        except Exception:
            pass
        return {"status": "saved_to_cold", "category": category}

    def get_session_resume(self, platform: Optional[str] = None) -> Dict[str, Any]:
        if platform:
            row = db.reader().execute(
                "SELECT last_command, context FROM Checkpoints "
                "WHERE profile = ? ORDER BY id DESC LIMIT 1",
                (f"platform:{platform}",),
            ).fetchone()
            if row:
                return {
                    "command": row["last_command"],
                    "context": json.loads(row["context"]) if row["context"] else {},
                }
            return {}
        return {"last_commands": self.last_commands}

    def get_hot_messages(self, platform: str, limit: int = 50) -> List[Dict[str, Any]]:
        profile = f"platform:{platform}"
        rows = db.reader().execute(
            "SELECT value, timestamp FROM Memory_Hot "
            "WHERE profile = ? ORDER BY id DESC LIMIT ?",
            (profile, limit),
        ).fetchall()
        out = []
        for r in rows:
            try:
                msg = json.loads(r["value"])
            except (ValueError, TypeError):
                continue
            msg.setdefault("timestamp", r["timestamp"])
            out.append(msg)
        return out

    def get_warm_messages(self, platform: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:

        return []

    def get_cold_knowledge(self, platform: str, category: str) -> Dict[str, Any]:
        rows = db.reader().execute(
            "SELECT entry FROM Memory_Cold "
            "WHERE category = ? ORDER BY id DESC LIMIT 50",
            (category,),
        ).fetchall()
        entries = []
        for r in rows:
            try:
                entries.append(json.loads(r["entry"]))
            except (ValueError, TypeError):
                continue
        return {"category": category, "entries": entries, "total_entries": len(entries)}

    def get_all_cold_categories(self, platform: str) -> List[str]:
        rows = db.reader().execute(
            "SELECT DISTINCT category FROM Memory_Cold ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    def get_platform_stats(self, platform: Optional[str] = None) -> Dict[str, Any]:
        reader = db.reader()
        params: tuple = ()
        where = ""
        if platform:
            where = "WHERE profile = ?"
            params = (f"platform:{platform}",)
        hot_rows = reader.execute(
            f"SELECT profile, COUNT(*) as count FROM Memory_Hot {where} GROUP BY profile", params
        ).fetchall()
        # Memory_Cold is a shared store (no profile column): count it whole.
        cold_count = reader.execute(
            "SELECT COUNT(*) FROM Memory_Cold"
        ).fetchone()[0]
        cold_cats = self.get_all_cold_categories(platform or "shared")
        return {
            "hot": {r["profile"]: r["count"] for r in hot_rows},
            "cold_total": cold_count,
            "cold_categories": cold_cats,
        }

manager = MemoryManager()

def add_message(platform: str, content: str, role: str = "user", **kwargs):
    return manager.add_to_hot(platform, content, role, **kwargs)

def save_knowledge(category: str, knowledge: Any, immediate: bool = True,
                   platform: str = "shared"):
    return manager.save_to_cold(category, knowledge, immediate, platform)

def get_resume(platform: Optional[str] = None):
    return manager.get_session_resume(platform)

def get_stats(platform: Optional[str] = None):
    return manager.get_platform_stats(platform)
