#!/usr/bin/env python3
import pathlib, subprocess, sys
import json

ALERT = pathlib.Path.home() / "security-hardening" / "alert-send.py"
ALERT_CONFIG = pathlib.Path.home() / "security-hardening" / "alert-config.json"

def _guard() -> str | None:
    # This lane hard-depends on ~/security-hardening. When the
    # helper is absent the caller used to get a raw traceback and nothing
    # else; now it gets a declared dependency failure.
    if not ALERT.exists():
        return (f"dependency missing: {ALERT} (alert-send lane). "
                f"send_text/send_email are optional actions — declared in "
                f"install.sh; install ~/security-hardening to enable.")
    if not ALERT_CONFIG.exists():
        return f"dependency missing: {ALERT_CONFIG} (alert-config.json)"
    try:
        json.load(ALERT_CONFIG.open())
    except Exception as e:
        return f"alert-config.json unparseable: {e}"
    return None

if __name__ == "__main__":
    bad = _guard()
    if bad:
        print(f"FAIL: email not sent — {bad}")
        sys.exit(1)
    args = sys.argv[1:]
    subject = args[0] if args else "from your system"
    body = args[1] if len(args) > 1 else "(empty)"
    r = subprocess.run(["python3", str(ALERT), "email", subject, body],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr)
    ok = "OK" in out and "FAIL" not in out
    print(f"{'OK' if ok else 'FAIL'}: email {'sent' if ok else 'failed'} — {out.strip()[-80:]}")
    sys.exit(0 if ok else 1)
