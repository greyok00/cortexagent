#!/usr/bin/env python3
"""lib/mcp_client.py — MCP client for the CortexAgent harness.

Connects to MCP servers (stdio) and registers their tools in the tool
registry so the overseer react loop can call them. Supports the standard
``~/.mcp.json`` format (``mcpServers``) and the lazy_mcp_servers.json list
format. Each server's tools are registered as ``mcp_<server>_<tool>``.

Design:
  - Persistent background event loop + per-server session cache — a server is
    spawned and connected once, then reused across calls (the react loop may
    call a tool several times; per-call spawn churn would be seconds of
    overhead per call).
  - Failure-tolerant: a server that fails to init is skipped with a stderr
    note — it never breaks the react loop.
  - Lazy: nothing is spawned until a tool is actually called; tool schemas are
    cached at registration time.

Usage:
  python3 lib/mcp_client.py smoke          # self-test (no servers needed)
  python3 lib/mcp_client.py list           # list configured servers + tools
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.tool_registry import register_tool  # noqa: E402

MCP_CONFIG = Path(os.environ.get(
    "CORTEXAGENT_MCP_CONFIG", "~/.mcp.json")).expanduser()
LAZY_CONFIG = Path(os.environ.get(
    "CORTEXAGENT_LAZY_MCP_CONFIG",
    "~/.cortexagent/config/lazy_mcp_servers.json")).expanduser()
# Comma-separated allowlist of server names; empty = all configured.
_SERVER_ALLOW = {s.strip() for s in
                 os.environ.get("CORTEXAGENT_MCP_SERVERS", "").split(",") if s.strip()}

# ── config loading ───────────────────────────────────────────────────────────
def load_servers() -> List[Dict[str, Any]]:
    """Load MCP server configs from ~/.mcp.json and the lazy config.

    Returns a list of {"name", "command", "args", "env"} dicts, deduped by
    name (first wins), filtered by CORTEXAGENT_MCP_SERVERS allowlist.
    """
    servers: Dict[str, Dict[str, Any]] = {}
    if MCP_CONFIG.exists():
        try:
            data = json.loads(MCP_CONFIG.read_text())
            for name, cfg in (data.get("mcpServers") or {}).items():
                command = cfg.get("command", "")
                servers[name] = {
                    "name": name,
                    "command": command,
                    "args": list(cfg.get("args", [])),
                    "env": dict(cfg.get("env", {})),
                }
        except Exception as e:
            print(f"mcp_client: {MCP_CONFIG} error: {e}", file=sys.stderr)
    if LAZY_CONFIG.exists():
        try:
            data = json.loads(LAZY_CONFIG.read_text())
            entries = data if isinstance(data, list) else data.get("servers", [])
            for e in entries:
                name = e.get("name", "mcp")
                if name in servers:
                    continue
                command = e.get("command", [])
                if isinstance(command, str):
                    command = command.split()
                servers[name] = {
                    "name": name,
                    "command": command[0] if command else "",
                    "args": command[1:] if command else [],
                    "env": {},
                }
        except Exception as e:
            print(f"mcp_client: {LAZY_CONFIG} error: {e}", file=sys.stderr)
    if _SERVER_ALLOW:
        servers = {n: s for n, s in servers.items() if n in _SERVER_ALLOW}
    return list(servers.values())


# ── persistent async session pool ───────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_sessions: Dict[str, Tuple[Any, Any]] = {}  # server name -> (ctx, session)


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever,
                                       name="mcp-client-loop", daemon=True)
        _loop_thread.start()
    return _loop


async def _connect(server: Dict[str, Any]) -> Tuple[Any, Any]:
    """Spawn the server and return (stdio_client_ctx, ClientSession)."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = None
    if server.get("env"):
        env = {**os.environ, **server["env"]}
    params = StdioServerParameters(
        command=server["command"],
        args=server.get("args", []),
        env=env,
    )
    ctx = stdio_client(params)
    read, write = await ctx.__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    await session.initialize()
    return ctx, session


