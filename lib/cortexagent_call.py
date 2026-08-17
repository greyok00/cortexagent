#!/usr/bin/env python3
"""cortexagent_call — hook-friendly CLI into the CortexAgent memory system.

Thin shim over the in-repo memory manager:
  hot write (300-row FIFO cap) + checkpoint (session resume)
  prune/dedup (2000 cap, 70/30) + event logging.

Used by cortexagent hooks to save prompts/responses and pull recent context.

Usage:
    cortexagent_call.py recent --limit 12
    cortexagent_call.py write --role user --content "..."
    cortexagent_call.py write --role assistant --content "..."
    cortexagent_call.py search "query" --limit 10
"""
import argparse
import json
import os
import sys
from pathlib import Path

PLATFORM = os.environ.get("CORTEXAGENT_PLATFORM", "cortexagent")

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    from memory.manager import manager
    from memory.db import db
except Exception as e:
    print(f"cortexagent_call: memory import failed ({e})", file=sys.stderr)
    manager = None
    db = None


def add_message(content: str, role: str = "user"):
    """Save through the memory manager pipeline (cap + checkpoint + prune)."""
    if manager is None:
        return False
    try:
        manager.add_to_hot(PLATFORM, content, role=role)
        return True
    except Exception as e:
        print(f"cortexagent_call: pipeline write failed ({e})", file=sys.stderr)
        return False


def get_hot(limit: int = 12):
    """Recent hot messages for this platform, oldest-first (for injection)."""
    if manager is None:
        return []
    try:
        rows = manager.get_hot_messages(PLATFORM, limit=limit)
        return list(reversed(rows))
    except Exception:
        return []


def get_resume():
    """Last user request + context for quick session recovery."""
    if manager is None:
        return {}
    try:
        return manager.get_session_resume(PLATFORM) or {}
    except Exception:
        return {}


def search(query: str, limit: int = 10):
    """Read-only hot-memory search."""
    if db is None:
        return []
    try:
        rows = db.reader().execute(
            "SELECT role, content, timestamp FROM Memory_Hot "
            "WHERE profile = ? AND LOWER(content) LIKE ? ORDER BY id DESC LIMIT ?",
            (f"platform:{PLATFORM}", f"%{query.lower()}%", limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]
    except Exception:
        return []


def _fmt_recent(limit: int):
    """Format resume + recent hot memory for SessionStart injection."""
    lines = []
    resume = get_resume()
    if resume and resume.get("command"):
        ctx = resume.get("context") or {}
        ctx_str = json.dumps(ctx)[:300] if ctx else ""
        lines.append(f"Last request: {resume['command']}")
        if ctx_str:
            lines.append(f"Last context: {ctx_str}")
        lines.append("")
    hot = get_hot(limit)
    if hot:
        lines.append("Recent memory (most recent last):")
        for m in hot:
            role = m.get("role", "?")
            ts = (m.get("timestamp") or "")[:19]
            content = (m.get("content") or "").strip().replace("\n", " ")
            if len(content) > 5000:
                content = content[:5000] + "…"
            lines.append(f"  [{ts}] {role}: {content}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_recent = sub.add_parser("recent", help="print recent hot memory + resume for injection")
    p_recent.add_argument("--limit", type=int, default=12)
    p_write = sub.add_parser("write", help="save a message through the memory pipeline")
    p_write.add_argument("--role", default="user")
    p_write.add_argument("--content", required=True)
    p_search = sub.add_parser("search", help="search hot memory (read-only)")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if args.cmd == "recent":
        out = _fmt_recent(args.limit)
        if out.strip():
            print(out)
    elif args.cmd == "write":
        ok = add_message(args.content, role=args.role)
        sys.exit(0 if ok else 1)
    elif args.cmd == "search":
        for r in search(args.query, limit=args.limit):
            content = (r.get("content") or "").strip().replace("\n", " ")[:5000]
            ts = (r.get("timestamp") or "")[:19]
            print(f"[{ts}] {r.get('role', '?')}: {content}")


if __name__ == "__main__":
    main()
