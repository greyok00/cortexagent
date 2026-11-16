#!/usr/bin/env python3
import pathlib, subprocess, sys

ALERT = pathlib.Path.home() / "security-hardening" / "alert-send.py"

if __name__ == "__main__":
    # Declared dependency check instead of a raw traceback.
    if not ALERT.exists():
        print(f"FAIL: text not sent — dependency missing: {ALERT} "
              f"(alert-send lane; declared optional in install.sh)")
        sys.exit(1)
    args = [a for a in sys.argv[1:]]
    img = None
    if "--image" in args:
        i = args.index("--image")
        img = args[i + 1]
        args = args[:i] + args[i + 2:]
    msg = " ".join(args)
    cmd = ["python3", str(ALERT), "gv", msg] + ([img] if img else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr)
    ok = "OK" in out and "FAIL" not in out
    print(f"{'OK' if ok else 'FAIL'}: text {'sent' if ok else 'not sent'} — {out.strip()[-80:]}")
    sys.exit(0 if ok else 1)