def _get_session(server: Dict[str, Any]) -> Tuple[Any, Any]:
    """Return the cached (ctx, session) for a server, connecting on first use."""
    name = server["name"]
    if name in _sessions:
        return _sessions[name]
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(_connect(server), loop)
    ctx, session = future.result(timeout=45)
    _sessions[name] = (ctx, session)
    return ctx, session


def _list_server_tools(server: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List a server's tools. Returns [] on any failure (never raises)."""
    try:
        _, session = _get_session(server)
        loop = _ensure_loop()
        future = asyncio.run_coroutine_threadsafe(session.list_tools(), loop)
        result = future.result(timeout=30)
        return [{"name": t.name, "description": t.description or "",
                 "inputSchema": t.inputSchema or {}}
                for t in result.tools]
    except Exception as e:
        print(f"mcp_client: list tools on '{server['name']}' failed: {e}",
              file=sys.stderr)
        return []


def _call_server_tool(server: Dict[str, Any], tool_name: str,
                      arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a tool on a server. Returns {"ok", "output", "error"}."""
    try:
        _, session = _get_session(server)
        loop = _ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool_name, arguments or {}), loop)
        result = future.result(timeout=120)
        parts: List[str] = []
        for c in result.content or []:
            text = getattr(c, "text", None)
            if text is not None:
                parts.append(str(text))
            elif getattr(c, "data", None) is not None:
                mime = getattr(c, "mimeType", "image")
                parts.append(f"[{mime} data, {len(c.data)} bytes]")
        output = "\n".join(parts)
        if result.isError:
            return {"ok": False, "output": "", "error": output or f"{tool_name} error"}
        return {"ok": True, "output": output, "error": ""}
    except Exception as e:
        return {"ok": False, "output": "",
                "error": f"mcp call {server['name']}/{tool_name} failed: {e}"}


def close_all() -> None:
    """Shut down all cached sessions (best-effort)."""
    global _sessions
    if not _sessions:
        return
    loop = _ensure_loop()

    async def _close():
        for name, (ctx, session) in list(_sessions.items()):
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        _sessions.clear()

    try:
        asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout=10)
    except Exception:
        _sessions.clear()


# ── registration ────────────────────────────────────────────────────────────
def register_mcp_tools() -> int:
    """Register every configured server's tools in the tool registry.

    Returns the number of tools registered. Idempotent (skips names already
    present). Never raises — a broken server is skipped with a stderr note.
    """
    from lib.tool_registry import TOOLS
    count = 0
    for server in load_servers():
        name = server["name"]
        tools = _list_server_tools(server)
        for t in tools:
            tname = t.get("name", "")
            if not tname:
                continue
            full = f"mcp_{name}_{tname}"
            if full in TOOLS:
                continue
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = schema.get("required", []) if isinstance(schema, dict) else []
            register_tool(full, _schema(
                t.get("description", f"MCP tool {tname} on {name}"),
                props, required),
                _make_handler(server, tname))
            count += 1
    return count


def _schema(description: str, properties: Dict[str, Any],
            required: List[str]) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}


def _make_handler(server: Dict[str, Any], tool_name: str):
    def _handler(**kwargs: Any) -> Dict[str, Any]:
        return _call_server_tool(server, tool_name, kwargs)
    return _handler


# ── self-test ───────────────────────────────────────────────────────────────
def _smoke() -> int:
    servers = load_servers()
    print(f"configured servers: {len(servers)}")
    for s in servers:
        print(f"  {s['name']}: {s['command']} {' '.join(s['args'])}")
    if servers:
        tools = _list_server_tools(servers[0])
        print(f"  first server tools: {[t['name'] for t in tools]}")
    print("mcp_client: OK")
    return 0


def _list() -> int:
    servers = load_servers()
    for s in servers:
        tools = _list_server_tools(s)
        print(f"{s['name']}: {len(tools)} tools")
        for t in tools:
            print(f"  mcp_{s['name']}_{t['name']}: {t['description'][:60]}")
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        sys.exit(_list())
    print("usage: mcp_client.py smoke | list", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
