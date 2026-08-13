#!/usr/bin/env python3
"""scripts/tool_bridge.py — the tool surface the cortex CLI (Pi fork) calls.

The cortex CLI's extensions shell out to this script to list and execute the
full CortexAgent tool registry (core + browser + skills). It is the single
stable interface between the TypeScript harness and the Python backend:

  python3 scripts/tool_bridge.py list [--stub] [--limit N]
  python3 scripts/tool_bridge.py run <name> <json-args>
  python3 scripts/tool_bridge.py --smoke

Output is always one JSON document on stdout (machine-readable for the
harness). Exit code 0 on success, 1 on error (error JSON on stdout).

Design rules:
  - Idempotent: ensure_registered() is safe to call every time.
  - Fast: no heavy imports beyond the registry + harness.
  - Stub mode: name + short description only (~35 tokens/tool) so the tiny
    model's 2048-ctx window can see the whole surface. Full schema is
    resolved on run (missing args → helpful error naming the params).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

STUB_MODE = os.environ.get("CORTEXAGENT_TOOL_STUBS", "1") == "1"
MAX_TOOLS = int(os.environ.get("CORTEXAGENT_MAX_TOOLS", "16"))


def _emit(obj: Any, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return code


def _list_tools(stub: bool, limit: Optional[int]) -> List[Dict[str, Any]]:
    from lib.harness_tools import ensure_registered
    from lib.tool_registry import list_tools
    ensure_registered()
    tools = list_tools(limit=limit, stub=stub)
    # Normalize to a flat, harness-friendly shape: name + description always,
    # parameters only in full mode.
    out: List[Dict[str, Any]] = []
    for t in tools:
        fn = t.get("function", t)
        name = fn.get("name", "")
        desc = fn.get("description", "")
        if stub:
            out.append({"name": name, "description": desc})
        else:
            out.append({
                "name": name,
                "description": desc,
                "parameters": fn.get("parameters", {"type": "object",
                                                    "properties": {}}),
            })
    return out


def _run_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from lib.harness_tools import ensure_registered
    from lib.tool_registry import execute_tool
    ensure_registered()
    return execute_tool(name, args)


def _smoke() -> int:
    fails = 0
    tools = _list_tools(stub=True, limit=None)
    if not tools:
        print("❌ list returned no tools")
        fails += 1
    else:
        print(f"✅ list OK ({len(tools)} tools, stub mode)")
    full = _list_tools(stub=False, limit=2)
    if not full or "parameters" not in full[0]:
        print("❌ full list missing parameters")
        fails += 1
    else:
        print("✅ full list OK (parameters present)")
    r = _run_tool("run_command", {"command": "echo bridge-ok"})
    if not r.get("ok"):
        print(f"❌ run_command: {r}")
        fails += 1
    else:
        print("✅ run_command OK")
    print("tool_bridge smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] == "--smoke":
        return _smoke()
    cmd = argv[0]
    if cmd == "list":
        stub = "--stub" in argv or STUB_MODE
        limit = None
        if "--limit" in argv:
            try:
                limit = int(argv[argv.index("--limit") + 1])
            except (ValueError, IndexError):
                return _emit({"ok": False, "error": "bad --limit value"}, 1)
        return _emit({"ok": True, "tools": _list_tools(stub, limit)})
    if cmd == "run":
        if len(argv) < 3:
            return _emit({"ok": False,
                          "error": "usage: tool_bridge.py run <name> <json-args>"}, 1)
        name = argv[1]
        try:
            args = json.loads(argv[2])
        except json.JSONDecodeError as e:
            return _emit({"ok": False, "error": f"bad json args: {e}"}, 1)
        if not isinstance(args, dict):
            return _emit({"ok": False, "error": "args must be a JSON object"}, 1)
        return _emit(_run_tool(name, args))
    return _emit({"ok": False, "error": f"unknown command: {cmd}"}, 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
