#!/usr/bin/env python3
"""Event pump (spec §7): tails the LIVE cortexagent session jsonl, converts
messages into supervisor events, enforces via the supervised-steer channel.

Read-only on the session; writes only to the steer file + sidecar stream.
Run as a systemd service (cortex-supervisor.service). Cannot-fail: session
read errors and supervisor exceptions both degrade to observe-only.
"""
from __future__ import annotations
import glob
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import supervisor as supervisor_mod  # noqa: E402

SESS_ROOT = os.path.expanduser("~/.cortex-agent/agent/sessions")


def current_session() -> str | None:
    import glob as g
    files = sorted(g.glob(os.path.join(SESS_ROOT, "*", "*.jsonl")),
                   key=os.path.getmtime)
    return files[-1] if files else None


def _digest(tool: str, args: dict) -> str:
    args_dump = json.dumps(args, sort_keys=True, default=str)
    import detectors
    return detectors._digest(tool, args_dump)


def msg_events(m: dict) -> list[dict]:
    """Convert one session message into 0..n supervisor events."""
    out = []
    role = m.get("role")
    c = m.get("content")
    if not isinstance(c, list):
        return out
    for b in c:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "toolCall":
            tool = b.get("name") or ""
            args = b.get("arguments") or {}
            digest = _digest(tool, args)
            ev = {"kind": "tool_call", "tool": tool, "args": args,
                  "digest": digest}
            # refusal families: the exec-gate/guard text lands in the result,
            # but the CALL itself carries the class for pre-exec accounting.
            out.append(ev)
        elif btype == "text" and role == "assistant":
            txt = b.get("text") or ""
            out.append({"kind": "model_turn", "tokens": len(txt) // 4})
    return out


def result_events(m: dict) -> list[dict]:
    out = []
    c = m.get("content")
    if not isinstance(c, list):
        return out
    for b in c:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            t = b.get("text") or ""
            out.append({"kind": "tool_result", "tool": m.get("toolName") or "tool",
                        "error": "refused" in t.lower(),
                        "result_hash": hashlib.sha1(t.encode()).hexdigest()[:10]})
            if "refused" in t.lower():
                fam = "gate" if "gate" in t.lower() or "allowlist" in t.lower() \
                    else ("guard" if "loop" in t.lower() else "other")
                out.append({"kind": "refusal", "reason_family": fam})
    return out


def main():
    sup = supervisor_mod.Supervisor("live")
    path = current_session()
    if not path:
        print("[pump] no session file yet; exiting cleanly", flush=True)
        return
    print(f"[pump] watching {os.path.basename(path)}", flush=True)
    offset = os.path.getsize(path)  # live-tail from EOF; startup history is watched by watch.py
    seen_ids: set[str] = set()
    while True:
        time.sleep(2)
        try:
            new = current_session()
            if not new:
                continue
            if new != path:
                path, offset = new, os.path.getsize(new)  # session rollover
                sup = supervisor_mod.Supervisor("live")   # BLOCKED→IDLE reset
                print(f"[pump] rollover → {os.path.basename(path)}", flush=True)
            size = os.path.getsize(path)
            if size < offset:
                offset = size
                continue
            if size == offset:
                continue
            with open(path, "rb") as f:
                f.seek(offset)
                chunk = f.read().decode("utf-8", "replace")
                offset = size
            for line in chunk.splitlines():
                line = line.strip()
                if not line or line in seen_ids:
                    continue
                # dedupe on line hash for rotation safety
                hid = hashlib.sha1(line.encode()).hexdigest()[:16]
                if hid in sup.__dict__.get("_seen", set()):
                    continue
                seen_ids.add(hid)
                if len(seen_ids) > 5000:
                    seen_ids.clear()
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "message":
                    continue
                mm = d.get("message", d)
                role = mm.get("role")
                for ev in (msg_events(mm) if role == "assistant"
                           else result_events(mm) if role == "toolResult" else []):
                    sup.on_event(ev)
        except FileNotFoundError:
            continue  # rotation race
        except Exception as e:
            # cannot-fail: log + keep tailing (supervisor degrade is internal)
            print(f"[pump] degraded: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
