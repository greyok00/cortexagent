#!/usr/bin/env python3
"""lib/tiny_llm.py — shared client for the tiny LFM2.5-1.2B model on llama-server.

Talks to the OpenAI-compatible ``/v1/chat/completions`` endpoint exposed by the
tiny model's llama-server (port 8082, started by lib/overseer.py via
lib/model_backend.py). Replaces every former Ollama ``/api/generate`` call to
``lfm2.5:1.2b`` across the codebase (overseer, media_pipeline, pdf_knowledge,
model_switcher) — so the CortexAgent product has **no Ollama dependency**.

If the tiny server is down, queries return ``None`` (graceful — callers already
treat a missing tiny LLM as non-fatal). The user's personal Ollama instance
(cloud models, intern stack) is separate and is never touched by this module.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402

_PORT = int(CFG.tiny_model_port)
_BASE = f"http://127.0.0.1:{_PORT}"
CHAT_URL = f"{_BASE}/v1/chat/completions"
HEALTH_URL = f"{_BASE}/health"


def is_available(timeout: float = 3.0) -> bool:
    """True iff the tiny llama-server answers /health."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# Default system prompt for the tiny LLM. Injects the operational variant
# of the practical-reasoning profile so every call from the overseer (or
# any other caller) gets plain, short, two-line answers without the caller
# having to repeat itself. Callers can still pass `system=` to override.
_TINY_SYSTEM = (
    "You are the CortexAgent overseer's reasoning engine. Plain language, "
    "short answers (one or two lines), no markdown, no emojis, no narration. "
    "State the action taken and the artifact path. If uncertain, say so."
)

def query(prompt: str, system: str = "", max_tokens: int = 256,
          temperature: float = 0.1, timeout: int = 30) -> Optional[str]:
    """Query the tiny model. Returns the text response, or None if unavailable.

    Mirrors the old Ollama call shape (prompt + system + max_tokens + temp) so
    callers can switch with a one-line change. When `system` is empty, the
    default practical-reasoning frame is applied so every call gets short,
    operational answers without callers having to repeat it.
    """
    messages = []
    messages.append({"role": "system", "content": system or _TINY_SYSTEM})
    messages.append({"role": "user", "content": prompt})
    payload = {
        # llama-server ignores `model` when only one model is loaded; required by
        # the OpenAI schema so we send a placeholder.
        "model": "tiny",
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            CHAT_URL, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        choices = data.get("choices") or [{}]
        content = choices[0].get("message", {}).get("content", "") or ""
        return content.strip()
    except Exception:
        return None


def _parse_tool_calls(message: dict) -> list:
    """Normalize a chat message's tool_calls into [{"id","name","arguments":dict}]."""
    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append({
            "id": tc.get("id", f"call_{len(calls)}"),
            "name": name,
            "arguments": args,
        })
    return calls


def query_with_tools(messages: list, tools: list, max_tokens: int = 512,
                     timeout: int = 60) -> Optional[dict]:
    """Send messages + tools to :8082. Returns {"kind": "text", "content": str}
    or {"kind": "tool_calls", "calls": [...]} or None on server failure."""
    payload = {
        "model": "tiny",
        "messages": messages,
        "tools": tools,
        "max_tokens": int(max_tokens),
        "temperature": 0.1,
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            CHAT_URL, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        choices = data.get("choices") or [{}]
        message = choices[0].get("message", {}) or {}
        calls = _parse_tool_calls(message)
        if calls:
            return {"kind": "tool_calls", "calls": calls}
        content = (message.get("content") or "").strip()
        if content:
            return {"kind": "text", "content": content}
        return None
    except Exception:
        return None


def _test() -> int:
    """Parser unit test — no server needed."""
    fails = 0
    # text response
    msg = {"content": "hello", "tool_calls": None}
    calls = _parse_tool_calls(msg)
    if calls != []:
        print(f"❌ text msg parsed as calls: {calls}")
        fails += 1
    # tool_calls with JSON-string arguments
    msg = {"content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "run_command", "arguments": '{"command": "echo hi"}'}}]}
    calls = _parse_tool_calls(msg)
    if len(calls) != 1 or calls[0]["name"] != "run_command" \
            or calls[0]["arguments"] != {"command": "echo hi"}:
        print(f"❌ tool_calls parse: {calls}")
        fails += 1
    # malformed arguments JSON → arguments stays {} (loop retries)
    msg = {"content": None, "tool_calls": [
        {"id": "call_2", "type": "function",
         "function": {"name": "run_command", "arguments": "{bad json"}}]}
    calls = _parse_tool_calls(msg)
    if len(calls) != 1 or calls[0]["arguments"] != {}:
        print(f"❌ malformed args parse: {calls}")
        fails += 1
    print("tiny_llm parser: OK" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_test())
    # Quick smoke: python3 lib/tiny_llm.py "Say OK in one word."
    ok = is_available()
    print(f"tiny server health: {'OK' if ok else 'DOWN'}")
    if ok and len(sys.argv) > 1:
        print("response:", query(" ".join(sys.argv[1:]), max_tokens=64))