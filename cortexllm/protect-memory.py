#!/usr/bin/env python3
"""Memory protection: caps hot memory to prevent lockups.
Triggered by cron. Caps each hot file at 200 messages max.
Also caps warm memory at 300 messages."""
import json, os, sys

memory_root = os.path.expanduser("~/.config/cortexllm/memory")
hot_dir = os.path.join(memory_root, "hot")
warm_file = os.path.join(memory_root, "warm", "per_profile.json")

capped = 0
if os.path.isdir(hot_dir):
    for fname in os.listdir(hot_dir):
        fpath = os.path.join(hot_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        if isinstance(data, dict):
            msgs = data.get("messages", [])
            if len(msgs) > 200:
                data["messages"] = msgs[-200:]
                with open(fpath, "w") as f:
                    json.dump(data, f)
                capped += 1
        elif isinstance(data, list):
            if len(data) > 200:
                data = data[-200:]
                with open(fpath, "w") as f:
                    json.dump(data, f)
                capped += 1

# Cap warm memory too
if os.path.isfile(warm_file):
    try:
        with open(warm_file) as f:
            data = json.load(f)
        msgs = data.get("messages", [])
        if len(msgs) > 500:
            data["messages"] = msgs[-500:]
            with open(warm_file, "w") as f:
                json.dump(data, f)
            capped += 1
    except (json.JSONDecodeError, IOError):
        pass

if capped:
    print(f"Memory protection: capped {capped} file(s)")
else:
    print("Memory protection: all within limits")
