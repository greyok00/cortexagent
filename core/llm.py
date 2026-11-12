"""core.llm — thin model-server client for loop.py (contract-fitted).

_query_llm(prompt, system, max_tokens) -> str (direct mode)
_query_llm_with_tools(messages, tools, max_tokens, timeout) -> reply dict
  {"kind": "text", "content": str}
  {"kind": "tool_calls", "calls": [{"name": ..., "args": {...}}]}

Server down, malformed reply, or empty content with no calls -> None (loop
maps None to "model unavailable"). Both functions speak HTTP to the local
OpenAI-compatible model server (:7090); no VRAM or model load lives here.

Created 2026-11-11 to close the forever-missing import. Signatures match
core/loop.py's call sites (messages-first, max_tokens/timeout kwargs) so
tests can monkeypatch with lambdas of that shape.
"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:7090"


def _post(body: dict, timeout: float):
    req = urllib.request.Request(
        BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            return data["choices"][0].get("message") or None
    except Exception:
        return None


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
