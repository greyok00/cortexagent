#!/usr/bin/env bash

set -euo pipefail

CONFIG="$HOME/.cortexagent/chromium-profile/launcher-config.json"

if ss -ltnp 2>/dev/null | grep -q ":9224 "; then
    echo "Default browser already running on :9224 — attaching to existing session"
    echo "Open any pinned tab in the existing window:"
    for url in $(python3 -c "
import json, sys
cfg = json.load(open('$CONFIG'))
for tab in cfg['pinned_tabs']:
    print(tab['url'])
"); do
        echo "  $url"
    done
    echo "Use: chromium --remote-debugging-port=9225 --existing-profile-dir=... to open a second window"
    exit 0
fi

WIN_POS=$(python3 -c "import json; c=json.load(open('$CONFIG')); p=c['window']['position']; print(f'--window-position={p[0]},{p[1]}')")
WIN_SIZE=$(python3 -c "import json; c=json.load(open('$CONFIG')); s=c['window']['size']; print(f'--window-size={s[0]},{s[1]}')")
if [ -n "${1:-}" ]; then
    WIN_SIZE="--window-size=$1"
fi
PROFILE_DIR=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c['user_data_dir'])")

echo "Launching default browser with profile: $PROFILE_DIR"
nohup /usr/lib/chromium/chromium \
    --remote-debugging-port=9224 \
    --remote-allow-origins=* \
    --no-first-run \
    --show-component-extension-options \
    --enable-gpu-rasterization \
    --no-default-browser-check \
    --disable-pings \
    --media-router=0 \
    --disable-session-crashed-bubble \
    --hide-crash-restore-bubble \
    "$WIN_POS" \
    "$WIN_SIZE" \
    --user-data-dir="$PROFILE_DIR" \
    > "$HOME/.cortexagent/logs/chromium-cdp.log" 2>&1 &

CHROMIUM_PID=$!
echo "Browser PID: $CHROMIUM_PID"

for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:9224/json >/dev/null 2>&1; then
        echo "CDP ready on :9224"
        break
    fi
    sleep 0.5
done

python3 -c "
import json, subprocess, time
cfg = json.load(open('$CONFIG'))
for tab in cfg['pinned_tabs']:
    cmd = ['chromium', '--remote-debugging-port=9224', '--new-window', tab['url']]
    subprocess.run(cmd, capture_output=True)
    time.sleep(1)
" 2>/dev/null || echo "Note: tab opening may need manual follow-up"

echo "Done. Open chromium-relaunch.sh again to check status."
