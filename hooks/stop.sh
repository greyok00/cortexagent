#!/bin/bash
# stop.sh — fires when the agent finishes a turn.
#
# Captures the assistant's final response (the turn's "context") into CortexAgent
# hot memory via the canonical pipeline, so recovery has what was DONE, not just
# the user's prompts. Skips re-saving the same turn on repeat Stop fires.
#
# Always exits 0 (non-blocking, non-fatal). Memory failures are logged to stderr.
set -eu

REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# shellcheck source=../lib/state.sh
. "${REPO_ROOT}/lib/state.sh"
cc_state_init

payload="$(cat || true)"
transcript="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    sys.stdout.write(d.get("transcript_path") or "")
except Exception:
    pass
' 2>/dev/null || true)"

[ -n "${transcript}" ] && [ -f "${transcript}" ] || exit 0

# Extract the last assistant text + its uuid from the transcript JSONL.
read -r uuid text <<< "$(python3 - "${transcript}" <<'PY'
import json, sys
path = sys.argv[1]
last_uuid = ""
last_text = ""
with open(path, errors="replace") as fh:
    for line in fh:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message") or {}
        blocks = msg.get("content") or []
        if not isinstance(blocks, list):
            continue
        parts = [b.get("text", "") for b in blocks
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
        text = " ".join(parts).strip()
        if not text:
            continue
        last_uuid = d.get("uuid") or ""
        last_text = text
# uuid cannot contain spaces; space-separate uuid and text for the bash read
print(last_uuid.replace(" ", "_") + " " + last_text[:2000].replace("\n", " "))
PY
)"

[ -n "${text}" ] || exit 0
[ -n "${uuid}" ] || exit 0

# Skip if this turn was already saved (repeat Stop fire).
marker="$(_cortexagent_state_dir)/last-assistant-uuid"
if [ -f "${marker}" ] && [ "$(cat "${marker}" 2>/dev/null || true)" = "${uuid}" ]; then
  exit 0
fi

# Save the assistant context through the memory pipeline + MCP-readable file.
python3 "${REPO_ROOT}/lib/cortexagent_call.py" write --role assistant --content "${text}" >/dev/null 2>&1 || true
printf '%s' "${uuid}" > "${marker}"

exit 0