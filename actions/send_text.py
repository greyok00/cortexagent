#!/usr/bin/env python3
import pathlib, subprocess, sys

ALERT = str(pathlib.Path.home() / "security-hardening" / "alert-send.py")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    img = None
    if "--image" in args:
        i = args.index("--image")
        img = args[i + 1]
        args = args[:i] + args[i + 2:]
    msg = " ".join(args)
    cmd = ["python3", ALERT, "gv", msg] + ([img] if img else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr)
    ok = "OK" in out and "FAIL" not in out
    print(f"{'OK' if ok else 'FAIL'}: text {'sent' if ok else 'not sent'} — {out.strip()[-80:]}")
    sys.exit(0 if ok else 1)
