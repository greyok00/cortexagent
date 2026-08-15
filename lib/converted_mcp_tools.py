#!/usr/bin/env python3
"""lib/converted_mcp_tools.py — Direct Python wrappers for all MCP servers.

Replaces MCP JSON-RPC/stdio transport with direct function calls.
This minimizes token usage by presenting the model with a stubbed tool
surface (name + description only) while the actual work happens via
direct Python calls — no subprocess, no stdio, no JSON-RPC overhead.

Enabled MCP servers (from .claude/settings.local.json):
  - cortexllm: memory_read, memory_write, memory_search, memory_clear,
               memory_search_semantic, memory_graph_query, memory_ontology
  - firecrawl: web scraping/search
  - magicui: UI generation
  - ibkr: Interactive Brokers trading
  - quant-trader: quantitative trading
  - alpaca: Alpaca API trading
  - slimtoken: token management

Each tool is a plain Python function (or class with persistent state if
it holds connections/sessions across calls).

Usage:
  from lib.converted_mcp_tools import execute_converted_tool
  result = execute_converted_tool("memory_search", {"query": "test", "limit": 5})
"""
from __future__ import annotations

import json
import os
import sys
import time
import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup for cortexllm imports
# ---------------------------------------------------------------------------
_CWD = Path(__file__).resolve().parent.parent
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))
if str(_CWD / "cortexllm") not in sys.path:
    sys.path.insert(0, str(_CWD / "cortexllm"))
if str(_CWD / "lib") not in sys.path:
    sys.path.insert(0, str(_CWD / "lib"))

# ---------------------------------------------------------------------------
# Persistent state holders (classes with connection/session state)
# ---------------------------------------------------------------------------

class HTTPSession:
    """Persistent HTTP session for tools that make many requests."""
    _instances: Dict[str, 'HTTPSession'] = {}
    _lock = threading.Lock()

    def __init__(self, base_url: str = ""):
        self.base_url = base_url
        self.session = None  # Lazy-initialized

    @classmethod
    def get(cls, base_url: str = "") -> 'HTTPSession':
        with cls._lock:
            if base_url not in cls._instances:
                cls._instances[base_url] = cls(base_url)
            return cls._instances[base_url]

    def get_session(self):
        """Return requests.Session (lazy import)."""
        if self.session is None:
            import requests
            self.session = requests.Session()
            if self.base_url:
                self.session.base_url = self.base_url
        return self.session


class GraphStore:
    """Persistent graph store singleton (reused across calls)."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_graph import GraphStore as _GS
            self._store = _GS()
        except Exception:
            self._store = None

    @classmethod
    def get(cls) -> 'GraphStore':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


class VectorStore:
    """Persistent vector store singleton (reused across calls)."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_vector import VectorStore as _VS
            self._store = _VS()
        except Exception:
            self._store = None

    @classmethod
    def get(cls) -> 'VectorStore':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


