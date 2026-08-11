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
  # Save full prompt (no truncation) to shared CortexLLM memory.
  # Single write path via lib/memory_thin.py — daemon first, direct fallback.
  # No caps (2026-08-11 hard rule). Mirrors to hot + warm atomically.
  PYTHONPATH="${REPO_ROOT}" python3 -c "
from lib.memory_thin import append
import sys
sys.stdout.write(str(append('user', sys.argv[1], platform='cortexagent')))
" "${prompt}" >/dev/null 2>&1 || true

  # ── Prompt queue (DEFAULT behavior) ──────────────────────────────────────
  # Decompose the prompt into a queued agenda, detect conflicts against prior
  # items, and either block (asking the user to resolve a contradiction) or
  # inject the agenda so the agent works the queue in order. Cheap (no LLM),
  # non-fatal: any error → the prompt passes through unqueued.
  hook_json="$(printf '%s' "${prompt}" | PYTHONPATH="${REPO_ROOT}" python3 -c '
import json, sys
try:
    prompt = sys.stdin.read()
    from lib import prompt_queue as pq
    res = pq.submit(prompt)
    if res.conflicts:
        # Hold the conflicting submission; surface the first conflict as a
        # blocking question exactly as the user specified.
        print(json.dumps({"decision": "block", "reason": res.conflicts[0]}))
    else:
        ctx = pq.agenda_context()
        if ctx:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": ctx,
            }}))
except Exception as e:
    sys.stderr.write(f"prompt_queue hook error (non-fatal): {e}\n")
' 2>/dev/null || true)"
  if [ -n "${hook_json}" ]; then
    printf '%s\n' "${hook_json}"
  fi
fi

exit 0