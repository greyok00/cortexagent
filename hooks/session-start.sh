#!/bin/bash
set -eu
REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "${REPO_ROOT}/lib/state.sh"

python3 "$REPO_ROOT/lib/overseer.py" start --interval 30 >/dev/null 2>&1 || true

python3 "${REPO_ROOT}/lib/prompt_queue.py" clear >/dev/null 2>&1 || true

payload="$(cat || true)"
source="$(printf '%s' "$payload" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('source','startup') or 'startup')" 2>/dev/null || echo "startup")"

AGENT_MEMORY=""
AGENT_MEMORY="$(python3 "$REPO_ROOT/lib/cortexagent_call.py" recent --limit 12 2>/dev/null || true)"

CORTEX_MEMORY=""
CORTEX_MEMORY_FILE="$HOME/.cortexagent/memory/hot/cortexagent.jsonl"
if [ -f "$CORTEX_MEMORY_FILE" ] && [ -s "$CORTEX_MEMORY_FILE" ]; then
  CORTEX_MEMORY="$(tail -20 "$CORTEX_MEMORY_FILE" 2>/dev/null | python3 -c "
import json, sys
lines = [json.loads(l) for l in sys.stdin.read().strip().split('\n') if l.strip()]
print(f'(cortexagent — {len(lines)} recent entries)')
for m in reversed(lines[-10:]):
    role = m.get('role', '?')
    content = m.get('content', '')[:5000]
    ts = m.get('timestamp', '')[:16]
    print(f'[{ts}] {role}: {content}')
" 2>/dev/null || true)"
fi

python3 - "$source" "$AGENT_MEMORY" "$CORTEX_MEMORY" <<'PY'
import json, os, sys
source = sys.argv[1]
agent_mem = sys.argv[2]
cortex_memory = sys.argv[3]

lines = ""
try:
    _mp = os.path.expanduser('~/.cortexagent/master-prompt.md')
    with open(_mp, encoding='utf-8') as fh:
        _master = fh.read().strip()
    if _master:
        lines = "=== MASTER PROMPT (binding, verbatim — scope/format/legal-procedure rules) ===\n" + _master + "\n\n"
except OSError:
    pass
if agent_mem:
    lines += "🤖 CortexAgent memory:\n" + agent_mem
if cortex_memory:
    if lines:
        lines += "\n"
    lines += "🧠 CortexAgent own-store memory:\n" + cortex_memory
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
