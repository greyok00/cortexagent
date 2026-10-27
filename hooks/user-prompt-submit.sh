#!/bin/bash
set -eu

REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

. "${REPO_ROOT}/lib/state.sh"

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
  PYTHONPATH="${REPO_ROOT}" python3 -c "
from lib.memory_thin import append
import sys
sys.stdout.write(str(append('user', sys.argv[1], platform='cortexagent')))
" "${prompt}" >/dev/null 2>&1 || true

  python3 "${REPO_ROOT}/lib/prompt_queue.py" clear >/dev/null 2>&1 || true

  hook_json="$(printf '%s' "${prompt}" | PYTHONPATH="${REPO_ROOT}" python3 -c '
import json, sys
try:
    prompt = sys.stdin.read()
    from lib import prompt_queue as pq
    pq.submit(prompt)
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
