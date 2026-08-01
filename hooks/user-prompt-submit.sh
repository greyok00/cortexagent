#!/bin/bash
# user-prompt-submit.sh — fires on every user prompt.
#
# Two jobs, both cheap (no LLM call):
#   1. Remember the prompt as the "last prompt" (for replay-on-compact).
#   2. Save the prompt to CortexAgent through memory_manager.add_message() —
#      the full pipeline: hot write + checkpoint + warm-buffer prune/dedup.
#
# Always exits 0. Memory failures are non-fatal (the session continues;
# we just log to stderr).
set -eu

REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# shellcheck source=../lib/state.sh
. "${REPO_ROOT}/lib/state.sh"

# Read the hook payload from stdin (JSON). Pull the prompt text.
payload="$(cat || true)"
prompt="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    p = d.get("prompt")
    if p is None:
        p = d.get("message") or d.get("text") or ""
    sys.stdout.write(p)
except Exception:
    pass
' 2>/dev/null || true)"

if [ -n "${prompt}" ]; then
  cc_save_last_prompt "$prompt"
  # Truncate to keep hot memory tidy.
  trunc="$(printf '%s' "$prompt" | head -c 2000)"
  python3 "${REPO_ROOT}/lib/cortexagent_call.py" write --role user --content "${trunc}" >/dev/null 2>&1 || true
fi

exit 0