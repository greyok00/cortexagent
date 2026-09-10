
import json
import os
import socket
import time
from pathlib import Path
from typing import List, Dict

try:
    from slimtoken.memory.atomic import atomic_append as _atomic_append
except ImportError:
    def _atomic_append(file_path, line):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(file_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)


_HOME = Path.home()
CORTEXLLM_DIR = _HOME / ".config/cortexllm"

HOT_FILE = CORTEXLLM_DIR / "memory" / "hot" / "cortexagent.jsonl"
COLD_FILE = CORTEXLLM_DIR / "memory" / "cold" / "cortexagent.jsonl"
DAEMON_SOCKET = _HOME / ".cortexllm" / "memory.sock"


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _try_daemon(message: dict) -> bool:

    if not DAEMON_SOCKET.exists():
        return False
    try:
        payload = json.dumps({
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "platform": "cortexagent",
            "metadata": {k: v for k, v in message.items()
                         if k not in ("role", "content", "timestamp")},
        }, ensure_ascii=False) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(DAEMON_SOCKET))
            s.sendall(payload.encode("utf-8"))
        return True
    except (OSError, socket.error):
        return False


def append(content: str, role: str = "user", *, session: str = "cortexagent",
           session_status: str = None, **meta) -> Path:

    message = {"role": role, "content": content, "timestamp": _now_ts(), **meta}
    line = json.dumps(message, ensure_ascii=False) + "\n"


    if session_status:
        try:
            from lib.session_coordinator import get_coordinator
            coord = get_coordinator(session)
            coord.broadcast(status=session_status, task=content[:80])
        except Exception:
            pass

    if _try_daemon(message):
        return HOT_FILE
    HOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_append(HOT_FILE, line)
    return HOT_FILE


def read_last(n: int = 5) -> List[Dict]:

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




def search(query: str, limit: int = 10) -> List[Dict]:

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

    entry = {"timestamp": _now_ts(), "content": content, **meta}
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    COLD_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_append(COLD_FILE, line)
    return COLD_FILE


def read_cold() -> List[Dict]:

    if not COLD_FILE.exists():
        return []
    try:
        return [json.loads(l) for l in COLD_FILE.read_text().strip().split("\n") if l.strip()]
    except (OSError, ValueError):
        return []


def cold_list() -> List[str]:

    return [f"{e['timestamp']}: {e.get('content', '')[:40]}" for e in read_cold()]



def check_sessions() -> dict:

    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return {"sessions": coord.poll(), "summary": coord.summarize_activity()}
    except Exception as e:
        return {"error": str(e), "sessions": []}


def log_awareness(message: str, level: str = "info") -> dict:

    try:
        from lib.session_coordinator import get_coordinator
        coord = get_coordinator("cortexagent")
        return coord.log_awareness(message, level)
    except Exception as e:
        return {"error": str(e)}



if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Single-session memory wrapper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append")
    a.add_argument("content")
    a.add_argument("--role", "-r", default="user")
    a.add_argument("--session-status", "-s", default=None)

    r = sub.add_parser("read")
    r.add_argument("--n", type=int, default=5)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)

    c = sub.add_parser("cold")
    c.add_argument("content")

    sub.add_parser("sessions")




    args = ap.parse_args()
    if args.cmd == "append":
        print(append(args.content, role=args.role, session_status=args.session_status))
    elif args.cmd == "read":
        for entry in read_last(args.n):
            print(json.dumps(entry, ensure_ascii=False))
    elif args.cmd == "search":
        for entry in search(args.query, limit=args.limit):
            print(json.dumps(entry, ensure_ascii=False))
    elif args.cmd == "cold":
        print(write_cold(args.content))
    elif args.cmd == "sessions":
        print(json.dumps(check_sessions(), indent=2, ensure_ascii=False))
