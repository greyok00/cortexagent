#!/usr/bin/env python3
"""session_bridge — shared-file bridge between TUI, webui, and overseer.

A JSONL log shared between processes. Writes are atomic appends under an
exclusive file lock (`flock`) so multiple writers (webui, TUI, overseer)
can't interleave or clobber each other. Reads use a per-origin cursor
(line index) to deliver only lines the caller hasn't seen.

Usage:
    bridge = SessionBridge()
    bridge.write("webui", {"type": "message", "content": "hello"})
    for ev in bridge.read_new("tui"):
        ...

Concurrency:
    - Writes take an exclusive flock on a lock sidecar file in the same dir,
      then `O_APPEND` the line. POSIX guarantees O_APPEND writes are atomic
      on local filesystems for sizes ≤ PIPE_BUF (4096B); our JSON lines
      are <2 KB so the line lands intact.
    - Reads open the log read-only, snap the cursor at file open, then
      parse new lines. No writer lock needed for reads.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

_DEFAULT_PATH = Path.home() / ".cortexagent" / "state" / "webui_session.jsonl"


class SessionBridge:
    """Append-only JSONL bridge shared between TUI, webui, and overseer."""

    def __init__(self, path: Optional[Path] = None):
        self._path = (path or _DEFAULT_PATH).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("", encoding="utf-8")
        # Sidecar lock file for cross-process append serialization.
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        if not self._lock_path.exists():
            self._lock_path.write_text("", encoding="utf-8")
        # Per-origin last-read cursor (line index).
        self._last_seq: Dict[str, int] = {}

    def write(self, origin: str, event: Dict) -> None:
        """Atomically append one event under flock. origin is a free string
        ('webui', 'tui', 'overseer', 'big', …) — the multi-agent session
        passes different origins to distinguish voices in the same log."""
        line = json.dumps({
            "id": event.get("id", ""),
            "from": origin,
            "type": event.get("type", "message"),
            "username": event.get("username", ""),
            "content": event.get("content", ""),
            "ts": event.get("ts", ""),
            "seq": int(event.get("seq", 0) or 0),
        }, separators=(",", ":")) + "\n"
        try:
            lf = open(self._lock_path, "r+", encoding="utf-8")
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    af = open(self._path, "a", encoding="utf-8")
                    try:
                        af.write(line)
                        af.flush()
                        os.fsync(af.fileno())
                    finally:
                        af.close()
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            finally:
                lf.close()
        except Exception:
            # Last-resort fallback (no locking) — best effort.
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def read_new(self, origin: Optional[str] = None) -> list[Dict]:
        """Return events since the last read. If `origin` is given, filter
        to events whose `from` matches (events written by *other* origins
        are skipped but their cursor is still advanced). If `origin` is
        None, return every new event regardless of author."""
        if origin is not None and origin not in self._last_seq:
            self._last_seq[origin] = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return []
        except Exception:
            return []
        if origin is None:
            start = 0
        else:
            start = self._last_seq[origin]
        new = []
        for line in lines[start:]:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if origin is None or ev.get("from") == origin:
                new.append(ev)
        if origin is not None:
            self._last_seq[origin] = len(lines)
        else:
            # No origin filter — advance every known cursor.
            for k in list(self._last_seq.keys()):
                self._last_seq[k] = len(lines)
        return new

    def tail(self, n: int = 50) -> list[Dict]:
        """Return the last N events regardless of origin (for /api/chat
        initial render)."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            return []
        out = []
        for line in lines[-n:]:
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def mark_read(self, origin: str, seq: int) -> None:
        """Advance the per-origin cursor so read_new skips up to seq."""
        self._last_seq[origin] = max(self._last_seq.get(origin, 0), seq)