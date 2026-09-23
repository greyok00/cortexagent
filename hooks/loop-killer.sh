#!/usr/bin/env bash
set -uo pipefail

INPUT=$(cat /dev/stdin 2>/dev/null || echo "")
[ -z "$INPUT" ] && exit 0

TRANSCRIPT=$(echo "$INPUT" | python3 -c "
import sys, json
try: print(json.load(sys.stdin).get('transcript_path','') or '')
except: print('')
" 2>/dev/null)
[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0

HITS=$(tail -n 40 "$TRANSCRIPT" 2>/dev/null | grep -c 'Connection error' || true)
if [ "${HITS:-0}" -ge 4 ]; then
    PPID_CLAUDE=$PPID
    if readlink /proc/$PPID_CLAUDE/exe 2>/dev/null | grep -q node; then
        echo "loop-killer: $HITS connection errors in last 40 lines — killing stuck claude PID $PPID_CLAUDE" >&2
        kill -9 "$PPID_CLAUDE" 2>/dev/null || true
    fi
fi
exit 0
