#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_registered = False


def ensure_registered() -> int:

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
    chrome = [x for x in names if x.startswith("chrome_")]
    skills = [x for x in names if x.startswith("skill_")]
    mcp = [x for x in names if x.startswith("mcp_")]
    print(f"  chrome_*: {len(chrome)}  skill_*: {len(skills)}  mcp_*: {len(mcp)}")
    print("harness_tools: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    print("usage: harness_tools.py smoke", file=sys.stderr)
    sys.exit(2)
