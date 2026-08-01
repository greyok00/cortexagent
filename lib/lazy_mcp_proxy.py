#!/usr/bin/env python3
"""lazy_mcp_proxy — generic thin wrapper for optional MCP servers.

Exposes one stub tool per configured server. When called, spawns the real
MCP server (stdio), performs handshake, lists real tools, proxies the call,
and shuts the real server down. Keeps idle tool tax minimal.

Config:
  CORTEXAGENT_LAZY_MCP_CONFIG  default: ~/.cortexagent/config/lazy_mcp_servers.json
  Each entry: {"name": "wp-studio", "command": ["npx", "-y", "@wp-studio/mcp"], "tools_hint": ["wp_render", "wp_deploy"]}

Usage:
  python3 lib/lazy_mcp_proxy.py --name wp-studio    # stdio MCP server
  python3 lib/lazy_mcp_proxy.py smoke               # self-test
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CONFIG_PATH = Path(os.environ.get("CORTEXAGENT_LAZY_MCP_CONFIG", "~/.cortexagent/config/lazy_mcp_servers.json")).expanduser()


def _load_config(name: Optional[str] = None) -> List[Dict[str, Any]]:
    if not CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text())
        entries = data if isinstance(data, list) else data.get("servers", [])
        if name:
            return [e for e in entries if e.get("name") == name]
        return entries
    except Exception as e:
        print(f"lazy_mcp_proxy: config error: {e}", file=sys.stderr)
        return []


def _send_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_json(stream) -> Optional[Dict[str, Any]]:
    line = stream.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _proxy_server(command: List[str]) -> Tuple[subprocess.Popen, int]:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    # handshake
    hello = _read_json(proc.stdout)
    if hello and hello.get("method") == "initialize":
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": hello.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "lazy-mcp-proxy", "version": "1.0"},
            }
        }) + "\n")
        proc.stdin.flush()

    proc.stdin.write(json.dumps({
        "jsonrpc": "2.0", "method": "initialize", "id": 1,
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "lazy-mcp-proxy-client", "version": "1.0"}}
    }) + "\n")
    proc.stdin.flush()
    resp = _read_json(proc.stdout)
    if not resp or "result" not in resp:
        err = proc.stderr.read(400) if proc.stderr else ""
        raise RuntimeError(f"real server init failed: {resp or err}")

    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()

    # list real tools
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 2}) + "\n")
    proc.stdin.flush()
    tools_resp = _read_json(proc.stdout)
    real_tools = (tools_resp or {}).get("result", {}).get("tools", [])

    return proc, len(real_tools)


def _call_real(proc: subprocess.Popen, name: str, arguments: Dict[str, Any], req_id: Any) -> Dict[str, Any]:
    proc.stdin.write(json.dumps({
        "jsonrpc": "2.0", "method": "tools/call", "id": 3,
        "params": {"name": name, "arguments": arguments}
    }) + "\n")
    proc.stdin.flush()
    resp = _read_json(proc.stdout)
    if not resp:
        err = proc.stderr.read(400) if proc.stderr else ""
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": f"real server no response: {err}"}}
    if "error" in resp:
        return {"jsonrpc": "2.0", "id": req_id, "error": resp["error"]}
    return {"jsonrpc": "2.0", "id": req_id, "result": resp.get("result", {})}


def _shutdown(proc: subprocess.Popen) -> None:
    try:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:
        pass


def _build_stub(entry: Dict[str, Any]) -> Dict[str, Any]:
    name = entry["name"]
    hint = entry.get("tools_hint", [])
    hint_str = f" Expands to: {', '.join(hint)}." if hint else ""
    return {
        "name": f"lazy_{name}",
        "description": f"Lazy proxy for optional MCP server '{name}'. Spawns real server on call.{hint_str} Arguments: {{\"real_tool\": string, \"arguments\": object}}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "real_tool": {"type": "string", "description": "Tool name on the real server."},
                "arguments": {"type": "object", "description": "Arguments for real_tool."},
            },
            "required": ["real_tool"],
        },
    }


def _run_server(name: str) -> None:
    entries = _load_config(name)
    if not entries:
        # config missing — expose one tool that returns an error
        stub = {
            "name": f"lazy_{name}",
            "description": f"Optional MCP server '{name}' is not configured.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
    else:
        stub = _build_stub(entries[0])

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception as e:
            _send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}})
            continue

        method = req.get("method")
        _id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            _send_json({"jsonrpc": "2.0", "id": _id, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": f"lazy-{name}", "version": "1.0"},
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _send_json({"jsonrpc": "2.0", "id": _id, "result": {"tools": [stub]}})
        elif method == "tools/call":
            tname = params.get("name", "")
            if tname != stub["name"]:
                _send_json({"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": f"Unknown tool: {tname}"}})
                continue
            if not entries:
                _send_json({"jsonrpc": "2.0", "id": _id, "error": {"code": -32000, "message": f"'{name}' not configured in {CONFIG_PATH}"}})
                continue
            args = params.get("arguments", {})
            real_tool = args.get("real_tool", "")
            real_args = args.get("arguments", {})
            entry = entries[0]
            command = entry.get("command", [])
            if isinstance(command, str):
                command = command.split()
            try:
                proc, _ = _proxy_server(command)
                result = _call_real(proc, real_tool, real_args, _id)
            except Exception as e:
                result = {"jsonrpc": "2.0", "id": _id, "error": {"code": -32000, "message": f"lazy proxy failed: {e}"}}
            finally:
                if "proc" in dir() and proc:
                    _shutdown(proc)
            _send_json(result)
        else:
            _send_json({"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": f"Method not found: {method}"}})


def _smoke() -> int:
    entries = _load_config()
    print(f"config entries: {len(entries)}")
    if entries:
        stub = _build_stub(entries[0])
        print(f"stub tool: {stub['name']}")
    print("lazy_mcp_proxy: OK")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=os.environ.get("LAZY_MCP_NAME", ""))
    ap.add_argument("smoke", nargs="?", default=None)
    args = ap.parse_args()

    if args.smoke == "smoke" or (len(sys.argv) > 1 and sys.argv[1] == "smoke"):
        sys.exit(_smoke())

    if not args.name:
        print("usage: lazy_mcp_proxy.py --name SERVER_NAME", file=sys.stderr)
        sys.exit(2)

    _run_server(args.name)


if __name__ == "__main__":
    main()
