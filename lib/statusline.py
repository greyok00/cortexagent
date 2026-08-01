#!/usr/bin/env python3
"""cortexagent statusline — branded bottom bar for the agent TUI.

Reads the agent's status JSON on stdin and prints a single branded line:
    CortexAgent · GreyOK00 · <model> · <cwd> · <ctx tokens>

The agent CLI calls this on every render. Output is plain text (one line).
Fails soft: on any error, prints a minimal branded line so the TUI never
loses its status bar.
"""
import json
import os
import sys


def main():
    raw = sys.stdin.read()
    d = {}
    try:
        d = json.loads(raw) if raw.strip() else {}
    except Exception:
        d = {}

    model = ""
    m = d.get("model")
    if isinstance(m, dict):
        model = m.get("display_name") or m.get("id") or ""
    elif isinstance(m, str):
        model = m

    cwd = d.get("cwd") or d.get("workspace", {}).get("current_dir") or ""
    if cwd:
        home = os.path.expanduser("~")
        if cwd == home:
            cwd = "~"
        elif cwd.startswith(home + os.sep):
            cwd = "~" + cwd[len(home):]

    # Context usage — field name varies by CLI version. Prefer current-context
    # fields; fall back to nothing rather than show a misleading number.
    ctx_str = ""
    cw = d.get("context_window") or {}
    if isinstance(cw, dict):
        used = cw.get("used") or cw.get("used_tokens") or cw.get("current")
        total = cw.get("total") or cw.get("limit") or cw.get("max")
        if used and total:
            ctx_str = f"{used}/{total} tok"
    if not ctx_str:
        ex = d.get("exceeds_200k_tokens")
        if isinstance(ex, dict):
            ctx_str = f"{ex.get('token_count','?')} tok"

    parts = ["CortexAgent", "GreyOK00"]
    if model:
        parts.append(model)
    if cwd:
        parts.append(cwd)
    if ctx_str:
        parts.append(ctx_str)
    print(" · ".join(str(p) for p in parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never let the statusline break the TUI.
        print("CortexAgent · GreyOK00")