#!/usr/bin/env python3
"""Build the boot-fast system prompt chain (hardened build).

cortexagent.md (raw, owner-editable, in ~/.cortexagent/agent)
  → cortexagent.md.min (whitespace-collapsed; semantics preserved — this only
    strips blank-line runs, indents and trailing spaces, NEVER words)
  → APPEND_SYSTEM.md (the file the TUI actually loads every session):
      the owner's HARD RULES block preserved VERBATIM, then a separator,
      then the minified agent instructions.
Edit cortexagent.md and rerun this script — APPEND_SYSTEM.md is generated,
never hand-edited (edits die on the next run).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIR = Path.home() / ".cortexagent" / "agent"
SRC = AGENT_DIR / "cortexagent.md"
MIN = AGENT_DIR / "cortexagent.md.min"
APPEND = AGENT_DIR / "APPEND_SYSTEM.md"


def minify(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    out, blank = [], 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln.lstrip())
    return "\n".join(out).strip() + "\n"


def main() -> int:
    src = SRC.read_text()
    if not src.strip():
        print(f"minify_prompt: {SRC} is empty — refusing to blank the prompt channel", file=sys.stderr)
        return 1
    mini = minify(src)
    MIN.write_text(mini)
    hard = APPEND.read_text() if APPEND.exists() else ""
    if "HARD RULES" in hard:
        rules = hard.split("\n---\n")[0].strip()
    else:
        rules = ""
    combined = (rules + ("\n\n---\n\n" if rules else "")) + mini if rules else mini
    APPEND.write_text(combined)
    print(f"cortexagent.md ({len(src)} B) -> {MIN.name} ({len(mini)} B); "
          f"APPEND_SYSTEM.md = HARD RULES + minified prompt ({len(combined)} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())