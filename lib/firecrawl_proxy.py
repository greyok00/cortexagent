#!/usr/bin/env python3
"""firecrawl_proxy — lazy single-tool MCP wrapper for the firecrawl MCP server.

Presents exactly one tool (firecrawl) to Claude Code and only spawns the
real npx firecrawl-mcp process when that tool is called. Keeps the 26 native
firecrawl tools "cold" — no idle cost, no per-request token tax.

Usage:
  python3 lib/firecrawl_proxy.py            # stdio MCP server
  python3 lib/firecrawl_proxy.py smoke      # self-test

Protocol: JSON-RPC 2.0 over stdio (MCP).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


FIRECRAWL_CMD = ["npx", "-y", "firecrawl-mcp"]
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")

FIRECRAWL_METHODS = {
    "scrape", "crawl", "map", "search", "extract", "parse",
    "research_search_papers", "research_read_paper", "research_inspect_paper",
    "research_related_papers", "research_search_github",
    "monitor_create", "monitor_update", "monitor_delete", "monitor_list",
    "monitor_check", "monitor_checks", "monitor_run", "monitor_get",
    "agent", "agent_status", "interact", "interact_stop", "feedback",
    "check_crawl_status", "search_feedback",
}

TOOL_NAME = "firecrawl"
TOOL_DESCRIPTION = "Lazy Firecrawl proxy. Call with {method, args}. Methods: " + ", ".join(sorted(FIRECRAWL_METHODS)) + "."


def _send_json(obj: Dict[str, Any]) -> None:
    raw = json.dumps(obj, ensure_ascii=False) + "\n"
    sys.stdout.write(raw)
    sys.stdout.flush()


def _read_json() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception as e:
        return {"_parse_error": str(e), "_raw": line.strip()}


def _call_firecrawl(method: str, args: Dict[str, Any]) -> Tuple[bool, Any]:
    """Spawn the real firecrawl-mcp, call one tool, return (ok, result_or_error)."""
    if method not in FIRECRAWL_METHODS:
        return (False, f"Unknown firecrawl method: {method}. "
                        f"Known methods: {', '.join(sorted(FIRECRAWL_METHODS))}")

    if not FIRECRAWL_API_KEY:
        return (False, "Firecrawl is not configured. Set FIRECRAWL_API_KEY to enable it.")

    env = os.environ.copy()
    env["FIRECRAWL_API_KEY"] = FIRECRAWL_API_KEY

    try:
        proc = subprocess.Popen(
            FIRECRAWL_CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except Exception as e:
        return (False, f"Failed to start firecrawl-mcp: {e}")

    import select as _select

    def read_line(timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        try:
            ready, _, _ = _select.select([proc.stdout], [], [], timeout)  # type: ignore
            if not ready:
                return None
        except Exception:
            return None
        line = proc.stdout.readline()  # type: ignore
        if not line:
            return None
        try:
            return json.loads(line)
        except Exception:
            return None

    def rpc(method_name: str, params: Dict[str, Any], id: int) -> None:
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method_name, "params": params, "id": id}) + "\n")  # type: ignore
        proc.stdin.flush()  # type: ignore

    try:
        # 1. handshake from child (server might send initialize first)
        hello = read_line(timeout=3.0)
        if hello and hello.get("method") == "initialize":
            _send_id = hello.get("id")
            proc.stdin.write(json.dumps({  # type: ignore
                "jsonrpc": "2.0", "id": _send_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "firecrawl-proxy", "version": "1.0"},
                }
            }) + "\n")
            proc.stdin.flush()  # type: ignore

        # 2. trigger the real server's init / tools list
        rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "cortexagent-firecrawl-proxy", "version": "1.0"}}, 1)
        resp = read_line(timeout=10.0)
        if not resp or "result" not in resp:
            err = proc.stderr.read(400) if proc.stderr else ""  # type: ignore
            return (False, f"firecrawl-mcp initialize failed: {resp or err}")

        rpc("tools/list", {}, 2)
        resp = read_line(timeout=10.0)
        if not resp or "result" not in resp:
            err = proc.stderr.read(400) if proc.stderr else ""  # type: ignore
            return (False, f"firecrawl-mcp tools/list failed: {resp or err}")

        # 3. call the requested native tool
        native_tool = f"firecrawl_{method}"
        rpc("tools/call", {"name": native_tool, "arguments": args or {}}, 3)
        resp = read_line(timeout=60.0)
        if not resp:
            err = proc.stderr.read(400) if proc.stderr else ""  # type: ignore
            return (False, f"firecrawl-mcp no response for {native_tool}: {err}")

        if "error" in resp:
            return (False, resp["error"])

        result = resp.get("result", {})
        # Extract content array if present; otherwise return the raw result.
        if isinstance(result, dict) and "content" in result:
            return (True, result["content"])
        return (True, result)
    except Exception as e:
        return (False, f"firecrawl-mcp runtime error: {e}")
    finally:
        try:
            proc.stdin.close()  # type: ignore
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except Exception:
            pass


def _build_tool() -> Dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "Firecrawl method.", "enum": sorted(FIRECRAWL_METHODS)},
                "args": {"type": "object", "description": "Method arguments."},
            },
            "required": ["method"],
        },
    }


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "firecrawl-proxy", "version": "1.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "result": {"tools": [_build_tool()]},
        }

    if method == "tools/call":
        name = params.get("name")
        if name != TOOL_NAME:
            return {
                "jsonrpc": "2.0",
                "id": _id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        arguments = params.get("arguments", {})
        fire_method = arguments.get("method", "")
        fire_args = arguments.get("args", {})
        ok, payload = _call_firecrawl(fire_method, fire_args)
        if ok:
            return {
                "jsonrpc": "2.0",
                "id": _id,
                "result": {"content": payload if isinstance(payload, list) else [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]},
            }
        return {
            "jsonrpc": "2.0",
            "id": _id,
            "error": {"code": -32000, "message": str(payload)},
        }

    # Unknown method — standard JSON-RPC method not found.
    return {
        "jsonrpc": "2.0",
        "id": _id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _smoke() -> int:
    tool = _build_tool()
    print(f"tool exposed: {tool['name']}")
    print(f"methods: {len(FIRECRAWL_METHODS)}")
    print("firecrawl_proxy: OK (no live npx test — requires network)")
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
