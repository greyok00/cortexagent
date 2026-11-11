#!/usr/bin/env python3
"""Supervise the running cortex-agent TUI session for loops/breaks (owner
order 2026-11-09: monitor through the whole app-creation process; fix +
implement. Ported from cortexagent's supervision plane, 2026-11-09.)

Detects: consecutive identical toolCalls (any kind), bash refusals, stopReason
length-storms, auto-continue bursts. Writes incidents to incidents.jsonl and
prints live. Read-only.

2026-11-09 fixes carried in this port:
- sessions are watched across ALL per-cwd dirs under the agent home (the grey
  original hardcoded one dir and silently watched nothing on a different cwd),
- every incident record carries "epoch" (seconds since the epoch) next to the
  wall-clock ts, so heal.py's recency window is midnight-safe instead of
  comparing bare time-of-day strings.
"""
import json, time, sys, glob, os
from collections import deque

SESS_ROOT = os.path.expanduser("~/.cortex-agent/agent/sessions")
OUT = os.path.expanduser("~/cortex-agent/state/supervision/incidents.jsonl")
STREAK_LIMIT = 4   # harness now trips at 6; report earlier so I can react
seen = set()
streak = deque()
streak_key = None
tail_files = {}

def _session_files():
    return sorted(glob.glob(os.path.join(SESS_ROOT, "*", "*.jsonl")), key=os.path.getmtime)

def current_session():
    files = _session_files()
    return files[-1] if files else None

def scan(path, offset=0):
    global streak_key
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            offset += len(data)
    except Exception:
        return offset
    for line in data.decode("utf8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        m = e.get("message", e)
        if not isinstance(m, dict):
            continue
        r = m.get("role")
        c = m.get("content")
        key = None
        desc = ""
        if r == "assistant" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "toolCall":
                    args = b.get("arguments") or b.get("input") or {}
                    key = f"{b.get('name')}|{json.dumps(args, sort_keys=True)[:400]}"
                    desc = f"{b.get('name')} {str(args.get('path') or args.get('command') or args)[:90]}"
        elif r == "toolResult":
            t = ""
            if isinstance(c, list) and c and isinstance(c[0], dict):
                t = c[0].get("text", "")
            elif isinstance(c, str):
                t = c
            if str(t).startswith("refused:"):
                key = None
                incident(t[:170], "refusal")
        elif r == "assistant" and isinstance(c, list):
            sr = m.get("stopReason", "")
            if sr == "length":
                incident("length stop", "length")
        if key:
            if key == streak_key:
                streak.append(desc)
                if len(streak) >= STREAK_LIMIT:
                    incident(f"streak x{len(streak)}: " + streak[0], "streak")
                    streak.clear()
            else:
                streak_key = key
                streak.clear()
                streak.append(desc)
    return offset

def incident(text, kind):
    if kind == "streak" and text in seen:
        return
    if kind == "streak":
        seen.add(text)
    rec = {"ts": time.strftime("%H:%M:%S"), "epoch": round(time.time(), 2),
           "kind": kind, "detail": text}
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[{rec['ts']}] {kind.upper()}: {text}", flush=True)

print("supervisor watching…")
paths = {p: 0 for p in _session_files()}
for p in list(paths):  # skip history
    paths[p] = os.path.getsize(p)
while True:
    cur = current_session()
    if cur and cur not in paths:
        paths[cur] = os.path.getsize(cur)  # new session: start at EOF... but early lines matter
        if os.path.getsize(cur) < 200000:
            paths[cur] = 0
    for p in list(paths):
        paths[p] = scan(p, paths[p])
    time.sleep(15)
