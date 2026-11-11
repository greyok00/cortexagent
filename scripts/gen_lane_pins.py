#!/usr/bin/env python3
"""gen_lane_pins.py — regenerate mcp/lane-pins.json for the locked lane.

Owner 2026-11-10: the locked lanes must (a) never be disable-able and (b)
track the owner's CURRENT greysearch / knowledge-ingestor code. The launcher
syncs the lane sources in (READ-ONLY inbound — sibling trees are never
written) and runs this script, which hashes every code file the lanes run.
locked-mcp.ts refuses to spawn without this file and refuses per-file on a
hash mismatch, so a swapped or vandalized file yields a loud probe, never a
silent absence.
"""
from __future__ import annotations
import hashlib, json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = {
    "mcp/greysearch": ["*.py"],
    "mcp/kbserver": ["*.py"],
    "mcp": ["run_server.py", "memory.cpython-313-x86_64-linux-gnu.so",
            "db.cpython-313-x86_64-linux-gnu.so",
            "research.cpython-313-x86_64-linux-gnu.so"],
    "mcp/lib": ["memory_readers.py"],
}

def main() -> int:
    pins: dict[str, str] = {}
    for base, patterns in TARGETS.items():
        for pat in patterns:
            d = os.path.join(REPO, base)
            if pat == "*" or "*" in pat:
                import glob
                hits = sorted(glob.glob(os.path.join(d, pat)))
            else:
                hits = [os.path.join(d, pat)]
            for f in hits:
                rel = os.path.relpath(f, REPO)
                if os.path.isfile(f):
                    pins[rel] = hashlib.sha256(open(f, "rb").read()).hexdigest()
    out = os.path.join(REPO, "mcp", "lane-pins.json")
    json.dump({"generated_by": "scripts/gen_lane_pins.py",
               "note": "locked-lane integrity pins; regenerate after lane edits",
               "pins": pins}, open(out, "w"), indent=1, sort_keys=True)
    print("lane-pins.json:", len(pins), "files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
