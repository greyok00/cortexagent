#!/usr/bin/env python3
import subprocess, sys, time, pathlib

CW = str(pathlib.Path.home() / "earnings-stack" / "scripts" / "cw_driver.py")
MD = str(pathlib.Path.home() / "earnings-stack" / "scripts" / "mindrift_driver.py")
LEDGER = str(pathlib.Path.home() / "earnings-stack" / "scripts" / "earnings_ledger.py")

def run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() or (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"

def clickworker():
    out = run(["python3", CW, "board"], 45)
    if "EXPIRED" in out or "LOGIN-NEEDED" in out:
        return "clickworker: session expired — needs manual 2FA login (password is in gnome-keyring)"
    if "no clickworker tab" in out:
        return "clickworker: no tab open in the worker window (open workplace.clickworker.com)"
    if "board text head" in out:
        return f"clickworker: session OK — {out[:160]}"
    return f"clickworker: {out[:160]}"

def mindrift():
    st = run(["python3", MD, "state"], 45)
    if "no annotation-tool tab" in st:
        return ("mindrift: no annotation tab open (label-exhed4afhtahh0b7) — "
                "open a task first, then I can judge/submit")
    return f"mindrift: {st[:160]}"

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        print("OK: script loads, drivers exist:",
              all(pathlib.Path(p).exists() for p in (CW, MD, LEDGER)))
        sys.exit(0)
    lines = [clickworker(), mindrift()]
    stamp = time.strftime("%F %H:%M")
    (pathlib.Path.home() / "earnings-stack" / "last-sweep.txt"
     .write_text(f"{stamp}\n" + "\n".join(lines)))
    print("\n".join(lines))
