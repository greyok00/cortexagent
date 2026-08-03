#!/usr/bin/env python3
"""
CortexLLM MCP Server
Universal per-profile memory system for any MCP-compatible AI agent.

Provides:
- Memory resources (hot/warm/cold tiers)
- Tools (read, write, search memory)
- Cross-platform sync (CortexAgent and other MCP-compatible agents)
"""

import json
import sys
import asyncio
from pathlib import Path
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, Tool, TextContent

# CortexLLM paths
CORTEXLLM_DIR = Path.home() / ".config/cortexllm"
HOT_DIR = CORTEXLLM_DIR / "memory/hot"
WARM_DIR = CORTEXLLM_DIR / "memory/warm"
COLD_DIR = CORTEXLLM_DIR / "memory/cold"

# Import SQLite backend for persistent memory
try:
    from cortexllm_db import db as sqlite_db
    HAS_SQLITE = True
except ImportError:
    sqlite_db = None
    HAS_SQLITE = False

# Initialize MCP server
app = Server("cortexllm")


class CortexLLMMemory:
    """Per-profile memory system with hot/warm/cold tiers.

    Primary storage: SQLite (via cortexllm_db) for persistence.
    Fallback: JSON files for backward compatibility.
    """

    def __init__(self):
        HOT_DIR.mkdir(parents=True, exist_ok=True)
        WARM_DIR.mkdir(parents=True, exist_ok=True)
        COLD_DIR.mkdir(parents=True, exist_ok=True)

    def get_hot(self, platform: str = "default") -> list:
        """Get hot memory messages for a platform.
        Reads from SQLite first, falls back to JSON file.
        Always includes most recent data from any platform as context."""
        messages = []

        # Try SQLite first (primary storage)
        if HAS_SQLITE:
            try:
                # Get data for the requested platform
                profile = f"platform:{platform}"
                rows = sqlite_db.reader().execute(
                    "SELECT role, content, metadata, timestamp FROM Memory_Hot "
                    "WHERE profile = ? ORDER BY id DESC LIMIT 100",
                    (profile,)
                ).fetchall()
                for row in reversed(rows):
                    msg = {
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                    }
                    if row["metadata"]:
                        try:
                            msg["metadata"] = json.loads(row["metadata"])
                        except:
                            pass
                    messages.append(msg)

                # Also include most recent data from other platforms for context
                other_rows = sqlite_db.reader().execute(
                    "SELECT profile, role, content, metadata, timestamp FROM Memory_Hot "
                    "WHERE profile != ? ORDER BY id DESC LIMIT 50",
                    (profile,)
                ).fetchall()
                for row in reversed(other_rows):
                    msg = {
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "_source_platform": row["profile"].replace("platform:", "")
                    }
                    if row["metadata"]:
                        try:
                            msg["metadata"] = json.loads(row["metadata"])
                        except:
                            pass
                    messages.append(msg)
            except Exception as e:
                print(f"Warning: SQLite hot read failed for {platform}: {e}", file=sys.stderr)

        # Fallback: NDJSON (.jsonl) or legacy JSON (.json)
        hot_file_ndjson = HOT_DIR / f"{platform}.jsonl"
        hot_file_json = HOT_DIR / f"{platform}.json"
        if hot_file_ndjson.exists():
            try:
                lines = hot_file_ndjson.read_text().strip().split('\n')
                return [json.loads(line) for line in lines if line.strip()]
            except Exception as e:
                print(f"Warning: failed to read NDJSON hot memory for {platform}: {e}", file=sys.stderr)
                return []
        if hot_file_json.exists():
            try:
                data = json.loads(hot_file_json.read_text())
                if isinstance(data, dict):
                    return data.get("messages", [])
                return data
            except Exception as e:
                print(f"Warning: failed to read hot memory for {platform}: {e}", file=sys.stderr)
                return []
        return []

    def get_hot_data(self, platform: str = "default") -> dict:
        """Get full hot memory dict with platform + messages keys."""
        return {
            "platform": platform,
            "messages": self.get_hot(platform)
        }

    def set_hot(self, platform: str, messages: list):
        """Set hot memory for a platform. Writes to both SQLite and JSON."""
        # Write to SQLite (primary)
        if HAS_SQLITE:
            try:
                profile = f"platform:{platform}"
                conn = sqlite_db.writer  # property, not method
                # Clear existing hot memory for this profile
                conn.execute("DELETE FROM Memory_Hot WHERE profile = ?", (profile,))
                # Insert all messages
                for msg in messages[-300:]:
                    conn.execute(
                        "INSERT INTO Memory_Hot (profile, role, content, metadata, platform) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (profile, msg.get("role", "user"), msg.get("content", ""),
                         json.dumps(msg.get("metadata", {})), platform)
                    )
                conn.commit()
            except Exception as e:
                print(f"Warning: SQLite hot write failed for {platform}: {e}", file=sys.stderr)

        # Also write to NDJSON file (append-only fallback)
        hot_file = HOT_DIR / f"{platform}.jsonl"
        with open(hot_file, 'a') as f:
            for msg in messages[-300:]:
                f.write(json.dumps(msg) + '\n')

    def append_hot(self, platform: str, content: str, role: str = "user", metadata: dict = None):
        """Append message to hot memory. Writes to both SQLite and JSON."""
        message = {
            "role": role,
            "content": content,
            "metadata": metadata or {}
        }

        # Write to SQLite (primary)
        if HAS_SQLITE:
            try:
                profile = f"platform:{platform}"
                conn = sqlite_db.writer  # property, not method
                conn.execute(
                    "INSERT INTO Memory_Hot (profile, role, content, metadata, platform) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (profile, role, content, json.dumps(metadata or {}), platform)
                )
                conn.commit()
            except Exception as e:
                print(f"Warning: SQLite hot append failed for {platform}: {e}", file=sys.stderr)

        # Also append to NDJSON file (append-only fallback — no lock needed)
        hot_file = HOT_DIR / f"{platform}.jsonl"
        with open(hot_file, 'a') as f:
            f.write(json.dumps(message) + '\n')

        return message

    def _get_hot_json(self, platform: str) -> list:
        """Get hot memory from JSON/NDJSON file only (internal use)."""
        hot_file_ndjson = HOT_DIR / f"{platform}.jsonl"
        hot_file_json = HOT_DIR / f"{platform}.json"
        if hot_file_ndjson.exists():
            try:
                lines = hot_file_ndjson.read_text().strip().split('\n')
                return [json.loads(line) for line in lines if line.strip()]
            except:
                pass
        if hot_file_json.exists():
            try:
                data = json.loads(hot_file_json.read_text())
                if isinstance(data, dict):
                    return data.get("messages", [])
                return data
            except:
                return []

    def get_warm(self) -> list:
        """Get warm (per-profile) memory messages.
        Reads from SQLite first, falls back to JSON file."""
        # Try SQLite first (primary storage)
        if HAS_SQLITE:
            try:
                rows = sqlite_db.reader().execute(
                    "SELECT role, content, metadata, timestamp FROM Memory_Warm "
                    "ORDER BY id DESC LIMIT 500"
                ).fetchall()
                if rows:
                    messages = []
                    for row in reversed(rows):
                        msg = {
                            "role": row["role"],
                            "content": row["content"],
                            "timestamp": row["timestamp"],
                        }
                        if row["metadata"]:
                            try:
                                msg["metadata"] = json.loads(row["metadata"])
                            except:
                                pass
                        messages.append(msg)
                    return messages
            except Exception as e:
                print(f"Warning: SQLite warm read failed: {e}", file=sys.stderr)

        # Fallback: JSON file
        warm_file = WARM_DIR / "per_profile.json"
        if not warm_file.exists():
            return []
        try:
            data = json.loads(warm_file.read_text())
            if isinstance(data, dict):
                return data.get("messages", [])
            return data
        except:
            return []

    def get_warm_data(self) -> dict:
        """Get full warm memory dict."""
        return {
            "messages": self.get_warm()
        }

    def set_warm(self, messages: list):
        """Set warm memory. Writes to both SQLite and JSON."""
        # Write to SQLite (primary)
        if HAS_SQLITE:
            try:
                conn = sqlite_db.writer  # property, not method
                conn.execute("DELETE FROM Memory_Warm")
                for msg in messages[-2000:]:
                    conn.execute(
                        "INSERT INTO Memory_Warm (profile, role, content, metadata) "
                        "VALUES (?, ?, ?, ?)",
                        ("warm:global", msg.get("role", "user"), msg.get("content", ""),
                         json.dumps(msg.get("metadata", {})))
                    )
                conn.commit()
            except Exception as e:
                print(f"Warning: SQLite warm write failed: {e}", file=sys.stderr)

        # Also write to JSON file (fallback)
        warm_file = WARM_DIR / "per_profile.json"
        warm_file.write_text(json.dumps({
            "messages": messages
        }, indent=2))

    def set_warm_data(self, data: dict):
        """Set warm memory from full dict."""
        messages = data.get("messages", [])
        self.set_warm(messages)
    
    def get_cold(self, category: str = None) -> dict:
        """Get cold storage (permanent knowledge)"""
        if category:
            cold_file = COLD_DIR / f"{category}.json"
            if cold_file.exists():
                try:
                    return json.loads(cold_file.read_text())
                except:
                    return {}
            return {}
        
        # List all categories
        categories = {}
        for f in COLD_DIR.glob("*.json"):
            try:
                categories[f.stem] = json.loads(f.read_text())
            except:
                pass
        return categories
    
    def set_cold(self, category: str, data: dict):
        """Save to cold storage"""
        cold_file = COLD_DIR / f"{category}.json"
        cold_file.write_text(json.dumps(data, indent=2))
    
    def search(self, query: str, limit: int = 10) -> list:
        """Search across all memory tiers"""
        results = []
        query_lower = query.lower()

        # Search SQLite hot memory (primary)
        if HAS_SQLITE:
            try:
                rows = sqlite_db.reader().execute(
                    "SELECT profile, role, content, timestamp FROM Memory_Hot "
                    "WHERE LOWER(content) LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{query_lower}%", limit)
                ).fetchall()
                for row in rows:
                    results.append({
                        "source": f"hot/{row['profile'].replace('platform:', '')}",
                        "content": row["content"][:5000],
                        "relevance": 0.8,
                        "timestamp": row["timestamp"]
                    })
            except Exception as e:
                print(f"Warning: SQLite hot search failed: {e}", file=sys.stderr)

        # Search SQLite warm memory
        if HAS_SQLITE:
            try:
                rows = sqlite_db.reader().execute(
                    "SELECT role, content, timestamp FROM Memory_Warm "
                    "WHERE LOWER(content) LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{query_lower}%", limit)
                ).fetchall()
                for row in rows:
                    results.append({
                        "source": "warm/per_profile",
                        "content": row["content"][:5000],
                        "relevance": 0.9,
                        "timestamp": row["timestamp"]
                    })
            except Exception as e:
                print(f"Warning: SQLite warm search failed: {e}", file=sys.stderr)

        # Fallback: search JSON files
        for hot_file in HOT_DIR.glob("*.json"):
            try:
                data = json.loads(hot_file.read_text())
                msgs = data.get("messages", []) if isinstance(data, dict) else data
                for msg in msgs[-limit:]:
                    content = msg.get("content", "")
                    if query_lower in content.lower():
                        results.append({
                            "source": f"hot/{hot_file.stem}",
                            "content": content[:5000],
                            "relevance": 0.8
                        })
            except:
                pass

        # Search cold storage (JSON files only)
        for cold_file in COLD_DIR.glob("*.json"):
            try:
                data = json.loads(cold_file.read_text())
                entries = data.get("entries", [])
                for entry in entries:
                    knowledge = json.dumps(entry.get("knowledge", {}))
                    if query_lower in knowledge.lower():
                        results.append({
                            "source": f"cold/{cold_file.stem}",
                            "content": knowledge[:5000],
                            "relevance": 1.0
                        })
            except:
                pass

        # Deduplicate by content
        seen = set()
        unique = []
        for r in results:
            key = r["content"][:100]
            if key not in seen:
                seen.add(key)
                unique.append(r)

        # Sort by relevance
        unique.sort(key=lambda x: x["relevance"], reverse=True)
        return unique[:limit]


