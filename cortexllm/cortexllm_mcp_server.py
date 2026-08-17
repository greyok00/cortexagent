#!/usr/bin/env python3
"""
CortexLLM MCP Server — Single-session memory for CortexAgent.

No warm tier. No caps. Two tiers only:
  - Hot: active conversation (NDJSON, append-only, no limit)
  - Cold: persistent knowledge facts (NDJSON, append-only, no limit)

Tools: memory_read, memory_write, memory_search, memory_clear
Resources: /memory/hot, /memory/cold
"""

import json
import sys
import asyncio
from pathlib import Path
from typing import Any, List
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, Tool, TextContent

# ─── Paths (single-session, matching daemon) ───────────────────────────────
CORTEXLLM_DIR = Path.home() / ".config/cortexllm"
HOT_FILE = CORTEXLLM_DIR / "memory" / "hot" / "cortexagent.jsonl"
COLD_DIR = CORTEXLLM_DIR / "memory" / "cold"

# ─── SQLite backend (optional, for advanced features) ──────────────────────
try:
    from cortexllm_db import db as sqlite_db
    HAS_SQLITE = True
except ImportError:
    sqlite_db = None
    HAS_SQLITE = False

app = Server("cortexllm")


# ─── Memory Backend ────────────────────────────────────────────────────────
class MemoryBackend:
    """Single-session memory backend. No caps, no warm tier."""

    def __init__(self):
        HOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        COLD_DIR.mkdir(parents=True, exist_ok=True)

    def _read_ndjson(self, path: Path) -> List[dict]:
        """Read all entries from NDJSON file."""
        if not path.exists():
            return []
        try:
            return [json.loads(l) for l in path.read_text().strip().split("\n") if l.strip()]
        except Exception:
            return []

    def _append_ndjson(self, path: Path, entry: dict) -> None:
        """Append entry to NDJSON file (atomic, no lock needed for <4KB)."""
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(path, "a") as f:
            f.write(line)

    # ── Hot memory ───────────────────────────────────────────────────────
    def get_hot(self) -> List[dict]:
        """Get all hot memory entries."""
        return self._read_ndjson(HOT_FILE)

    def append_hot(self, role: str, content: str, **meta) -> dict:
        """Append to hot memory. No cap."""
        entry = {"role": role, "content": content, "timestamp": _now_ts(), **meta}
        self._append_ndjson(HOT_FILE, entry)
        return entry

    def set_hot(self, entries: List[dict]) -> None:
        """Replace all hot memory (truncate)."""
        if HOT_FILE.exists():
            HOT_FILE.write_text("")
        for entry in entries:
            self._append_ndjson(HOT_FILE, entry)

    def clear_hot(self) -> None:
        """Clear hot memory."""
        if HOT_FILE.exists():
            HOT_FILE.write_text("")

    # ── Cold memory (per-category .json, matching cortexllm engine) ──────
    def _read_category(self, category: str) -> dict:
        """Read one cold category file (engine format)."""
        path = COLD_DIR / f"{category}.json"
        if not path.exists():
            return {"category": category, "entries": []}
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or "entries" not in data:
                return {"category": category, "entries": []}
            return data
        except Exception:
            return {"category": category, "entries": []}

    def get_cold(self, category: str = "") -> List[dict]:
        """Get all cold memory entries. If category given, only that one.

        Reads the real per-category .json files (the cortexllm engine format),
        so CortexAgent sees the same 29 categories as the rest of the system.
        """
        if category:
            data = self._read_category(category)
            return [{"category": category, **e} for e in data.get("entries", [])]
        if not COLD_DIR.exists():
            return []
        results = []
        for path in sorted(COLD_DIR.glob("*.json")):
            cat = path.stem
            try:
                data = json.loads(path.read_text())
                for e in data.get("entries", []):
                    results.append({"category": cat, **e})
            except Exception:
                continue
        return results

    def append_cold(self, content: str, category: str = "cortexagent", **meta) -> dict:
        """Append to a cold category file (engine format). No cap."""
        data = self._read_category(category)
        entry = {"timestamp": _now_ts(), "content": content, **meta}
        data.setdefault("entries", []).append(entry)
        path = COLD_DIR / f"{category}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return {"category": category, **entry}

    def clear_cold(self, category: str = "") -> None:
        """Clear cold memory. If category given, only that one."""
        if category:
            path = COLD_DIR / f"{category}.json"
            if path.exists():
                path.unlink()
            return
        if COLD_DIR.exists():
            for path in COLD_DIR.glob("*.json"):
                path.unlink()

    # ── Search ───────────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 10) -> List[dict]:
        """Search across hot + cold."""
        q = query.lower()
        results = []
        for entry in self._read_ndjson(HOT_FILE):
            content = entry.get("content", "")
            if q in content.lower():
                entry["source"] = "hot"
                results.append(entry)
                if len(results) >= limit:
                    return results
        for entry in self.get_cold():
            content = entry.get("content", "")
            if q in content.lower():
                entry["source"] = "cold"
                results.append(entry)
                if len(results) >= limit:
                    break
        return results


