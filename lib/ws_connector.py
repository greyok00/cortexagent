#!/usr/bin/env python3
"""lib/ws_connector.py — WebSocket connector for persistent bidirectional connections.

Phase 4 — WebSockets (conditional). Only used when a tool/model requires
persistent bidirectional communication. Currently:
  - Cortex router uses SSE streaming (no persistent connection needed)
  - Browser control uses CDP websockets (already in browser_control.py)
  - This module is available for future WebSocket-based tools

Usage:
  from lib.ws_connector import WSConnector
  conn = WSConnector("ws://localhost:8082")
  await conn.send({"type": "ping"})
  msg = await conn.recv()
  await conn.close()
"""
from __future__ import annotations

import json
import os
import asyncio
import time
from typing import Any, Callable, Dict, Optional

# Lazy import websocket (only loaded when actually used)
_ws: Optional[Any] = None


def _get_ws():
    """Lazy-load websocket module."""
    global _ws
    if _ws is None:
        import websocket
        _ws = websocket
    return _ws


class WSConnector:
    """WebSocket connector for persistent bidirectional connections.

    Args:
      url: WebSocket endpoint (ws:// or wss://).
      on_message: Callback for received messages.
      on_error: Callback for errors.
      on_open: Callback for connection open.
      reconnect_delay: Seconds between reconnect attempts.
      max_reconnect_delay: Cap on reconnect delay.
    """

    def __init__(self, url: str,
                 on_message: Optional[Callable] = None,
                 on_error: Optional[Callable] = None,
                 on_open: Optional[Callable] = None,
                 reconnect_delay: float = 1.0,
                 max_reconnect_delay: float = 30.0):
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self.on_open = on_open
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._ws = None
        self._running = False

    def connect(self, headers: Optional[Dict[str, str]] = None) -> bool:
        """Open WebSocket connection. Returns True if successful."""
        try:
            ws = _get_ws()
            self._ws = ws.create_connection(
                self.url,
                timeout=10,
                headers=headers or {},
                suppress_origin=True,
            )
            self._running = True
            if self.on_open:
                self.on_open(self)
            return True
        except Exception as e:
            if self.on_error:
                self.on_error(str(e))
            return False

    def send(self, data: Dict[str, Any]) -> bool:
        """Send JSON data. Returns True if successful."""
        if not self._ws or not self._running:
            return False
        try:
            self._ws.send(json.dumps(data))
            return True
        except Exception as e:
            if self.on_error:
                self.on_error(str(e))
            return False

    def recv(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Receive JSON data. Returns None on timeout/error."""
        if not self._ws or not self._running:
            return None
        try:
            self._ws.settimeout(timeout)
            raw = self._ws.recv()
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
        except Exception as e:
            if self.on_error:
                self.on_error(str(e))
            return None

    def close(self) -> None:
        """Close the connection."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def __del__(self):
        self.close()


class AsyncWSConnector:
    """Async WebSocket connector for use with asyncio."""

    def __init__(self, url: str, on_message: Optional[Callable] = None):
        self.url = url
        self.on_message = on_message
        self._ws = None
        self._running = False
        self._reconnect_task = None

    async def connect(self) -> bool:
        """Open async WebSocket connection."""
        try:
            import websockets
            self._ws = await websockets.connect(self.url)
            self._running = True
            # Start receiving
            asyncio.create_task(self._receive_loop())
            return True
        except Exception:
            return False

    async def send(self, data: Dict[str, Any]) -> None:
        """Send JSON data."""
        if self._ws:
            await self._ws.send(json.dumps(data))

    async def recv(self) -> Optional[Dict[str, Any]]:
        """Receive JSON data."""
        if self._ws:
            try:
                raw = await self._ws.recv()
                return json.loads(raw)
            except Exception:
                return None
        return None

    async def close(self) -> None:
        """Close the connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _receive_loop(self) -> None:
        """Continuously receive messages."""
        while self._running and self._ws:
            try:
                msg = await self._ws.recv()
                try:
                    data = json.loads(msg)
                    if self.on_message:
                        self.on_message(data)
                except Exception:
                    pass
            except Exception:
                break


# ── Module-level convenience ──────────────────────────────────────────────────

async def connect(url: str) -> Optional[AsyncWSConnector]:
    """Create and connect an async WebSocket connector."""
    conn = AsyncWSConnector(url)
    if await conn.connect():
        return conn
    return None


def connect_sync(url: str, **kwargs) -> Optional[WSConnector]:
    """Create and connect a sync WebSocket connector."""
    conn = WSConnector(url, **kwargs)
    if conn.connect():
        return conn
    return None


# ── Self-tests ────────────────────────────────────────────────────────────────
def _smoke() -> int:
    """Smoke test the WebSocket connector (no server needed)."""
    fails = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal fails
        if not cond:
            print(f"❌ {label}: {detail}")
            fails += 1
        else:
            print(f"✅ {label}")

    from lib.ws_connector import WSConnector, AsyncWSConnector
    check("WSConnector imported", True)
    check("AsyncWSConnector imported", True)

    # Connector creation
    conn = WSConnector("ws://localhost:8082")
    check("WSConnector created", conn is not None)
    check("connector URL", conn.url == "ws://localhost:8082")

    # Async connector creation
    async_conn = AsyncWSConnector("ws://localhost:8082")
    check("AsyncWSConnector created", async_conn is not None)

    print("✅ ws_connector smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(_smoke() if "--smoke" in sys.argv else 0)
