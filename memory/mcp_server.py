#!/usr/bin/env python3
"""memory/mcp_server.py — stdio MCP server for CortexAgent memory.

Tools:
  memory_read   — read hot/warm/cold memory
  memory_write  — write a message or fact
  memory_search — search warm memory
  memory_stats  — show memory counts
  memory_clear  — clear a tier (warm/hot) for the platform
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from memory.manager import manager
from memory.db import db

PLATFORM = os.environ.get("CORTEXAGENT_PLATFORM", "cortexagent")
PROFILE = f"platform:{PLATFORM}"


def _send_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_json() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _ok(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _tool(name: str, description: str, params: Dict[str, Any],
          required: List[str]) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": params, "required": required}}


TOOLS = [
    _tool("memory_read", "Read memory tier.", {
        "tier": {"type": "string", "enum": ["hot", "warm", "cold"], "description": "Memory tier."},
        "limit": {"type": "number", "description": "Max rows (default 20)."},
        "category": {"type": "string", "description": "Cold category filter."},
    }, ["tier"]),
    _tool("memory_write", "Write to memory.", {
        "content": {"type": "string", "description": "Text or fact to save."},
        "tier": {"type": "string", "enum": ["hot", "warm", "cold"], "description": "Target tier (default warm)."},
        "role": {"type": "string", "description": "Role for hot/warm (default user)."},
        "category": {"type": "string", "description": "Category for cold facts."},
    }, ["content"]),
    _tool("memory_search", "Search warm memory.", {
        "query": {"type": "string"},
        "limit": {"type": "number", "description": "Max rows (default 10)."},
    }, ["query"]),
    _tool("memory_stats", "Show memory counts.", {}, []),
    _tool("memory_clear", "Clear hot or warm memory for this platform.", {
        "tier": {"type": "string", "enum": ["hot", "warm"]},
    }, ["tier"]),
]


def _handle_read(args: Dict[str, Any]) -> Dict[str, Any]:
    tier = args.get("tier")
    limit = int(args.get("limit", 20))
    if tier == "hot":
        rows = manager.get_hot_messages(PLATFORM, limit=limit)
    elif tier == "warm":
        rows = manager.get_warm_messages(PLATFORM, limit=limit)
    elif tier == "cold":
        cat = args.get("category")
        rows = db.get_cold(PROFILE, category=cat, limit=limit)
    else:
        return _err("Unknown tier")
    return _ok(json.dumps(rows, ensure_ascii=False, default=str, indent=2))


def _handle_write(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args.get("content", "")
    tier = args.get("tier", "warm")
    if tier == "hot":
        manager.add_to_hot(PLATFORM, content, role=args.get("role", "user"))
    elif tier == "warm":
        db.add_to_warm(
            profile=PROFILE, role=args.get("role", "user"),
            content=content, platform=PLATFORM,
        )
    elif tier == "cold":
        manager.save_to_cold(args.get("category", "general"), content, platform=PROFILE)
    else:
        return _err("Unknown tier")
    return _ok("saved")


def _handle_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query", "").lower()
    limit = int(args.get("limit", 10))
    rows = db.reader().execute(
        "SELECT role, content, timestamp FROM Memory_Warm "
        "WHERE profile = ? AND LOWER(content) LIKE ? ORDER BY id DESC LIMIT ?",
        (PROFILE, f"%{query}%", limit)
    ).fetchall()
    out = [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]
    return _ok(json.dumps(out, ensure_ascii=False, default=str, indent=2))


def _handle_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    stats = manager.get_platform_stats(PLATFORM)
    return _ok(json.dumps(stats, ensure_ascii=False, default=str, indent=2))


def _handle_clear(args: Dict[str, Any]) -> Dict[str, Any]:
    tier = args.get("tier")
    if tier == "hot":
        db.writer.execute("DELETE FROM Memory_Hot WHERE profile = ?", (PROFILE,))
        db.writer.commit()
    elif tier == "warm":
        db.delete_warm(PROFILE)
    else:
        return _err("Unknown tier")
    return _ok(f"cleared {tier}")


def _dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "memory_read":
        return _handle_read(args)
    if name == "memory_write":
        return _handle_write(args)
    if name == "memory_search":
        return _handle_search(args)
    if name == "memory_stats":
        return _handle_stats(args)
    if name == "memory_clear":
        return _handle_clear(args)
    return _err(f"Unknown tool: {name}")


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": _id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "cortexagent-memory", "version": "1.0"}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": _id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        return {"jsonrpc": "2.0", "id": _id, "result": _dispatch(name, args)}

    return {"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def _smoke() -> int:
    # Write then read
    db.initialize()
    manager.add_to_hot(PLATFORM, "smoke test prompt", role="user")
    rows = manager.get_hot_messages(PLATFORM, limit=5)
    print(f"wrote + read hot: {len(rows)} rows")
    print(f"tools: {[t['name'] for t in TOOLS]}")
    print("cortexagent-memory: OK")
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())

    while True:
        req = _read_json()
        if req is None:
            break
        resp = _handle_request(req)
        if resp is not None:
            _send_json(resp)


if __name__ == "__main__":
    main()
