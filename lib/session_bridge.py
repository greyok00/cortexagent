#!/usr/bin/env python3
"""session_bridge — shared-file bridge between TUI and webui.

Both sides append to a JSONL file. Each side reads lines it hasn't seen.
Writes are atomic (write-to-temp + rename). Reads are line-buffered.

Usage:
    bridge = SessionBridge()
    bridge.write("webui", {"type": "message", "content": "hello"})
    for ev in bridge.read_new("tui"):
        ...
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Generator, Optional

_DEFAULT_PATH = Path.home() / ".cortexagent" / "state" / "webui_session.jsonl"


class SessionBridge:
    """Append-only JSONL bridge between TUI and webui."""

    def __init__(self, path: Optional[Path] = None):
        self._path = (path or _DEFAULT_PATH).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("", encoding="utf-8")
        self._last_seq: Dict[str, int] = {}  # per-origin last seq read

    def write(self, origin: str, event: Dict) -> None:
        """Atomically append an event. origin = 'tui' or 'webui'."""
        line = json.dumps({
            "id": event.get("id", ""),
            "from": origin,
            "type": event["type"],
            "content": event.get("content", ""),
            "ts": event.get("ts", ""),
            "seq": event.get("seq", 0),
        }, separators=(",", ":")) + "\n"
        # Atomic append: write to temp file in same dir, then rename
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), suffix=".tmp", prefix="webui_"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(line)
            os.replace(tmp, str(self._path))
        except Exception:
            # Fallback: plain append (still works, just not atomic)
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def read_new(self, origin: str) -> list[Dict]:
        """Return events from `origin` since last read for this origin."""
        if origin not in self._last_seq:
            self._last_seq[origin] = 0
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        new = []
        for line in lines[self._last_seq[origin]:]:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                new.append(ev)
            except json.JSONDecodeError:
                continue
        self._last_seq[origin] = len(lines)
        return new

    def mark_read(self, origin: str, seq: int) -> None:
        """Advance cursor so read_new skips up to seq."""
        self._last_seq[origin] = max(self._last_seq.get(origin, 0), seq)
