#!/usr/bin/env python3
"""Durable model watcher: boots the cortexagent model and reboots it if it
dies. server.py is re-imported per process start, so profile edits apply at
each boot/reboot. Runs under a systemd user unit so settings persist."""
import sys, os, time, signal
sys.path.insert(0, os.path.expanduser("~/cortex-agent/build/src"))
os.environ.setdefault("CORTEXENGINE_PORT", "7100")
os.environ.setdefault("CORTEXENGINE_LANE_PORT", "7101")
import server
signal.signal(signal.SIGTERM, lambda *_: (server.stop_model(), os._exit(0)))
d = server.start_model(timeout=600)
print("boot:", {k: d.get(k) for k in ("ok", "ctx", "pid", "error")}, flush=True)
if d.get("ok"):
    while True:
        time.sleep(30)
        if not server.is_ready():
            d2 = server.start_model(timeout=600)
            print("reboot:", d2.get("ok"), d2.get("ctx"), flush=True)
