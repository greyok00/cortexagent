#!/usr/bin/env python3
"""Single JSONL tail reader for every cortexagent memory lane.

Replaces three copies (memory/mcp_server.py, lib/converted_mcp_tools.py,
lib/memory_thin.py) of the same tail-truncate-and-abort reader: files bigger
than the scan window returned nothing even when complete records were inside
it (the boundary row was parsed as JSON and aborted the whole read), and one
corrupt row discarded every later valid row. Here the window boundary row is
dropped cleanly, corrupt rows are tallied instead of fatal, and the result
states its outcome explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_WINDOW = 1_048_576  # 1 MB tail scan window


def read_jsonl_tail(path, n: int, window_bytes: int = DEFAULT_WINDOW) -> dict:
    """Last ``n`` complete JSONL records, tolerant per row.

    Returns a status object: ``{"status": "ok"|"empty"|"missing"|"corrupt",
    "rows": [...], "dropped": int, "skipped_bytes": int}``.

    - "missing": the file does not exist.
    - "empty": the file exists but holds no complete parseable record within
      the window.
    - "corrupt": rows were present but none parsed (``dropped`` says how many).
    - "ok": otherwise; ``dropped`` may still be > 0 when only some rows
      failed, and ``skipped_bytes`` is the file prefix outside the window.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return {"status": "missing", "rows": [], "dropped": 0, "skipped_bytes": 0}
    if size == 0:
        return {"status": "empty", "rows": [], "dropped": 0, "skipped_bytes": 0}
    n = max(1, int(n))
    window = min(size, max(int(window_bytes), 4096))
    skipped = size - window
    try:
        with path.open("rb") as f:
            if skipped:
                f.seek(skipped)
                f.readline()  # the boundary row is usually partial — drop it
            data = f.read(window + 4096)
    except OSError:
        return {"status": "missing", "rows": [], "dropped": 0, "skipped_bytes": 0}
    rows, dropped = [], 0
    for raw in data.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            dropped += 1
    if rows:
        status, rows = "ok", rows[-n:]
    elif dropped:
        status = "corrupt"
    else:
        status = "empty"
    return {"status": status, "rows": rows, "dropped": dropped,
            "skipped_bytes": skipped}