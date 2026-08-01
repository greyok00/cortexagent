#!/bin/bash
set -eu
REPO_ROOT="${CORTEXAGENT_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
. "${REPO_ROOT}/lib/state.sh"

payload="$(cat || true)"
source="$(printf '%s' "$payload" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('source','startup') or 'startup')" 2>/dev/null || echo "startup")"

python3 "$REPO_ROOT/lib/cortexagent_call.py" recent --limit 12 2>/dev/null | python3 -c "
import json, os, sys
recent = sys.stdin.read().strip()
lines = ''
if recent:
    lines = 'Recovered from CortexAgent memory:\n' + recent
else:
    lines = '(No prior CortexAgent memory for this profile yet.)'
source = '$source'
if source == 'compact':
    f = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'cortexagent', 'last-prompt')
    try:
        with open(f) as fh:
            last = fh.read().strip()
        if last:
            lines += '\n\nContext was just compacted. Continue the user\'s last request:\n' + last
    except:
        pass
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': lines}}))
" 2>/dev/null || echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"(No prior CortexAgent memory for this profile yet.)"}}'
exit 0
