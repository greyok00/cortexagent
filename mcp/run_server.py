#!/usr/bin/env python3
"""run_server.py — spawn a compiled (.so) cortexagent MCP server module.

Kept as PURE SOURCE like build/src/server.py: it is the only entry into a
compiled server module. Usage: python3 mcp/run_server.py --server <name> [--args ...]
The server module must expose main() like build's Cython modules do. Registry
state lives in ~/.cortexagent/agent/mcp_registry.json; nothing here talks to any
external network on its own.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("rest", nargs="*")
    args, extra = ap.parse_known_args()
    # core-resident copies (owner 2026-10-24 integration) take precedence when
    # CORTEXENGINE_CORE_TOOLS is set by the core loader — verified bytes must be
    # the bytes that run; the mcp/ twin stays the distribution original.
    sys.path.insert(0, str(ROOT / "mcp"))  # registry servers stay SEPARATE compiled .so modules
    core_tools = os.environ.get("CORTEXENGINE_CORE_TOOLS")
    if core_tools:
        sys.path.insert(0, core_tools)  # inserted AFTER mcp so it wins import precedence
    sys.argv = [f"mcp-{args.server}", *extra]
    mod = importlib.import_module(args.server)
    if not hasattr(mod, "main"):
        print(f"mcp/{args.server} module has no main() — unconvertible server layout", file=sys.stderr)
        return 1
    return int(mod.main() or 0)


if __name__ == "__main__":
    sys.exit(main())