"""Shared pytest fixtures + a reaper for leaked `about:blank` tabs.

The live stealth tests open real `about:blank` tabs (the `fresh_tab` fixture)
and close them when the run finishes cleanly. When a run is interrupted
(KeyboardInterrupt, a timeout kill, a hard crash), the fixture's generator
finalizer never runs and the blank tabs stay in the browser tab strip — the
"about blink" tabs that accumulate across interrupted suites.

This module installs an `atexit` reaper as a backstop: at process exit it asks
the live CDP endpoint to close every page tab whose URL is exactly
`about:blank`. Real tabs (any navigated URL) are never touched. The reaper is
best-effort and silent on failure (no CDP / already closed / etc.).
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "lib")):
    if p not in sys.path:
        sys.path.insert(0, p)

CDP_HTTP = "http://127.0.0.1:9222"


def _reap_blank_tabs() -> None:
    """Close any leftover `about:blank` page tabs via the CDP HTTP endpoint."""
    try:
        with urllib.request.urlopen(CDP_HTTP + "/json", timeout=2) as r:
            tabs = json.load(r)
    except Exception:
        return  # CDP not reachable — nothing to reap.
    for t in tabs:
        if t.get("type") == "page" and t.get("url") == "about:blank":
            tid = t.get("id")
            if not tid:
                continue
            try:
                urllib.request.urlopen(
                    CDP_HTTP + "/json/close/" + urllib.parse.quote(tid), timeout=3
                ).read()
            except Exception:
                pass


atexit.register(_reap_blank_tabs)