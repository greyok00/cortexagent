#!/usr/bin/env python3
"""learn_worker.py — one-shot isolated runner for kb_learn_topic.

Runs the greysearch deep research + quality-gated ingest OUTSIDE the
single-threaded knowledge-ingestor stdio server, so a slow web research
can never wedge the MCP lane. Launched by kbserver_patch.tool_kb_learn_topic:

    learn_worker.py <run_dir> <wall_limit_seconds>

Writes <run_dir>/digest.json atomically when done (or failed).
"""
import json
import os
import signal
import sys
import threading
import time

RUN_DIR = sys.argv[1] if len(sys.argv) > 1 else ""
WALL = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0
T0 = time.time()


def _watchdog():
    """Own-process wall-clock fence: kill my whole group at the deadline."""
    time.sleep(WALL)
    digest = os.path.join(RUN_DIR, "digest.json")
    if not os.path.exists(digest):
        try:
            with open(digest + ".tmp", "w") as f:
                json.dump({"state": "failed",
                           "why": f"worker wall-clock self-kill after {int(WALL)}s"}, f)
            os.replace(digest + ".tmp", digest)
        except Exception:
            pass
    try:
        os.killpg(os.getpgrp(), signal.SIGKILL)
    except Exception:
        os._exit(9)


def _write_digest(digest: dict):
    if not RUN_DIR:
        return
    tmp = os.path.join(RUN_DIR, "digest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(digest, f, indent=1, default=str)
    os.replace(tmp, os.path.join(RUN_DIR, "digest.json"))


def main():
    threading.Thread(target=_watchdog, daemon=True).start()
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    req_path = os.path.join(RUN_DIR, "request.json")
    try:
        with open(req_path) as f:
            args = json.load(f)
    except Exception as e:
        _write_digest({"state": "failed", "why": f"unreadable request.json: {e}"})
        return 1

    import kbserver_patch as patch

    try:
        result = patch._learn_now(args)
    except Exception as e:
        _write_digest({"state": "failed",
                       "why": f"{type(e).__name__}: {e}",
                       "elapsed_s": round(time.time() - T0, 1)})
        return 1

    if isinstance(result, dict) and result.get("error"):
        _write_digest({"state": "failed", "why": result["error"],
                       "elapsed_s": round(time.time() - T0, 1)})
        return 1

    result = dict(result)
    result["state"] = "done"
    result["elapsed_s"] = round(time.time() - T0, 1)
    _write_digest(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
