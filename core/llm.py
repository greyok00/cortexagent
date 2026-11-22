"""core.llm — thin model-server client for loop.py (contract-fitted).

_query_llm(prompt, system, max_tokens) -> str (direct mode)
_query_llm_with_tools(messages, tools, max_tokens, timeout) -> reply dict
  {"kind": "text", "content": str}
  {"kind": "tool_calls", "calls": [{"name": ..., "args": {...}}]}

Server down, malformed reply, or empty content with no calls -> None (loop
maps None to "model unavailable"). Both functions speak HTTP to the local
OpenAI-compatible engine server; no VRAM or model load lives here. Every
successful reply also bumps the real usage counters (USAGE["calls"],
LAST_TPS) that the system tool and the TUI footer report.

Created 2026-11-11 to close the forever-missing import. Signatures match
core/loop.py's call sites (messages-first, max_tokens/timeout kwargs) so
tests can monkeypatch with lambdas of that shape.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

# Real usage counters, filled from the engine's own response in _post().
# USAGE["calls"] counts completed model calls; LAST_TPS is the completion
# tokens-per-second of the most recent one (0.0 until the server reports
# usage). The system tool and the TUI footer read these — 2026-11-21 audit:
# wiring/system_status used to read them before anything defined them.
USAGE = {"calls": 0}
LAST_TPS = 0.0


def _track(data: dict, elapsed: float) -> None:
    """Record one completed call from the engine's response body."""
    global LAST_TPS
    USAGE["calls"] += 1
    usage = data.get("usage") or {}
    toks = int(usage.get("completion_tokens") or 0)
    if toks > 0 and elapsed > 0:
        LAST_TPS = toks / elapsed


def _resolve_base() -> str:
    """Same knobs the launcher exports (bin/cortex-agent): the lane/direct
    base when set, else the engine's own port (default :7100 — :7090 is the
    sibling family's port, per the launcher header's port law)."""
    env = os.environ.get("CORTEXENGINE_LOCAL_BASE") or ""
    if env:
        base = env.rstrip("/")
        return base[:-3] if base.endswith("/v1") else base
    return "http://127.0.0.1:%d" % int(os.environ.get("CORTEXENGINE_PORT", "7100"))


BASE = _resolve_base()


def _post(body: dict, timeout: float):
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            msg = data["choices"][0].get("message") or None
    except Exception:
        return None
    _track(data, time.monotonic() - t0)
    return msg


def _query_llm(prompt: str, system: str = "", max_tokens: int = 1024,
               timeout: float = 90):
    """Direct (no-tools) mode: returns the assistant text, or None."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    msg = _post({"messages": messages, "max_tokens": int(max_tokens),
                 "stream": False}, timeout)
    if msg is None:
        return None
    return msg.get("content") or ""


def _query_llm_with_tools(messages, tools=None, max_tokens: int = 1024,
                          timeout: float = 90):
    """Tool loop reply: loop-shaped dict keyed on "kind"; None on failure."""
    body = {"messages": list(messages or []), "max_tokens": int(max_tokens),
            "stream": False}
    if tools:
        body["tools"] = list(tools)
    msg = _post(body, timeout)
    if msg is None:
        return None
    tc = msg.get("tool_calls") or []
    if tc:
        calls = []
        for c in tc:
            fn = (c.get("function") or {})
            name = fn.get("name") or c.get("name") or ""
            raw = fn.get("arguments")
            if isinstance(raw, str):
                try:
                    args = json.loads(raw)
                except Exception:
                    args = {}
            elif isinstance(raw, dict):
                args = raw
            else:
                args = {}
            if name:
                calls.append({"name": name, "args": args})
        if calls:
            return {"kind": "tool_calls", "calls": calls}
    content = msg.get("content") or ""
    return {"kind": "text", "content": content}
