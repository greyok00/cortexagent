from __future__ import annotations

import sys
from pathlib import Path

# The prompt file is a source artifact, not compiled state — edited by hand
# (owner edits between boots are the whole point). Every read is fail-open:
# a missing/unreadable file degrades to a one-line stand-in so the module can
# never take the whole brain down at import time (the import-crash class the
# 2026-11-03 audit codified for this fork family).
PROMPT_FILE = Path(__file__).resolve().parent / "system-prompt.txt"

_FILE_MISSING = "cortexagent: system prompt file missing — plain, careful answers."
_READ_FAILED = "cortexagent: system prompt unreadable — plain, careful answers."


def load_system_prompt() -> str:
    try:
        text = PROMPT_FILE.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return _READ_FAILED
    if not text.strip():
        return _FILE_MISSING
    return text


def reload_system_prompt() -> None:
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = load_system_prompt()


SYSTEM_PROMPT = load_system_prompt()

if __name__ == "__main__":  # live edit check: python3 model/prompt.py
    print(len(SYSTEM_PROMPT), "chars from", PROMPT_FILE, file=sys.stderr)