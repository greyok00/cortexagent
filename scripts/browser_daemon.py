#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE = Path(os.environ.get(
    "COURSE_BROWSER_PROFILE", str(Path.home() / "tmp" / "course-browser-profile")))
PORT = int(os.environ.get("COURSE_BROWSER_PORT", "9335"))


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DISPLAY", ":0")
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            args=[
                f"--remote-debugging-port={PORT}",
                "--no-sandbox",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("about:blank", timeout=30000)
        except Exception:
            pass
        print(f"READY cdp=http://127.0.0.1:{PORT}", flush=True)

        while True:
            time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
