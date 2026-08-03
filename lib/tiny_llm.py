#!/usr/bin/env python3
"""lib/tiny_llm.py — shared client for the tiny 0.5b model on llama-server.

Talks to the OpenAI-compatible ``/v1/chat/completions`` endpoint exposed by the
tiny model's llama-server (port 8082, started by lib/overseer.py via
lib/model_backend.py). Replaces every former Ollama ``/api/generate`` call to
``qwen2.5:0.5b`` across the codebase (overseer, media_pipeline, pdf_knowledge,
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


def query(prompt: str, system: str = "", max_tokens: int = 256,
          temperature: float = 0.1, timeout: int = 30) -> Optional[str]:
    """Query the tiny model. Returns the text response, or None if unavailable.

    Mirrors the old Ollama call shape (prompt + system + max_tokens + temp) so
    callers can switch with a one-line change.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
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


if __name__ == "__main__":
    # Quick smoke: python3 lib/tiny_llm.py "Say OK in one word."
    ok = is_available()
    print(f"tiny server health: {'OK' if ok else 'DOWN'}")
    if ok and len(sys.argv) > 1:
        print("response:", query(" ".join(sys.argv[1:]), max_tokens=64))