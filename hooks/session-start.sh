#!/bin/bash
set -eu
REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "${REPO_ROOT}/lib/state.sh"

# Start overseer daemon (heartbeat + orchestrator combined)
python3 "$REPO_ROOT/lib/overseer.py" start --interval 30 >/dev/null 2>&1 || true

payload="$(cat || true)"
source="$(printf '%s' "$payload" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('source','startup') or 'startup')" 2>/dev/null || echo "startup")"

# Read from CortexAgent memory (own DB)
AGENT_MEMORY=""
AGENT_MEMORY="$(python3 "$REPO_ROOT/lib/cortexagent_call.py" recent --limit 12 2>/dev/null || true)"

# Read from shared CortexLLM hot memory (try cortexagent platform first, fall back to claude)
CORTEXLLM_MEMORY=""
for _platform in "cortexagent" "claude"; do
  CORTEXLLM_FILE="$HOME/.config/cortexllm/memory/hot/${_platform}.jsonl"
  if [ -f "$CORTEXLLM_FILE" ] && [ -s "$CORTEXLLM_FILE" ]; then
    CORTEXLLM_MEMORY="$(tail -20 "$CORTEXLLM_FILE" 2>/dev/null | python3 -c "
import json, sys
lines = [json.loads(l) for l in sys.stdin.read().strip().split('\n') if l.strip()]
print(f'({_platform} — {len(lines)} recent entries)')
for m in reversed(lines[-10:]):
    role = m.get('role', '?')
    content = m.get('content', '')[:5000]
    ts = m.get('timestamp', '')[:16]
    print(f'[{ts}] {role}: {content}')
" 2>/dev/null || true)"
    [ -n "$CORTEXLLM_MEMORY" ] && break
  fi
done

python3 - "$source" "$AGENT_MEMORY" "$CORTEXLLM_MEMORY" <<'PY'
import json, os, sys
source = sys.argv[1]
agent_mem = sys.argv[2]
cortexllm_mem = sys.argv[3]

lines = ""
if agent_mem:
    lines = "🤖 CortexAgent memory:\n" + agent_mem
if cortexllm_mem:
    if lines:
        lines += "\n"
    lines += "💬 Claude Code memory:\n" + cortexllm_mem
if not lines:
    lines = "(No prior memory found)"

if source == "compact":
    f = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'cortexagent', 'last-prompt')
    try:
        with open(f) as fh:
            last = fh.read().strip()
        if last:
            lines += "\n\nContext was just compacted. Continue the user's last request:\n" + last
    except:
        pass

print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': lines}}))
PY
exit 0
