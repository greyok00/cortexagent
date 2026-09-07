#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


_MULTIMODAL = {
    "claude-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5",
    "claude-fable-5", "claude-3-5-sonnet", "claude-3-7-sonnet",
    "claude-3-opus", "claude-3-haiku", "claude-3-sonnet",
    "gpt-4o", "gpt-4o-mini", "gpt-4-vision", "gpt-4-turbo",
    "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "llava", "llava-llama3",
    "moondream", "minicpm-v", "internvl",
    # GLM family is multimodal (glm5_next arch reports vision capability).
    "glm", "glm-5.3-flash", "glm-4v", "glm-4.5v",
}


def _current_model() -> str:

    for key in ("CLAUDE_CODE_SUBAGENT_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        v = os.environ.get(key)
        if v:
            return v
    try:
        am = json.loads((Path.home() / ".cortexagent" / "state"
                         / "active_model.json").read_text())
        m = am.get("model")
        if m:
            return m
    except Exception:
        pass
    return "unknown"


def is_multimodal(model: str) -> bool:

    m = model.lower()

    base = m.split(":")[0]
    if base in _MULTIMODAL:
        return True

    return any(k in m for k in ("-vl", "vision", "multimodal", "llava"))


def main() -> int:
    model = _current_model()
    if is_multimodal(model):
        print(f"OK: model '{model}' is multimodal — safe to send the image.")
        return 0
    print(
        f"BLOCKED: model '{model}' is NOT multimodal. "
        "Do NOT send the image — it will 400 and crash. "
        "Ask the user instead (they can describe it, or switch to a "
        "multimodal model).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
