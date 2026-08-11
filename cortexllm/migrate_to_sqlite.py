#!/usr/bin/env python3
"""
CortexLLM JSON → SQLite Migration Script

Reads existing JSON memory files from ~/.config/cortexllm/memory/
and migrates all data into the SQLite database.

Preserves:
  - Hot memory (per-platform JSON files → Memory_Hot table)
  - Warm memory (per_profile.json → Memory_Warm table)
  - Cold memory (per-category JSON files → Memory_Cold table)
  - Checkpoints (memory_state.json → Checkpoints table)

Safe to run multiple times — skips already-migrated rows via idempotency keys.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Ensure we can import from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from cortexllm_db import db, DB_PATH

MEMORY_DIR = Path.home() / ".config/cortexllm/memory"
HOT_DIR = MEMORY_DIR / "hot"
WARM_DIR = MEMORY_DIR / "warm"
COLD_DIR = MEMORY_DIR / "cold"
STATE_FILE = Path.home() / ".config/cortexllm/memory_state.json"

# Track migration stats
stats = {
    "hot_migrated": 0,
    "hot_skipped": 0,
    "warm_migrated": 0,
    "warm_skipped": 0,
    "cold_migrated": 0,
    "cold_skipped": 0,
    "checkpoints_migrated": 0,
    "errors": [],
}


def migrate_hot():
    """Migrate per-platform hot memory JSON files to Memory_Hot table."""
    print("\n--- Hot Memory ---")
    if not HOT_DIR.exists():
        print("  No hot memory directory found.")
        return

    for fpath in sorted(HOT_DIR.glob("*.json*")):
        if fpath.name.endswith(".tmp"):
            continue
        try:
            if fpath.suffix == ".jsonl":
                # NDJSON: one JSON object per line
                lines = fpath.read_text().strip().split('\n')
                messages = [json.loads(line) for line in lines if line.strip()]
                platform = fpath.stem
            else:
                data = json.loads(fpath.read_text())
                # Handle both list and {platform, messages} formats
                if isinstance(data, dict):
                    platform = data.get("platform", fpath.stem)
                    messages = data.get("messages", [])
                elif isinstance(data, list):
                    platform = fpath.stem
                    messages = data
                else:
                    continue
        except (json.JSONDecodeError, IOError) as e:
            stats["errors"].append(f"Failed to read {fpath.name}: {e}")
            continue

        profile = f"platform:{platform}"
        for msg in messages:
            if not isinstance(msg, dict) or "content" not in msg:
                continue
            try:
                db.add_to_hot(
                    profile=profile,
                    role=msg.get("role", "user"),
                    content=msg["content"],
                    tokens_in=msg.get("tokens_in", 0),
                    tokens_out=msg.get("tokens_out", 0),
                    metadata=msg.get("metadata", {}),
                    platform=platform,
                )
                stats["hot_migrated"] += 1
            except Exception as e:
                stats["errors"].append(f"Hot insert error ({fpath.name}): {e}")
                stats["hot_skipped"] += 1

        print(f"  {fpath.name}: {len(messages)} messages → {stats['hot_migrated']} total")


def migrate_warm():
    """Migrate warm memory (per_profile.json) to Memory_Warm table."""
    print("\n--- Warm Memory ---")
    warm_file = WARM_DIR / "per_profile.json"
    if not warm_file.exists():
        print("  No per_profile.json found.")
        return

    try:
        data = json.loads(warm_file.read_text())
    except (json.JSONDecodeError, IOError) as e:
        stats["errors"].append(f"Failed to read per_profile.json: {e}")
        return

    if isinstance(data, dict):
        messages = data.get("messages", [])
    elif isinstance(data, list):
        messages = data
    else:
        messages = []

    for msg in messages:
        if not isinstance(msg, dict) or "content" not in msg:
            continue
        try:
            profile = msg.get("profile", "shared")
            db.add_to_warm(
                profile=profile,
                role=msg.get("role", "user"),
                content=msg["content"],
                tokens_in=msg.get("tokens_in", 0),
                tokens_out=msg.get("tokens_out", 0),
                metadata=msg.get("metadata", {}),
                platform=msg.get("platform", "default"),
            )
            stats["warm_migrated"] += 1
        except Exception as e:
            stats["errors"].append(f"Warm insert error: {e}")
            stats["warm_skipped"] += 1

    print(f"  {len(messages)} messages → {stats['warm_migrated']} total")


def migrate_cold():
    """Migrate cold memory (per-category JSON files) to Memory_Cold table."""
    print("\n--- Cold Memory ---")
    if not COLD_DIR.exists():
        print("  No cold memory directory found.")
        return

    for fpath in sorted(COLD_DIR.glob("*.json")):
        try:
            data = json.loads(fpath.read_text())
        except (json.JSONDecodeError, IOError) as e:
            stats["errors"].append(f"Failed to read {fpath.name}: {e}")
            continue

        category = fpath.stem
        entries = []

        if isinstance(data, dict):
            entries = data.get("entries", [data])
        elif isinstance(data, list):
            entries = data

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                # Extract fact text
                knowledge = entry.get("knowledge", entry)
                if isinstance(knowledge, dict):
                    fact = json.dumps(knowledge)
                else:
                    fact = str(knowledge)

                db.add_to_cold(
                    profile="shared",
                    category=category,
                    fact=fact,
                    source=entry.get("source", "migration"),
                    confidence=entry.get("confidence", 0.8),
                    tags=entry.get("tags", [category]),
                    metadata=entry.get("metadata", {}),
                )
                stats["cold_migrated"] += 1
            except Exception as e:
                stats["errors"].append(f"Cold insert error ({fpath.name}): {e}")
                stats["cold_skipped"] += 1

        print(f"  {fpath.name}: {len(entries)} entries → {stats['cold_migrated']} total")


def migrate_checkpoints():
    """Migrate memory_state.json last_commands to Checkpoints table."""
    print("\n--- Checkpoints ---")
    if not STATE_FILE.exists():
        print("  No memory_state.json found.")
        return

    try:
        state = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, IOError) as e:
        stats["errors"].append(f"Failed to read memory_state.json: {e}")
        return

    last_commands = state.get("last_commands", {})
    for profile, cmd_info in last_commands.items():
        if isinstance(cmd_info, dict) and "command" in cmd_info:
            try:
                db.save_checkpoint(
                    profile=profile,
                    last_command=cmd_info["command"],
                    context=cmd_info.get("context", {}),
                    session_id=cmd_info.get("session_id"),
                )
                stats["checkpoints_migrated"] += 1
            except Exception as e:
                stats["errors"].append(f"Checkpoint error ({profile}): {e}")

    print(f"  {len(last_commands)} profiles → {stats['checkpoints_migrated']} checkpoints")


def verify_migration():
    """Verify the migration by querying each table."""
    print("\n--- Verification ---")
    reader = db.reader()

    tables = [
        ("Memory_Hot", "SELECT COUNT(*) FROM Memory_Hot"),
        ("Memory_Warm", "SELECT COUNT(*) FROM Memory_Warm"),
        ("Memory_Cold", "SELECT COUNT(*) FROM Memory_Cold"),
        ("Checkpoints", "SELECT COUNT(*) FROM Checkpoints"),
        ("Active_Tasks", "SELECT COUNT(*) FROM Active_Tasks"),
        ("Logs", "SELECT COUNT(*) FROM Logs"),
    ]

    for name, query in tables:
        count = reader.execute(query).fetchone()[0]
        print(f"  {name}: {count} rows")

    # Show profiles
    profiles = reader.execute(
        "SELECT DISTINCT profile FROM Memory_Hot ORDER BY profile"
    ).fetchall()
    if profiles:
        print(f"\n  Profiles in Memory_Hot: {[p['profile'] for p in profiles]}")


def main():
    print("=" * 60)
    print("  CortexLLM JSON → SQLite Migration")
    print("=" * 60)
    print(f"  Source: {MEMORY_DIR}")
    print(f"  Target: {DB_PATH}")
    print(f"  Started: {datetime.now().isoformat()}")
    print("=" * 60)

    # Initialize database
    print("\nInitializing database...")
    db.initialize()
    print("  Done.")

    # Run migrations
    migrate_hot()
    migrate_warm()
    migrate_cold()
    migrate_checkpoints()

    # Verify
    verify_migration()

    # Summary
    print("\n" + "=" * 60)
    print("  Migration Summary")
    print("=" * 60)
    print(f"  Hot:      {stats['hot_migrated']} migrated, {stats['hot_skipped']} skipped")
    print(f"  Warm:     {stats['warm_migrated']} migrated, {stats['warm_skipped']} skipped")
    print(f"  Cold:     {stats['cold_migrated']} migrated, {stats['cold_skipped']} skipped")
    print(f"  Checkpoints: {stats['checkpoints_migrated']} migrated")
    if stats["errors"]:
        print(f"\n  Errors ({len(stats['errors'])}):")
        for err in stats["errors"][:10]:
            print(f"    - {err}")
    print("=" * 60)


if __name__ == "__main__":
    main()
