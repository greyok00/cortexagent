#!/usr/bin/env python3
"""
Memory Daemon — persistent Unix-socket server for hot memory appends.

One instance per memory store. Stores are fully independent:

    cortexagent (local):  --store ~/.cortexagent/memory         --socket ~/.cortexagent/memory.sock
    cortexagent:      --store ~/.cortexagent/memory --socket ~/.cortexagent/memory.sock

Protocol: newline-delimited JSON on the socket
    {"role": "user", "content": "...", "platform": "...", "metadata": {...}}

Writes <store>/hot/<platform>.jsonl (atomic O_APPEND). Hot + cold only:
no warm tier, no SQLite, no vector index. Writes its own pidfile at
<store>/daemon.pid and removes it (plus <socket>) on shutdown.
"""

import argparse
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class MemoryDaemon:
    def __init__(self, store: Path, socket_path: Path, name: str):
        # TEMPORARILY DISABLE SESSION-SPECIFIC STORAGE TO TEST BASIC FUNCTIONALITY
        # Check for session ID to make store session-specific
        # session_id = os.environ.get("CORTEXAGENT_SESSION_ID")
        # if session_id:
        #     # Create session-specific directory: <store>/sessions/<session-id>/
        #     self.store = store / "sessions" / session_id
        # else:
        #     self.store = store
        self.store = store

        self.socket_path = socket_path
        self.name = name
        self.pidfile = self.store / "daemon.pid"
        self.log = self.store / "daemon.log"
        self.store.mkdir(parents=True, exist_ok=True)
        (self.store / "hot").mkdir(parents=True, exist_ok=True)
        (self.store / "cold").mkdir(parents=True, exist_ok=True)

    def _logmsg(self, msg: str):
        try:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(f"[{_now()}] [{self.name} pid={os.getpid()}] {msg}\n")
        except OSError:
            pass

    def _append(self, platform: str, msg: dict):
        hot = self.store / "hot" / f"{platform}.jsonl"
        hot.parent.mkdir(parents=True, exist_ok=True)
        entry = {"role": msg.get("role", "user"),
                 "content": msg.get("content", ""),
                 "timestamp": _now()}
        if msg.get("metadata"):
            entry["metadata"] = msg.get("metadata")
        line = json.dumps(entry) + "\n"
        try:
            # Use O_APPEND for atomic appends (fsync before close)
            fd = os.open(
                str(hot),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # Last resort: regular write
            with open(hot, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def _stop(self, signum, frame):
        self._logmsg("stopping")
        sys.exit(0)

    def run(self):
        # Single-instance guard: refuse to start if another live daemon owns the store.
        if self.pidfile.exists():
            try:
                old_pid = int(self.pidfile.read_text().strip())
                os.kill(old_pid, 0)
                print(f"[{self.name}] already running as pid {old_pid}", file=sys.stderr)
                sys.exit(1)
            except OSError:
                # pidfile exists but no such process — probably stale
                pass

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

        # Ensure socket directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Create socket
        try:
            os.unlink(self.socket_path)
        except OSError:
            if os.path.exists(self.socket_path):
                raise

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.bind(str(self.socket_path))
            s.listen(16)
            os.chmod(self.socket_path, 0o600)
            self.pidfile.write_text(f"{os.getpid()}\n")
            # bind the socket path into the unit's liveness check
            # a previous run's symlink survives shutdown — replace it, don't die
            # on FileExistsError
            link = self.store / "socket"
            try:
                if link.is_symlink():
                    link.unlink()
            except OSError:
                if link.is_symlink():
                    link.unlink()
            os.symlink(self.socket_path, link)
            self._logmsg(f"started (socket: {self.socket_path})")

            while True:
                conn, _ = s.accept()
                try:
                    # Protocol: one JSON object per connection, read to EOF
                    # with a hard cap (the old single
                    # recv(4096) silently dropped every oversized message),
                    # then an explicit "OK\n"/"ERR …\n" reply.
                    data = b""
                    while len(data) <= 1_048_576:
                        part = conn.recv(65536)
                        if not part:
                            break
                        data += part
                    if not data:
                        reply = b"ERR empty\n"
                    elif len(data) > 1_048_576:
                        reply = b"ERR too-large\n"
                        self._logmsg("dropped: message exceeded 1 MiB cap")
                    else:
                        try:
                            msg = json.loads(data.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            msg = None
                            reply = b"ERR bad-payload\n"
                            self._logmsg("dropped: unparseable payload")
                        if msg is not None:
                            self._append(msg.get("platform", "unknown"), msg)
                            reply = b"OK\n"
                    try:
                        conn.sendall(reply)
                    except OSError:
                        pass
                finally:
                    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Memory daemon (hot NDJSON appender)")
    ap.add_argument("--store", required=True, help="Memory store root, e.g. ~/.cortexagent/memory")
    ap.add_argument("--socket", required=True, help="Unix socket path")
    ap.add_argument("--name", default="memory")
    args = ap.parse_args()
    MemoryDaemon(Path(os.path.expanduser(args.store)),
                 Path(os.path.expanduser(args.socket)),
                 args.name).run()