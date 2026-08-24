
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

    try:
        with urllib.request.urlopen(CDP_HTTP + "/json", timeout=2) as r:
            tabs = json.load(r)
    except Exception:
        return
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