#!/usr/bin/env python3
"""lib/harness_tools.py — wires the full tool surface into the registry.

Idempotent ``ensure_registered()`` registers the harness tools once:
  - browser tools (lib/browser_tools — 9 brave_* tools)
  - skills (lib/skills — skill_<name> from ~/.cortexagent/skills/)
  - MCP server tools (lib/mcp_client — mcp_<server>_<tool>)

Called from ``react_loop.run_react`` before ``list_tools()`` so the overseer
loop sees the full tool surface. ``CORTEXAGENT_HARNESS_TOOLS=0`` disables
(loop falls back to the core registry only).

Usage:
  python3 lib/harness_tools.py smoke          # self-test
"""
from __future__ import annotations

import os
import sys
from typing import Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_registered = False


def ensure_registered() -> int:
    """Register browser + skills + MCP tools once. Returns tools added.

    Idempotent (module-level flag). Failure-tolerant: each subsystem is
    independent — a broken MCP server or missing skills dir never blocks
    the others. Disabled entirely by CORTEXAGENT_HARNESS_TOOLS=0.
    """
    global _registered
    if _registered:
        return 0
    if os.environ.get("CORTEXAGENT_HARNESS_TOOLS", "1") == "0":
        _registered = True
        return 0
    total = 0
    try:
        from lib.browser_tools import register_browser_tools
        total += register_browser_tools()
    except Exception as e:
        print(f"harness_tools: browser tools skipped: {e}", file=sys.stderr)
    try:
        from lib.skills import load_skills_dir, register_skill_tools
        load_skills_dir()
        total += register_skill_tools()
    except Exception as e:
        print(f"harness_tools: skills skipped: {e}", file=sys.stderr)
    # MCP servers are opt-in: only load when CORTEXAGENT_MCP_SERVERS names
    # them. Their schemas are verbose and would crowd the tiny model's
    # context; the user enables the servers they want (modularized how they
    # want) and raises CORTEXAGENT_MAX_TOOLS to fit them.
    if os.environ.get("CORTEXAGENT_MCP_SERVERS", "").strip():
        try:
            from lib.mcp_client import register_mcp_tools
            total += register_mcp_tools()
        except Exception as e:
            print(f"harness_tools: MCP tools skipped: {e}", file=sys.stderr)
    _registered = True
    return total


def _smoke() -> int:
    n = ensure_registered()
    from lib.tool_registry import list_tools
    tools = list_tools()
    print(f"registered {n} harness tools — total registry: {len(tools)}")
    names = [t["function"]["name"] for t in tools]
    brave = [x for x in names if x.startswith("brave_")]
    skills = [x for x in names if x.startswith("skill_")]
    mcp = [x for x in names if x.startswith("mcp_")]
    print(f"  brave_*: {len(brave)}  skill_*: {len(skills)}  mcp_*: {len(mcp)}")
    print("harness_tools: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    print("usage: harness_tools.py smoke", file=sys.stderr)
    sys.exit(2)