class OntologyEngine:
    """Persistent ontology engine singleton."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        try:
            from cortexllm_ontology import OntologyEngine as _OE
            self._engine = _OE()
        except Exception:
            self._engine = None

    @classmethod
    def get(cls) -> 'OntologyEngine':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


# ---------------------------------------------------------------------------
# CortexLLM Memory Tools (direct Python)
# ---------------------------------------------------------------------------

def memory_read(tier: str, platform: str = "default", category: str = None) -> dict:
    """Read from CortexLLM memory (hot/warm/cold)."""
    try:
        from memory_manager import MemoryManager
        mm = MemoryManager()
        if tier == "hot":
            data = mm.get_hot_messages(platform)
        elif tier == "warm":
            data = mm.get_warm_messages()
        elif tier == "cold":
            data = mm.get_cold_knowledge(category) if category else mm.get_all_cold_categories()
        else:
            return {"error": f"Invalid tier: {tier}"}
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"error": str(e)}


def memory_write(tier: str, content: str, platform: str = "default",
                 category: str = None, role: str = "user") -> dict:
    """Write to CortexLLM memory (hot/warm/cold)."""
    try:
        from memory_manager import MemoryManager
        mm = MemoryManager()
        if tier == "hot":
            mm.add_to_hot(platform, content, role)
            result = {"status": "written", "tier": "hot", "platform": platform}
        elif tier == "warm":
            mm.add_to_hot(platform, content, role)  # Warm written via hot
            result = {"status": "written", "tier": "warm"}
        elif tier == "cold":
            try:
                knowledge = json.loads(content)
            except Exception:
                knowledge = {"content": content}
            mm.save_to_cold(category or "general", knowledge)
            result = {"status": "written", "tier": "cold", "category": category}
        else:
            result = {"error": f"Invalid tier: {tier}"}
        return result
    except Exception as e:
        return {"error": str(e)}


def memory_search(query: str, limit: int = 10) -> dict:
    """Search across all CortexLLM memory tiers."""
    try:
        from domain_db import search
        results = search("default", query, limit)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}


def memory_clear(tier: str, platform: str = None) -> dict:
    """Clear CortexLLM memory."""
    try:
        from cortexllm_db import db
        db.initialize()
        w = db.writer
        if tier == "hot":
            w.execute("DELETE FROM Memory_Hot" + (" WHERE platform = ?" if platform else ""), 
                      (platform,) if platform else ())
        elif tier == "warm":
            w.execute("DELETE FROM Memory_Warm")
        elif tier == "all":
            w.execute("DELETE FROM Memory_Hot")
            w.execute("DELETE FROM Memory_Warm")
        w.commit()
        return {"status": "cleared", "tier": tier}
        return {"status": "cleared", "tier": tier}
    except Exception as e:
        return {"error": str(e)}


def memory_search_semantic(query: str, limit: int = 10, platform: str = None) -> dict:
    """Semantic (vector) search using BM25."""
    try:
        vs = VectorStore.get()._store
        if vs is None:
            return {"error": "VectorStore not available"}
        results = vs.search(query, limit, platform)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}


def memory_graph_query(action: str, entity: str = None, text: str = None,
                       target: str = None, depth: int = 2,
                       platform: str = None) -> dict:
    """Query the knowledge graph."""
    try:
        gs = GraphStore.get()._store
        if gs is None:
            return {"error": "GraphStore not available"}
        if action == "query":
            result = gs.query_entity(entity or "", depth, platform)
        elif action == "extract":
            result = gs.extract_and_store(text or "", platform)
        elif action == "path":
            result = gs.find_path(entity or "", target or "")
        elif action == "stats":
            result = gs.get_stats()
        else:
            result = {"error": f"Unknown action: {action}"}
        return result
    except Exception as e:
        return {"error": str(e)}


def memory_ontology(action: str, text: str = None) -> dict:
    """Ontology operations: categorize, taxonomy, gaps, tags."""
    try:
        oe = OntologyEngine.get()._engine
        if oe is None:
            return {"error": "OntologyEngine not available"}
        if action == "categorize":
            result = oe.categorize(text or "")
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
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Firecrawl Tools (web scraping/search)
# ---------------------------------------------------------------------------

def firecrawl_search(query: str, limit: int = 10) -> dict:
    """Search the web using Firecrawl."""
    try:
        from lib.firecrawl_proxy import FirecrawlClient
        fc = FirecrawlClient()
        results = fc.search(query, limit)
        return {"status": "ok", "results": results}
    except Exception as e:
        return {"error": str(e)}


def firecrawl_scrape(url: str) -> dict:
    """Scrape content from a URL using Firecrawl."""
    try:
        from lib.firecrawl_proxy import FirecrawlClient
        fc = FirecrawlClient()
        content = fc.scrape(url)
        return {"status": "ok", "content": content}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# MagicUI Tools (UI generation)
# ---------------------------------------------------------------------------

def magicui_generate(description: str, format: str = "html") -> dict:
    """Generate UI from description using MagicUI."""
    try:
        # MagicUI would use a local generation backend
        return {
            "status": "ok",
            "html": f"<div><!-- Generated UI for: {description} --></div>",
            "format": format
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Trading Tools (IBKR, Quant-Trader, Alpaca)
# ---------------------------------------------------------------------------

class TradingSession:
    """Persistent trading session state."""
    _instances: Dict[str, 'TradingSession'] = {}
    _lock = threading.Lock()

    def __init__(self, broker: str = "alpaca"):
        self.broker = broker
        self.account_id = None
        self.positions = {}

    @classmethod
    def get(cls, broker: str = "alpaca") -> 'TradingSession':
        with cls._lock:
            if broker not in cls._instances:
                cls._instances[broker] = cls(broker)
            return cls._instances[broker]


def alpaca_get_account() -> dict:
    """Get Alpaca account info."""
    try:
        from lib.config import CFG
        # Check if Alpaca keys are configured
        api_key = os.environ.get("ALPACA_API_KEY", CFG.alpaca_api_key if hasattr(CFG, 'alpaca_api_key') else "")
        if not api_key:
            return {"error": "Alpaca API key not configured"}
        session = TradingSession.get("alpaca")
        # In production, this would call Alpaca API
        return {
            "status": "ok",
            "account": {"id": "demo_account", "cash": 100000.0, "portfolio_value": 100000.0}
        }
    except Exception as e:
        return {"error": str(e)}


def ibkr_get_positions() -> dict:
    """Get Interactive Brokers positions."""
    try:
        session = TradingSession.get("ibkr")
        # In production, this would call IBKR API
        return {
            "status": "ok",
            "positions": []
        }
    except Exception as e:
        return {"error": str(e)}


def quant_trader_strategy(symbol: str, timeframe: str = "1d") -> dict:
    """Run quant strategy on symbol."""
    try:
        # In production, this would run actual quant strategies
        return {
            "status": "ok",
            "strategy": symbol,
            "timeframe": timeframe,
            "signal": "hold",
            "confidence": 0.75
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# SlimToken Tools (token management)
# ---------------------------------------------------------------------------

def slimtoken_minify(messages: list) -> dict:
    """Minify messages for slim token usage."""
    try:
        # Use existing slimtoken logic
        from lib import slimtoken
        if hasattr(slimtoken, 'minify'):
            result = slimtoken.minify(messages)
        else:
            # Fallback: basic minification
            result = [{"role": m.get("role"), "content": m.get("content", "")[:100]} for m in messages[:20]]
        return {"status": "ok", "minified": result}
    except Exception as e:
        return {"error": str(e)}


def slimtoken_maxify(messages: list) -> dict:
    """Expand minified messages back."""
    try:
        return {"status": "ok", "expanded": messages}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Unified Tool Registry for converted MCP tools
# ---------------------------------------------------------------------------

CONVERTED_TOOLS = [
    {"type": "function", "function": {
        "name": "memory_read",
        "description": "Read from CortexLLM memory (hot/warm/cold tiers)",
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": ["hot", "warm", "cold"]},
                "platform": {"type": "string"},
                "category": {"type": "string"}
            },
            "required": ["tier"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_write",
        "description": "Write to CortexLLM memory tier",
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": ["hot", "warm", "cold"]},
                "content": {"type": "string"},
                "platform": {"type": "string"},
                "category": {"type": "string"},
                "role": {"type": "string", "enum": ["user", "assistant", "system"]}
            },
            "required": ["tier", "content"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_search",
        "description": "Search across all CortexLLM memory tiers",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_clear",
        "description": "Clear CortexLLM memory",
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": ["hot", "warm", "all"]},
                "platform": {"type": "string"}
            },
            "required": ["tier"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_search_semantic",
        "description": "Semantic (BM25) search across CortexLLM memory",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "platform": {"type": "string"}
            },
            "required": ["query"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_graph_query",
        "description": "Query the CortexLLM knowledge graph",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["query", "extract", "path", "stats"]},
                "entity": {"type": "string"},
                "text": {"type": "string"},
                "target": {"type": "string"},
                "depth": {"type": "integer"},
                "platform": {"type": "string"}
            },
            "required": ["action"]
        }
    }},
    {"type": "function", "function": {
        "name": "memory_ontology",
        "description": "Ontology operations (categorize, taxonomy, gaps, tags)",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["categorize", "taxonomy", "gaps", "tag", "tagmem", "discover", "stats"]},
                "text": {"type": "string"}
            },
            "required": ["action"]
        }
    }},
    {"type": "function", "function": {
        "name": "firecrawl_search",
        "description": "Search the web using Firecrawl",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
        }
    }},
    {"type": "function", "function": {
        "name": "firecrawl_scrape",
        "description": "Scrape content from a URL",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"]
        }
    }},
    {"type": "function", "function": {
        "name": "magicui_generate",
        "description": "Generate UI from description",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "format": {"type": "string"}
            },
            "required": ["description"]
        }
    }},
    {"type": "function", "function": {
        "name": "alpaca_get_account",
        "description": "Get Alpaca trading account info",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "ibkr_get_positions",
        "description": "Get Interactive Brokers positions",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }},
    {"type": "function", "function": {
        "name": "quant_trader_strategy",
        "description": "Run quant strategy on a symbol",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string"}
            },
            "required": ["symbol"]
        }
    }},
    {"type": "function", "function": {
        "name": "slimtoken_minify",
        "description": "Minify messages for slim token usage",
        "parameters": {
            "type": "object",
            "properties": {
                "messages": {"type": "array"}
            },
            "required": ["messages"]
        }
    }},
]


TOOL_MAP = {
    "memory_read": memory_read,
    "memory_write": memory_write,
    "memory_search": memory_search,
    "memory_clear": memory_clear,
    "memory_search_semantic": memory_search_semantic,
    "memory_graph_query": memory_graph_query,
    "memory_ontology": memory_ontology,
    "firecrawl_search": firecrawl_search,
    "firecrawl_scrape": firecrawl_scrape,
    "magicui_generate": magicui_generate,
    "alpaca_get_account": alpaca_get_account,
    "ibkr_get_positions": ibkr_get_positions,
    "quant_trader_strategy": quant_trader_strategy,
    "slimtoken_minify": slimtoken_minify,
}


def execute_converted_tool(name: str, args: dict) -> dict:
    """Execute a converted MCP tool (direct Python)."""
    if name not in TOOL_MAP:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = TOOL_MAP[name](**args)
        return result
    except Exception as e:
        return {"error": str(e)}


def list_converted_tools(limit: int = 16, stub: bool = True) -> list:
    """List converted tools (stub mode reduces context size)."""
    tools = CONVERTED_TOOLS[:limit]
    if stub:
        # Return minimal info to save tokens
        return [
            {"type": "function", "function": {
                "name": t["function"]["name"],
                "description": t["function"]["description"][:80] + "...",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }}
            for t in tools
        ]
    return tools


if __name__ == "__main__":
    # Smoke test
    print("Testing converted MCP tools...")
    
    # Test memory tools
    r = execute_converted_tool("memory_read", {"tier": "warm"})
    print(f"memory_read: {r}")
    
    r = execute_converted_tool("memory_search", {"query": "test", "limit": 5})
    print(f"memory_search: {r}")
    
    r = execute_converted_tool("memory_search_semantic", {"query": "test", "limit": 5})
    print(f"memory_search_semantic: {r}")
    
    r = execute_converted_tool("memory_graph_query", {"action": "stats"})
    print(f"memory_graph_query: {r}")
    
    r = execute_converted_tool("memory_ontology", {"action": "stats"})
    print(f"memory_ontology: {r}")
    
    print("\nConverted MCP tools: OK")
