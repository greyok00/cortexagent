#!/usr/bin/env python3
import json, pathlib, subprocess, sys

ALERT = str(pathlib.Path.home() / "security-hardening" / "alert-send.py")
CFG = json.load(open(pathlib.Path.home() / "security-hardening" / "alert-config.json"))

if __name__ == "__main__":
    args = sys.argv[1:]
    subject = args[0] if args else "from your system"
    body = args[1] if len(args) > 1 else "(empty)"
    r = subprocess.run(["python3", ALERT, "email", subject, body],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr)
    ok = "OK" in out and "FAIL" not in out
    print(f"{'OK' if ok else 'FAIL'}: email {'sent' if ok else 'failed'} — {out.strip()[-80:]}")
    sys.exit(0 if ok else 1)
