"""
memory_thin.py — Single-session memory wrapper for CortexAgent.

No tiers. No caps. Single linear history + cold facts.

The hot layer is the active conversation buffer (NDJSON, no limit).
The cold layer stores persistent knowledge facts (NDJSON, no limit).
Warm was for cross-session merging — removed for single-session use.
"""
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple

try:
    from cortexllm.atomic import atomic_append as _atomic_append
except ImportError:
    def _atomic_append(file_path, line):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(file_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

# Paths
_HOME = Path.home()
CORTEXLLM_DIR = _HOME / ".config/cortexllm"
# Actual hot/cold paths used by the daemon (single-session, no per-profile)
HOT_FILE = CORTEXLLM_DIR / "memory" / "hot" / "cortexagent.jsonl"
COLD_FILE = CORTEXLLM_DIR / "memory" / "cold" / "cortexagent.jsonl"
DAEMON_SOCKET = _HOME / ".cortexllm" / "memory.sock"
ENTERPRISE_DB = CORTEXLLM_DIR / "cortexllm.db"


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _try_daemon(content: str) -> bool:
    """Try writing via daemon socket."""
    if not DAEMON_SOCKET.exists():
        return False
    try:
        payload = json.dumps({"content": content}, ensure_ascii=False) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(DAEMON_SOCKET))
            s.sendall(payload.encode("utf-8"))
        return True
    except (OSError, socket.error):
        return False


def append(content: str, role: str = "user", *, session: str = "cortexagent",
           session_status: str = None, **meta) -> Path:
    """Append to single-session hot memory. No cap, no tier.

    Daemon first, direct fallback. Includes session awareness if session_status set.
    """
    message = {"role": role, "content": content, "timestamp": _now_ts(), **meta}
    line = json.dumps(message, ensure_ascii=False) + "\n"

    # Optional: broadcast session status for inter-session awareness
    if session_status:
        try:
            from lib.session_coordinator import get_coordinator
            coord = get_coordinator(session)
            coord.broadcast(status=session_status, task=content[:80])
        except Exception:
            pass  # Non-fatal, session awareness is optional

    if _try_daemon(line):
        return HOT_FILE
    HOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_append(HOT_FILE, line)
    return HOT_FILE


def read_last(n: int = 5) -> List[Dict]:
    """Read last N entries from hot memory."""
    if not HOT_FILE.exists():
        return []
    try:
        size = HOT_FILE.stat().st_size
        with open(HOT_FILE, "rb") as f:
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [l for l in tail.split("\n") if l.strip()][-n:]
        return [json.loads(l) for l in lines]
    except (OSError, ValueError):
        return []


def read_all() -> List[Dict]:
    """Read all entries from hot memory (no cap)."""
    if not HOT_FILE.exists():
        return []
    try:
        return [json.loads(l) for l in HOT_FILE.read_text().strip().split("\n") if l.strip()]
    except (OSError, ValueError):
        return []


def search(query: str, limit: int = 10) -> List[Dict]:
    """Linear keyword search across hot memory."""
    if not query or not HOT_FILE.exists():
        return []
    q = query.lower()
    matches = []
    try:
        for i, line in enumerate(HOT_FILE.read_text().split("\n"), 1):
            if not line.strip():
                continue
            if q in line.lower():
                entry = json.loads(line)
                entry["line_no"] = i
                matches.append(entry)
                if len(matches) >= limit:
                    break
    except Exception:
        pass
    return matches


def write_cold(content: str, **meta) -> Path:
    """Append a cold knowledge fact. No cap."""
    entry = {"timestamp": _now_ts(), "content": content, **meta}
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    COLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_append(COLD_FILE, line)
    return COLD_FILE


def read_cold() -> List[Dict]:
    """Read all cold facts."""
    if not COLD_FILE.exists():
        return []
    try:
        return [json.loads(l) for l in COLD_FILE.read_text().strip().split("\n") if l.strip()]
    except (OSError, ValueError):
        return []


def cold_list() -> List[str]:
    """List cold entry keys/timestamps."""
    return [f"{e['timestamp']}: {e.get('content', '')[:40]}" for e in read_cold()]


# ─── Session Awareness ────────────────────────────────────────────────────
def check_sessions() -> dict:
    """Check what other sessions are doing. Returns session status dict."""
    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return {"sessions": coord.poll(), "summary": coord.summarize_activity()}
    except Exception as e:
        return {"error": str(e), "sessions": []}


def log_awareness(message: str, level: str = "info") -> dict:
    """Log inter-session awareness to hot memory."""
    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return coord.log_awareness(message, level)
    except Exception as e:
        return {"error": str(e)}


# ─── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Single-session memory wrapper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append")
    a.add_argument("content")
    a.add_argument("--role", "-r", default="user")
    a.add_argument("--session-status", "-s", default=None)
    args = ap.parse_args()
    if args.cmd == "append":
        print(append(args.content, role=args.role, session_status=args.session_status))

    r = sub.add_parser("read")
    r.add_argument("--n", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "read":
        for entry in read_last(args.n):
            print(json.dumps(entry, ensure_ascii=False))

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    if args.cmd == "search":
        for entry in search(args.query, limit=args.limit):
            print(json.dumps(entry, ensure_ascii=False))

    c = sub.add_parser("cold")
    c.add_argument("content")
    args = ap.parse_args()
    if args.cmd == "cold":
        print(write_cold(args.content))

    p = sub.add_parser("sessions")
    args = ap.parse_args()
    if args.cmd == "sessions":
        print(json.dumps(check_sessions(), indent=2, ensure_ascii=False))
