#!/usr/bin/env python3

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Dict, Optional

_DEFAULT_PATH = Path.home() / ".cortexagent" / "state" / "session_bridge.jsonl"


class SessionBridge:


    def __init__(self, path: Optional[Path] = None):
        self._path = (path or _DEFAULT_PATH).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("", encoding="utf-8")

        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        if not self._lock_path.exists():
            self._lock_path.write_text("", encoding="utf-8")

        self._last_seq: Dict[str, int] = {}

    def write(self, origin: str, event: Dict) -> None:

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

            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def read_new(self, origin: Optional[str] = None) -> list[Dict]:

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

            for k in list(self._last_seq.keys()):
                self._last_seq[k] = len(lines)
        return new

    def tail(self, n: int = 50) -> list[Dict]:

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

        self._last_seq[origin] = max(self._last_seq.get(origin, 0), seq)