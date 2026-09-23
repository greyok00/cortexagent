#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys

BUCKET = pathlib.Path(__file__).parent

def registry():
    reg = {}
    for f in sorted(BUCKET.glob("*.py")):
        if f.name in ("run.py", "__init__.py"):
            continue
        doc = (f.read_text(errors="replace").split('"""')[1]
               if f.read_text(errors="replace").count('"""') >= 2 else "")
        reg[f.name[:-3]] = {"path": str(f),
                            "help": doc.strip().splitlines()[0] if doc.strip() else ""}
    return reg

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("list", "--list"):
        print("Offline action bucket — run.py <action> [args]")
        for name, meta in registry().items():
            print(f"  {name:16s} {meta['help']}")
        sys.exit(0)
    action = sys.argv[1]
    reg = registry()
    if action not in reg:
        print(f"FAIL: no action '{action}'. Available: {', '.join(reg)}")
        sys.exit(1)
    r = subprocess.run(["python3", reg[action]["path"], *sys.argv[2:]],
                       timeout=180)
    sys.exit(r.returncode)