def _now_ts() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ─── MCP Handlers ──────────────────────────────────────────────────────────
backend = MemoryBackend()


@app.list_resources()
async def list_resources():
    """List available memory resources."""
    hot_count = len(backend.get_hot())
    cold_count = len(backend.get_cold())
    return [
        Resource(
            uri="memory://hot",
            name="Hot Memory",
            description=f"Active conversation buffer ({hot_count} entries, no cap)",
            mimeType="application/json",
        ),
        Resource(
            uri="memory://cold",
            name="Cold Memory",
            description=f"Persistent knowledge ({cold_count} entries, no cap)",
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> List[TextContent]:
    """Read a memory resource."""
    if uri == "memory://hot":
        data = backend.get_hot()
    elif uri == "memory://cold":
        data = backend.get_cold()
    else:
        return [TextContent(type="text", text=f"Unknown resource: {uri}")]
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


@app.list_tools()
async def list_tools():
    """List available tools."""
    return [
        Tool(
            name="memory_read",
            description="Read from hot or cold memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "enum": ["hot", "cold"]},
                    "category": {"type": "string", "description": "Cold category to read (default: all)"},
                    "last_n": {"type": "integer", "description": "Last N entries (default: all)"},
                },
                "required": ["tier"],
            },
        ),
        Tool(
            name="memory_write",
            description="Append to hot or cold memory (no cap)",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "enum": ["hot", "cold"]},
                    "role": {"type": "string", "enum": ["user", "assistant", "system", "cold"], "default": "user"},
                    "category": {"type": "string", "description": "Cold category to write to (default: cortexagent)"},
                    "content": {"type": "string"},
                    "metadata": {"type": "object", "optional": True},
                },
                "required": ["tier", "content"],
            },
        ),
        Tool(
            name="memory_search",
            description="Search across hot + cold memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memory_clear",
            description="Clear hot or cold memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "enum": ["hot", "cold"]},
                },
                "required": ["tier"],
            },
        ),
        Tool(
            name="session_status",
            description="Check what other sessions are doing (inter-session awareness)",
            inputSchema={
                "type": "object",
                "properties": {
                    "broadcast": {"type": "string", "optional": True, "description": "Set my status"},
                    "task": {"type": "string", "optional": True, "description": "What I'm doing"},
                },
                "required": [],
            },
        ),
        Tool(
            name="session_log",
            description="Log inter-session awareness message to hot memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "level": {"type": "string", "enum": ["info", "warn", "critical"], "default": "info"},
                },
                "required": ["message"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, args: Any) -> List[TextContent]:
    """Execute a tool."""
    try:
        if name == "memory_read":
            tier = args.get("tier", "hot")
            last_n = args.get("last_n", None)
            category = args.get("category", "")
            data = backend.get_hot() if tier == "hot" else backend.get_cold(category)
            if last_n:
                data = data[-last_n:]
            return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]

        elif name == "memory_write":
            tier = args.get("tier", "hot")
            role = args.get("role", "user")
            content = args.get("content", "")
            category = args.get("category", "cortexagent")
            metadata = args.get("metadata", {})
            if tier == "hot":
                entry = backend.append_hot(role, content, **metadata)
            else:
                entry = backend.append_cold(content, category=category, **metadata)
            return [TextContent(type="text", text=json.dumps({"status": "ok", "entry": entry}) )]

        elif name == "memory_search":
            query = args.get("query", "")
            limit = args.get("limit", 10)
            results = backend.search(query, limit)
            return [TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]

        elif name == "memory_clear":
            tier = args.get("tier", "hot")
            category = args.get("category", "")
            if tier == "hot":
                backend.clear_hot()
            else:
                backend.clear_cold(category)
            return [TextContent(type="text", text=json.dumps({"status": "ok", "cleared": tier}) )]

        elif name == "session_status":
            """Check/set session status."""
            try:
                from lib.session_coordinator import get_coordinator
                coord = get_coordinator("cortexagent")
                broadcast = args.get("broadcast")
                task = args.get("task")
                if broadcast:
                    coord.broadcast(status=broadcast, task=task)
                    return [TextContent(type="text", text=json.dumps({"status": "broadcast", "broadcast": broadcast, "task": task}))]
                sessions = coord.poll()
                return [TextContent(type="text", text=json.dumps({"sessions": sessions, "summary": coord.summarize_activity()}, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

        elif name == "session_log":
            """Log inter-session awareness."""
            try:
                from lib.session_coordinator import get_coordinator
                coord = get_coordinator("cortexagent")
                message = args.get("message", "")
                level = args.get("level", "info")
                result = coord.log_awareness(message, level)
                return [TextContent(type="text", text=json.dumps(result))]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read, write):
        await app.run({"stdio": read}, {"stdio": write})


if __name__ == "__main__":
    asyncio.run(main())
