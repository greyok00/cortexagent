#!/usr/bin/env python3
"""memory/manager.py — CortexAgent memory manager (hot/warm/cold).

- Hot: per-platform FIFO cap 300
- Warm: per-platform buffer, 70% recent + 30% preserved, deduped
- Cold: distilled facts by category
"""
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
WARM_LIMIT = 2000
WARM_RECENT_RATIO = 0.7
WARM_BUFFER_RATIO = 0.3


class MemoryManager:
    def __init__(self):
        db.initialize()
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

        if is_code:
            self._add_to_warm_direct(platform, content, role, tokens_in, tokens_out, metadata)
            return {"status": "saved_to_warm", "reason": "code_excluded_from_hot"}

        db.add_to_hot(
            profile=profile, role=role, content=content,
            tokens_in=tokens_in, tokens_out=tokens_out,
            metadata=metadata or {}, platform=platform,
        )

        try:
            db.log_event(
                profile=profile,
                event_type="agent_started" if role == "user" else "llm_response",
                event_data={
                    "role": role, "content_length": len(content),
                    "platform": platform, "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                },
            )
        except Exception:
            pass

        if role == "user":
            self.last_commands[platform] = {
                "command": content,
                "timestamp": datetime.now().isoformat(),
                "context": (metadata or {}).get("context", {}),
            }
            db.save_checkpoint(
                profile=profile,
                last_command=content,
                context=(metadata or {}).get("context", {}),
            )

        self._update_warm_buffer()

        return {
            "status": "saved_to_hot",
            "profile": profile,
            "role": role,
            "timestamp": datetime.now().isoformat(),
        }

    def _add_to_warm_direct(self, platform: str, content: str, role: str,
                            tokens_in: int, tokens_out: int,
                            metadata: Optional[Dict[str, Any]]):
        db.add_to_warm(
            profile=f"platform:{platform}", role=role, content=content,
            tokens_in=tokens_in, tokens_out=tokens_out,
            metadata=metadata or {}, platform=platform,
        )
        try:
            db.log_event(
                profile=f"platform:{platform}",
                event_type="warm_write",
                event_data={"role": role, "content_length": len(content), "platform": platform},
            )
        except Exception:
            pass

    def _update_warm_buffer(self) -> None:
        reader = db.reader()
        recent_rows = reader.execute(
            "SELECT * FROM Memory_Hot ORDER BY timestamp DESC LIMIT ?",
            (int(WARM_LIMIT * WARM_RECENT_RATIO),)
        ).fetchall()
        warm_rows = reader.execute(
            "SELECT * FROM Memory_Warm ORDER BY timestamp DESC LIMIT ?",
            (WARM_LIMIT,)
        ).fetchall()

        buffer_size = int(WARM_LIMIT * WARM_BUFFER_RATIO)
        buffer_rows = warm_rows[-buffer_size:] if len(warm_rows) > buffer_size else warm_rows

        all_rows = list(recent_rows) + list(buffer_rows)
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for r in all_rows:
            key = (r["profile"], r["role"], r["content"][:200])
            if key not in seen:
                seen.add(key)
                deduped.append(dict(r))

        deduped.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
        deduped = deduped[:WARM_LIMIT]

        w = db.writer
        w.execute("DELETE FROM Memory_Warm")
        for row in deduped:
            w.execute(
                "INSERT INTO Memory_Warm (profile, role, content, tokens_in, tokens_out, metadata, platform) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["profile"], row["role"], row["content"],
                 row.get("tokens_in", 0), row.get("tokens_out", 0),
                 row.get("metadata", "{}"), row.get("platform", "default"))
            )
        w.commit()

        profile_counts: Dict[str, int] = {}
        for r in deduped:
            p = r["profile"]
            profile_counts[p] = profile_counts.get(p, 0) + 1
        return profile_counts

    def save_to_cold(self, category: str, knowledge: Any, immediate: bool = True,
                     platform: str = "shared"):
        fact = json.dumps(knowledge) if isinstance(knowledge, dict) else str(knowledge)
        db.add_to_cold(
            profile=platform,
            category=category,
            fact=fact,
            source="auto-discovered" if immediate else "manual",
            confidence=0.8,
            tags=[category],
            metadata={"source": "auto" if immediate else "manual"},
        )
        try:
            db.log_event(
                profile=platform,
                event_type="cold_write",
                event_data={"category": category, "fact_length": len(fact)},
            )
        except Exception:
            pass
        return {"status": "saved_to_cold", "category": category}

    def get_session_resume(self, platform: Optional[str] = None) -> Dict[str, Any]:
        if platform:
            cp = db.get_checkpoint(f"platform:{platform}")
            if cp:
                return {
                    "command": cp["last_command"],
                    "context": json.loads(cp["context"]) if cp["context"] else {},
                }
            return {}
        return {"last_commands": self.last_commands}

    def get_hot_messages(self, platform: str, limit: int = 50) -> List[Dict[str, Any]]:
        profile = f"platform:{platform}"
        rows = db.get_hot(profile, limit=limit)
        return rows

    def get_warm_messages(self, platform: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
        if platform:
            rows = db.get_warm(f"platform:{platform}", limit=limit)
        else:
            rows = db.reader().execute(
                "SELECT * FROM Memory_Warm ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            rows = [dict(r) for r in rows]
        return rows

    def get_cold_knowledge(self, platform: str, category: str) -> Dict[str, Any]:
        rows = db.get_cold(platform, category=category, limit=50)
        return {"category": category, "entries": rows, "total_entries": len(rows)}

    def get_all_cold_categories(self, platform: str) -> List[str]:
        return db.get_cold_categories(platform)

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
        warm_rows = reader.execute(
            f"SELECT profile, COUNT(*) as count FROM Memory_Warm {where} GROUP BY profile", params
        ).fetchall()
        cold_count = reader.execute(
            f"SELECT COUNT(*) FROM Memory_Cold {where}", params
        ).fetchone()[0]
        cold_cats = self.get_all_cold_categories(platform or "shared")
        return {
            "hot": {r["profile"]: r["count"] for r in hot_rows},
            "warm": {r["profile"]: r["count"] for r in warm_rows},
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
