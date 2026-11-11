#!/usr/bin/env python3
"""greysearch_cli.py - the `greysearch` command.

`greysearch` (no args) opens the research station: starts the portal
server on 127.0.0.1:8791 (or reuses the one already listening) and points
the default browser at it. Extra subcommands stay thin:

    greysearch              open the station (portal + browser)
    greysearch library      open the library screen directly
    greysearch runs         open the run ledger directly
    greysearch search "q"   run a one-shot search CLI (delegates to research.py)
    greysearch stop         stop the portal server if we started it

Prints the URL. Never blocks the station's own server threads.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HOST = os.environ.get("GREYSEARCH_PORTAL_HOST") or "127.0.0.1"
PORT = int(os.environ.get("GREYSEARCH_PORTAL_PORT") or 8791)
BASE = f"http://{HOST}:{PORT}"


def _alive(timeout=1.2):
    """True when something already serves the portal's /api/latest."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{BASE}/api/latest", timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _start_portal():
    if _alive():
        return None
    exe = Path(sys.executable)
    server_py = Path(__file__).resolve().parent / "portal_server.py"
    proc = subprocess.Popen(
        [str(exe), str(server_py)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    for _ in range(40):
        if _alive():
            return proc
        time.sleep(0.25)
    raise RuntimeError("portal did not come up on " + BASE)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="greysearch",
        description="Greysearch research station: search the web, read the "
                    "sources, keep the library. No args opens the station.")
    ap.add_argument("cmd", nargs="?", default="open",
                    choices=["open", "library", "runs", "search", "stop"])
    ap.add_argument("rest", nargs="*", help="query text for `search`")
    args = ap.parse_args()

    if args.cmd == "stop":
        # gentle: ask the portal process (started by us) to exit via SIGTERM
        out = subprocess.run(["pgrep", "-f", "portal_server.py"],
                             capture_output=True, text=True)
        pids = [p for p in out.stdout.split() if p.strip()]
        for p in pids:
            try:
                os.kill(int(p), 15)
                print(f"greysearch: stopped portal pid {p}")
            except Exception:
                pass
        return 0

    if args.cmd == "search":
        q = " ".join(args.rest).strip()
        if not q:
            print('usage: greysearch search "your question"')
            return 2
        exe = Path(sys.executable)
        research_py = Path(__file__).resolve().parent / "research.py"
        return subprocess.run([str(exe), str(research_py), q]).returncode

    proc = _start_portal()
    if proc:
        print(f"greysearch: portal started (pid {proc.pid})")
    else:
        print("greysearch: portal already running")
    page = {"library": "library.html", "runs": "runs.html"}.get(args.cmd, "")
    url = f"{BASE}/{page}" if page else BASE + "/"
    print("greysearch: opening " + url)
    try:
        webbrowser.open(url)
    except Exception:
        pass  # headless: the URL is printed, user opens it themselves
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
