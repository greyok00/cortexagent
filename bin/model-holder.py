#!/usr/bin/env python3
"""model-holder.py — live parent for the model server (2026-11-06).

The vendored engine-server carries PR_SET_PDEATHSIG: it dies with the
process that booted it. The TUI session qualifies (stays alive while it
manages the model); an operational restart from outside the TUI needs a
persistent parent instead. This script is that parent: boot the model,
then sleep forever. If this holder is killed, the model dies with it and
the next boot re-runs this script.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build" / "src"))
import server  # noqa: E402

r = server.start_model(timeout=900)
print("boot result:", {k: v for k, v in r.items() if k != "cmd"}, flush=True)
while True:
    time.sleep(3600)
