#!/usr/bin/env python3
import glob, os, subprocess, sys, time

DIRS = [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]

def find(query):
    cands = []
    for d in DIRS:
        for f in glob.glob(d + "/**/*", recursive=True):
            if os.path.isfile(f) and query.lower() in os.path.basename(f).lower():
                cands.append(f)
    cands.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return cands[0] if cands else None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: open_pdf.py <name-substring>")
        sys.exit(1)
    path = find(sys.argv[1])
    if not path:
        print(f"FAIL: no file matching '{sys.argv[1]}' in Downloads/Desktop")
        sys.exit(1)
    subprocess.Popen(["env", "DISPLAY=:0", "atril", path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    r = subprocess.run(["pgrep", "-c", "atril"], capture_output=True, text=True)
    running = int(r.stdout.strip() or 0) > 0
    print(f"{'OK' if running else 'FAIL'}: opened {os.path.basename(path)} "
          f"({running} viewer(s) running — all left open)")
    sys.exit(0 if running else 1)