# Global memory instance
memory = CortexLLMMemory()


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available memory resources"""
    return [
        Resource(
            uri="cortexllm://memory/hot",
            name="Hot Memory",
            description="Active session memory (per-platform)",
            mimeType="application/json"
        ),
        Resource(
            uri="cortexllm://memory/warm",
            name="Warm Memory",
            description="Unified cross-platform memory",
            mimeType="application/json"
        ),
        Resource(
            uri="cortexllm://memory/cold",
            name="Cold Memory",
            description="Permanent knowledge storage",
            mimeType="application/json"
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read memory resource"""
    if uri == "cortexllm://memory/hot":
        # Return all hot memories (from SQLite primary, JSON fallback)
        all_hot = {}

        # Try SQLite first
        if HAS_SQLITE:
            try:
                rows = sqlite_db.reader().execute(
                    "SELECT platform, role, content, timestamp FROM Memory_Hot "
                    "ORDER BY id DESC LIMIT 1000"
                ).fetchall()
                for row in rows:
                    plat = row["platform"] or "default"
                    if plat not in all_hot:
                        all_hot[plat] = []
                    all_hot[plat].append({
                        "role": row["role"],
                        "content": row["content"][:5000],
                        "timestamp": row["timestamp"]
                    })
                # Reverse each platform's messages to be chronological
                for plat in all_hot:
                    all_hot[plat].reverse()
            except Exception as e:
                print(f"Warning: SQLite hot read failed: {e}", file=sys.stderr)

        # Fallback: JSON files
        if not all_hot:
            for hot_file in HOT_DIR.glob("*.json"):
                try:
                    data = json.loads(hot_file.read_text())
                    if isinstance(data, dict):
                        all_hot[hot_file.stem] = data.get("messages", [])
                    else:
                        all_hot[hot_file.stem] = data
                except:
                    pass
        return json.dumps(all_hot, indent=2)
    
    elif uri == "cortexllm://memory/warm":
        return json.dumps(memory.get_warm_data(), indent=2)
    
    elif uri == "cortexllm://memory/cold":
        return json.dumps(memory.get_cold(), indent=2)
    
    else:
        raise ValueError(f"Unknown resource: {uri}")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available memory tools"""
    return [
        Tool(
            name="memory_read",
            description="Read from CortexLLM per-profile memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["hot", "warm", "cold"],
                        "description": "Memory tier to read from"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform name (for hot memory)"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name (for cold memory)"
                    }
                },
                "required": ["tier"]
            }
        ),
        Tool(
            name="memory_write",
            description="Write to CortexLLM per-profile memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["hot", "warm", "cold"],
                        "description": "Memory tier to write to"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform name (for hot memory)"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name (for cold memory)"
                    },
                    "role": {
                        "type": "string",
                        "enum": ["user", "assistant", "system"],
                        "description": "Message role"
                    }
                },
                "required": ["tier", "content"]
            }
        ),
        Tool(
            name="memory_search",
            description="Search across all CortexLLM memory tiers",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_clear",
            description="Clear CortexLLM memory (use with caution)",
            inputSchema={
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["hot", "warm", "all"],
                        "description": "Which memory to clear"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform to clear (for hot memory)"
                    }
                },
                "required": ["tier"]
            }
        ),
        Tool(
            name="memory_search_semantic",
            description="Semantic (vector) search across CortexLLM memory using embeddings",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default: 10)"},
                    "platform": {"type": "string", "description": "Filter by platform"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_graph_query",
            description="Query the CortexLLM knowledge graph: extract entities/relationships or traverse around an entity",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["query", "extract", "path", "stats"],
                        "description": "Graph action: query (traverse), extract (from text), path (between two entities), stats"
                    },
                    "entity": {"type": "string", "description": "Entity name (for 'query' action)"},
                    "text": {"type": "string", "description": "Text to extract from (for 'extract' action)"},
                    "target": {"type": "string", "description": "Target entity (for 'path' action)"},
                    "depth": {"type": "integer", "description": "Traversal depth (default: 2)"},
                    "platform": {"type": "string", "description": "Filter by platform"}
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="memory_ontology",
            description="Ontology operations: categorize text, build taxonomy, find knowledge gaps, tag content",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["categorize", "taxonomy", "gaps", "tag", "tagmem", "discover", "stats"],
                        "description": "Ontology action to perform"
                    },
                    "text": {"type": "string", "description": "Text to categorize (for 'categorize' action)"}
                },
                "required": ["action"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute memory tool"""
    
    if name == "memory_read":
        tier = arguments.get("tier", "warm")
        
        if tier == "hot":
            platform = arguments.get("platform", "default")
            data = memory.get_hot(platform)
        
        elif tier == "warm":
            data = memory.get_warm()
        
        elif tier == "cold":
            category = arguments.get("category")
            data = memory.get_cold(category)
        
        else:
            data = {"error": "Invalid tier"}
        
        return [TextContent(type="text", text=json.dumps(data, indent=2))]
    
    elif name == "memory_write":
        tier = arguments.get("tier", "warm")
        content = arguments.get("content", "")
        role = arguments.get("role", "user")
        
        if tier == "hot":
            platform = arguments.get("platform", "default")
            result = memory.append_hot(platform, content, role)
        
        elif tier == "warm":
            messages = memory.get_warm()
            messages.append({"role": role, "content": content})
            messages = messages[-2000:]
            memory.set_warm(messages)
            result = {"status": "written", "tier": "warm"}
        
        elif tier == "cold":
            category = arguments.get("category", "general")
            try:
                knowledge = json.loads(content)
            except:
                knowledge = {"content": content}
            
            data = memory.get_cold(category)
            if not data:
                data = {"category": category, "entries": []}
            
            data["entries"].append({
                "timestamp": str(asyncio.get_event_loop().time()),
                "knowledge": knowledge
            })
            memory.set_cold(category, data)
            result = {"status": "written", "tier": "cold", "category": category}
        
        else:
            result = {"error": "Invalid tier"}
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "memory_search":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        results = memory.search(query, limit)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "memory_clear":
        tier = arguments.get("tier", "all")

        # Clear SQLite (primary storage)
        if HAS_SQLITE:
            try:
                conn = sqlite_db.writer  # property, not method
                if tier == "hot":
                    platform = arguments.get("platform")
                    if platform:
                        conn.execute("DELETE FROM Memory_Hot WHERE platform = ?", (platform,))
                    else:
                        conn.execute("DELETE FROM Memory_Hot")
                elif tier == "warm":
                    conn.execute("DELETE FROM Memory_Warm")
                elif tier == "all":
                    conn.execute("DELETE FROM Memory_Hot")
                    conn.execute("DELETE FROM Memory_Warm")
                conn.commit()
            except Exception as e:
                print(f"Warning: SQLite clear failed: {e}", file=sys.stderr)

        # Also clear JSON files (fallback)
        if tier == "hot":
            platform = arguments.get("platform")
            if platform:
                hot_file = HOT_DIR / f"{platform}.json"
                if hot_file.exists():
                    hot_file.unlink()
                result = {"status": "cleared", "platform": platform}
            else:
                for f in HOT_DIR.glob("*.json"):
                    f.unlink()
                result = {"status": "cleared", "tier": "hot"}

        elif tier == "warm":
            warm_file = WARM_DIR / "per_profile.json"
            if warm_file.exists():
                warm_file.unlink()
            result = {"status": "cleared", "tier": "warm"}

        elif tier == "all":
            for f in HOT_DIR.glob("*.json"):
                f.unlink()
            warm_file = WARM_DIR / "per_profile.json"
            if warm_file.exists():
                warm_file.unlink()
            result = {"status": "cleared", "tier": "all"}

        else:
            result = {"error": "Invalid tier"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "memory_search_semantic":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        platform = arguments.get("platform")
        try:
            from cortexllm_vector import VectorStore
            vs = VectorStore()
            results = vs.search(query, limit, platform)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]

    elif name == "memory_graph_query":
        action = arguments.get("action", "query")
        try:
            from cortexllm_graph import GraphStore
            gs = GraphStore()
            if action == "query":
                entity = arguments.get("entity", "")
                depth = arguments.get("depth", 2)
                platform = arguments.get("platform")
                result = gs.query_entity(entity, depth, platform)
            elif action == "extract":
                text = arguments.get("text", "")
                platform = arguments.get("platform", "default")
                result = gs.extract_and_store(text, platform)
            elif action == "path":
                src = arguments.get("entity", "")
                tgt = arguments.get("target", "")
                result = gs.find_path(src, tgt)
            elif action == "stats":
                result = gs.get_stats()
            else:
                result = {"error": f"Unknown action: {action}"}
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]

    elif name == "memory_ontology":
        action = arguments.get("action", "stats")
        try:
            from cortexllm_ontology import OntologyEngine
            oe = OntologyEngine()
            if action == "categorize":
                text = arguments.get("text", "")
                result = oe.categorize(text)
            elif action == "taxonomy":
                result = oe.build_taxonomy()
            elif action == "gaps":
                result = oe.find_gaps()
            elif action == "tag":
                result = oe.auto_tag_practices()
            elif action == "tagmem":
                result = oe.tag_memory()
            elif action == "discover":
                result = oe.discover_categories()
            elif action == "stats":
                result = oe.get_stats()
            else:
                result = {"error": f"Unknown action: {action}"}
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
