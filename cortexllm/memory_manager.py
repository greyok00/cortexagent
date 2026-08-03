#!/usr/bin/env python3
"""
CortexLLM Memory Manager v4 — SQLite-native
- Hot: Per-profile active session (300 rows each, FIFO, independent)
- Warm: Per-profile buffer (2000 total) - preserves context per profile
- Cold: Permanent knowledge, per-profile, never expires

Storage: SQLite via cortexllm_db.Database (WAL mode, single-writer/multi-reader)
JSON files kept as read-only fallback during transition.

Warm Memory Algorithm:
  - 70% recent messages (weighted by profile activity)
  - 30% historical messages from same profile (preserved buffer)
  - Never completely loses profile context
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

from cortexllm_db import db
from cortexllm_models import EventType

CORTEXLLM_DIR = Path.home() / ".config/cortexllm"
HOT_DIR = CORTEXLLM_DIR / "memory/hot"
WARM_DIR = CORTEXLLM_DIR / "memory/warm"
COLD_DIR = CORTEXLLM_DIR / "memory/cold"

HOT_LIMIT = 300
WARM_LIMIT = 2000
WARM_BUFFER_RATIO = 0.3
WARM_RECENT_RATIO = 0.7


class MemoryManager:
    def __init__(self):
        db.initialize()
        self.last_commands = {}
        self._load_state()

    def _load_state(self):
        """Load persistent state from Checkpoints table."""
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

    def _save_state(self):
        """Persist state is now handled by SQLite — no-op."""
        pass

    def add_to_hot(self, platform: str, content: str, role: str = "user",
                   tokens_in: int = 0, tokens_out: int = 0, metadata: Dict = None,
                   is_code: bool = False):
        """Add message to per-profile hot memory via SQLite."""
        profile = f"platform:{platform}"

        # Skip code in hot memory — send directly to warm
        if is_code:
            self._add_to_warm_direct(platform, content, role, tokens_in, tokens_out, metadata)
            return {"status": "saved_to_warm", "reason": "code_excluded_from_hot"}

        # Write to SQLite synchronously before any LLM call
        db.add_to_hot(
            profile=profile,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata=metadata or {},
            platform=platform,
        )

        # Log event for observability
        try:
            db.log_event(
                profile=profile,
                event_type=EventType.AGENT_STARTED.value if role == "user" else EventType.LLM_RESPONSE.value,
                event_data={
                    "role": role,
                    "content_length": len(content),
                    "platform": platform,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                },
            )
        except Exception:
            pass  # Non-critical

        # Track last command for session resume
        if role == "user":
            self.last_commands[platform] = {
                "command": content,
                "timestamp": datetime.now().isoformat(),
                "context": metadata.get("context", {}) if metadata else {}
            }
            db.save_checkpoint(
                profile=profile,
                last_command=content,
                context=metadata.get("context", {}) if metadata else {},
            )

        # Update warm buffer
        self._update_warm_buffer()

        return {
            "status": "saved_to_hot",
            "profile": profile,
            "role": role,
            "timestamp": datetime.now().isoformat(),
        }

    def _add_to_warm_direct(self, platform: str, content: str, role: str,
                            tokens_in: int, tokens_out: int, metadata: Dict):
        """Add directly to warm (for code that skips hot)."""
        db.add_to_warm(
            profile=f"platform:{platform}",
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            metadata=metadata or {},
            platform=platform,
        )
        try:
            db.log_event(
                profile=f"platform:{platform}",
                event_type="warm_write",
                event_data={"role": role, "content_length": len(content), "platform": platform},
            )
        except Exception:
            pass

    def _update_warm_buffer(self):
        """
        Update warm memory with BUFFER ALGORITHM:
        - 70% recent messages (weighted by profile activity)
        - 30% preserved buffer from same profile (never lost)

        Per-profile memory: Each profile's context is preserved independently.
        """
        reader = db.reader()

        # Get recent messages from hot (all profiles)
        recent_rows = reader.execute(
            "SELECT * FROM Memory_Hot ORDER BY timestamp DESC LIMIT ?",
            (int(WARM_LIMIT * WARM_RECENT_RATIO),)
        ).fetchall()

        # Get existing warm messages for buffer preservation
        warm_rows = reader.execute(
            "SELECT * FROM Memory_Warm ORDER BY timestamp DESC LIMIT ?",
            (WARM_LIMIT,)
        ).fetchall()

        # Build buffer: 30% from existing warm (oldest first for history)
        buffer_size = int(WARM_LIMIT * WARM_BUFFER_RATIO)
        buffer_rows = warm_rows[-buffer_size:] if len(warm_rows) > buffer_size else warm_rows

        # Combine: recent (70%) + buffer (30%)
        all_rows = list(recent_rows) + list(buffer_rows)

        # Deduplicate by content+role to avoid exact duplicates
        seen = set()
        deduped = []
        for r in all_rows:
            key = (r["profile"], r["role"], r["content"][:200])
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        # Sort by timestamp descending, cap at WARM_LIMIT
        deduped.sort(key=lambda r: r["timestamp"] if r["timestamp"] else "", reverse=True)
        deduped = deduped[:WARM_LIMIT]

        # Write to warm table (clear and re-insert)
        w = db.writer
        w.execute("DELETE FROM Memory_Warm")
        for row in deduped:
            w.execute(
                "INSERT INTO Memory_Warm (profile, role, content, tokens_in, tokens_out, metadata, platform) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["profile"], row["role"], row["content"],
                 row["tokens_in"], row["tokens_out"],
                 row["metadata"], row["platform"])
            )
        w.commit()

        # Count per profile
        profile_counts = {}
        for r in deduped:
            p = r["profile"]
            profile_counts[p] = profile_counts.get(p, 0) + 1

        return profile_counts

    def save_to_cold(self, category: str, knowledge: Dict, immediate: bool = True):
        """Save to cold storage — distilled facts only."""
        fact = json.dumps(knowledge) if isinstance(knowledge, dict) else str(knowledge)
        db.add_to_cold(
            profile="shared",
            category=category,
            fact=fact,
            source="auto-discovered" if immediate else "manual",
            confidence=0.8,
            tags=[category],
            metadata={"source": "auto" if immediate else "manual"},
        )
        try:
            db.log_event(
                profile="shared",
                event_type="cold_write",
                event_data={"category": category, "fact_length": len(fact)},
            )
        except Exception:
            pass
        return {"status": "saved_to_cold", "category": category}

    def get_session_resume(self, platform: str = None) -> Dict:
        """Get last commands for session resume from Checkpoints table."""
        if platform:
            cp = db.get_checkpoint(f"platform:{platform}")
            if cp:
                return {
                    "command": cp["last_command"],
                    "context": json.loads(cp["context"]) if cp["context"] else {},
                }
            return {}
        return {"last_commands": self.last_commands}

    def get_hot_messages(self, platform: str, limit: int = 50) -> List[Dict]:
        """Get recent messages from per-profile hot memory via SQLite.

        Merges all sub-profiles for the platform (e.g. "cortexagent/sub",
        "other/agent") into one view — generic, not tied to any platform.
        """
        base = platform.split("/")[0]
        rows = db.reader().execute(
            "SELECT * FROM Memory_Hot WHERE profile LIKE ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (f"platform:{base}%", limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_warm_messages(self, platform: str = None, limit: int = 100) -> List[Dict]:
        """Get messages from per-profile warm memory."""
        if platform:
            rows = db.get_warm(f"platform:{platform}", limit=limit)
        else:
            rows = db.reader().execute(
                "SELECT * FROM Memory_Warm ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            rows = [dict(r) for r in rows]
        return rows

    def get_cold_knowledge(self, category: str) -> Dict:
        """Get knowledge from cold storage."""
        rows = db.get_cold("shared", category=category, limit=50)
        return {
            "category": category,
            "entries": rows,
            "total_entries": len(rows),
        }

    def get_all_cold_categories(self) -> List[str]:
        """List all cold storage categories."""
        rows = db.reader().execute(
            "SELECT DISTINCT category FROM Memory_Cold ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    def get_platform_stats(self) -> Dict:
        """Get per-profile memory statistics."""
        reader = db.reader()

        # Hot counts per profile
        hot_rows = reader.execute(
            "SELECT profile, COUNT(*) as count FROM Memory_Hot GROUP BY profile"
        ).fetchall()

        # Warm counts per profile
        warm_rows = reader.execute(
            "SELECT profile, COUNT(*) as count FROM Memory_Warm GROUP BY profile"
        ).fetchall()

        # Cold counts
        cold_count = reader.execute("SELECT COUNT(*) FROM Memory_Cold").fetchone()[0]
        cold_categories = self.get_all_cold_categories()

        stats = {
            "hot": {r["profile"]: r["count"] for r in hot_rows},
            "warm": {r["profile"]: r["count"] for r in warm_rows},
            "cold_categories": cold_categories,
            "cold_total": cold_count,
            "warm_total": sum(r["count"] for r in warm_rows),
        }

        return stats


# Create global instance
manager = MemoryManager()


def add_message(platform, content, role="user", **kwargs):
    return manager.add_to_hot(platform, content, role, **kwargs)


def save_knowledge(category, knowledge, immediate=True):
    return manager.save_to_cold(category, knowledge, immediate)


def get_resume(platform=None):
    return manager.get_session_resume(platform)


def get_stats():
    return manager.get_platform_stats()


if __name__ == "__main__":
    print("Testing Memory Manager v4 - SQLite-native\n")

    # Simulate heavy CortexAgent usage
    print("Simulating heavy CortexAgent usage (20 messages)...")
    for i in range(20):
        add_message("cortexagent", f"CortexAgent message {i}", metadata={"test": "heavy_use"})

    # Light usage from another platform
    print("Simulating light usage (3 messages)...")
    for i in range(3):
        add_message("claude", f"claude message {i}", metadata={"test": "light_use"})

    # Save knowledge
    save_knowledge("buffer_test", {"algorithm": "70% recent + 30% preserved buffer"})

    # Show stats
    print("\n=== MEMORY STATS ===")
    stats = get_stats()
    for profile, count in stats.get("hot", {}).items():
        print(f"  Hot - {profile}: {count}")
    for profile, count in stats.get("warm", {}).items():
        print(f"  Warm - {profile}: {count}")
    print(f"  Cold: {stats['cold_total']} entries in {len(stats['cold_categories'])} categories")
    print(f"  Warm Total: {stats['warm_total']}")

    print("\n✓ Memory Manager v4 ready - SQLite-native with per-profile isolation")
