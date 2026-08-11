"""
memory_thin.py — thinned CortexAgent memory wrapper.

Thin shell over ~/.cortexllm/scripts/save-context.py + the daemon socket.
The CortexAgent side does NOT need the full MCP server, skill, or ontology
tooling — just hot append + warm mirror + cold write + read/search.

HARD RULE (2026-08-11): no caps. Every prompt appends to hot and is mirrored
to warm. Warm is the cross-session buffer the engine was designed for.

DROPPED 2026-08-11 (post-cortexllm v0.4.0): the local `_atomic_append` is now
`from cortexllm.atomic import atomic_append`. POSIX-atomic O_APPEND ≤ PIPE_BUF
(4096B) on Linux. The local copy was a verbatim duplicate of the public API.
"""
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# Re-export the drop-in so internal callers can keep using the underscore name.
try:
    from cortexllm.atomic import atomic_append as _atomic_append  # noqa: F401
except ImportError:
    # cortexllm not installed / vendored fallback missing — provide a local
    # POSIX-only atomic append (kept here so the wrapper degrades gracefully).
    def _atomic_append(file_path, line):  # type: ignore[no-redef]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(file_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

# Resolve CortexLLM paths (mirrors lib/config.py get cortexllm_*)
_HOME = Path.home()
CORTEXLLM_DIR = _HOME / ".config/cortexllm"
HOT_DIR = CORTEXLLM_DIR / "memory/hot"
WARM_DIR = CORTEXLLM_DIR / "memory/warm"
COLD_DIR = CORTEXLLM_DIR / "memory/cold"
DAEMON_SOCKET = _HOME / ".cortexllm" / "memory.sock"
SAVE_SCRIPT = _HOME / ".cortexllm" / "scripts" / "save-context.py"
ENTERPRISE_DB = CORTEXLLM_DIR / "cortexllm.db"


def _now_ts() -> str:
    """ISO-ish timestamp matching the engine's format."""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _try_daemon(role: str, content: str, platform: str, **meta) -> bool:
    """Send one write via the daemon socket. Fast path. Returns True on success."""
    if not DAEMON_SOCKET.exists():
        return False
    payload = json.dumps(
        {"role": role, "content": content, "platform": platform, "metadata": meta},
        ensure_ascii=False,
    ) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(DAEMON_SOCKET))
            s.sendall(payload.encode("utf-8"))
        return True
    except (OSError, socket.error):
        return False


def _direct_write(role: str, content: str, platform: str, tiers: Tuple[str, ...] = ("hot", "warm")) -> bool:
    """Append to hot NDJSON + warm NDJSON directly. No caps, no SQL."""
    message = {"role": role, "content": content, "timestamp": _now_ts()}
    line = json.dumps(message, ensure_ascii=False) + "\n"
    if "hot" in tiers:
        _atomic_append(HOT_DIR / f"{platform}.jsonl", line)
    if "warm" in tiers:
        _atomic_append(WARM_DIR / f"{platform}.warm.jsonl", line)
    return True


def append(role: str, content: str, *, platform: str = "cortexagent", **meta) -> Path:
    """Atomic append to hot+warm. Daemon first, direct fallback.

    Returns the path of the hot file written to (for callers that want to
    tail it). Never raises — memory failures are non-fatal by design.
    """
    if _try_daemon(role, content, platform, **meta):
        return HOT_DIR / f"{platform}.jsonl"
    _direct_write(role, content, platform)
    return HOT_DIR / f"{platform}.jsonl"


def read_last(n: int = 5, *, platform: str = "cortexagent") -> List[Dict]:
    """Tail-read hot, return last N entries as dictionaries."""
    hot_file = HOT_DIR / f"{platform}.jsonl"
    if not hot_file.exists():
        return []
    try:
        # Read last ~8KB — enough for ~50 short messages.
        size = hot_file.stat().st_size
        with open(hot_file, "rb") as f:
            f.seek(max(0, size - 8192))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [l for l in tail.split("\n") if l.strip()][-n:]
        return [json.loads(l) for l in lines]
    except (OSError, ValueError):
        return []


def search(query: str, *, tier: str = "hot", platform: str = "cortexagent",
           limit: int = 10) -> List[Dict]:
    """Linear keyword scan across the tier. Fast enough for working sets.

    Returns list of {role, content, timestamp, line_no} matches.
    """
    if not query:
        return []
    q = query.lower()
    path = (HOT_DIR if tier == "hot" else WARM_DIR) / f"{platform}.{'' if tier == 'hot' else 'warm.'}jsonl"
    if not path.exists():
        return []
    matches = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if q in line.lower():
                    try:
                        entry = json.loads(line)
                        entry["line_no"] = i
                        matches.append(entry)
                        if len(matches) >= limit:
                            break
                    except ValueError:
                        continue
    except OSError:
        pass
    return matches


def write_cold(category: str, knowledge: Dict, *, source: str = "cortexagent") -> Path:
    """Write a single curated fact to cold/<category>.json. Atomic (tmp+rename)."""
    import tempfile
    path = COLD_DIR / f"{category}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                data = {"category": category, "entries": []}
        except (OSError, ValueError):
            data = {"category": category, "entries": []}
    else:
        data = {"category": category, "entries": []}
    if "entries" not in data:
        data["entries"] = []
    data["entries"].append({
        "timestamp": _now_ts(),
        "source": source,
        "knowledge": knowledge,
    })
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cold-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def cold_list() -> List[str]:
    """List cold category files."""
    if not COLD_DIR.exists():
        return []
    return sorted(p.stem for p in COLD_DIR.glob("*.json"))


def cold_get(category: str) -> Dict:
    """Read a cold category file."""
    path = COLD_DIR / f"{category}.json"
    if not path.exists():
        return {"category": category, "entries": []}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"category": category, "entries": []}


# ─── CLI for direct invocation ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Thin CortexAgent memory wrapper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("content")
    a.add_argument("--role", "-r", default="user")
    a.add_argument("--platform", "-p", default="cortexagent")
    a = sub.add_parser("read")
    a.add_argument("--n", type=int, default=5)
    a.add_argument("--platform", "-p", default="cortexagent")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--tier", default="hot", choices=["hot", "warm"])
    s.add_argument("--platform", "-p", default="cortexagent")
    s.add_argument("--limit", type=int, default=10)
    c = sub.add_parser("cold")
    c.add_argument("category")
    c.add_argument("knowledge_json")
    args = ap.parse_args()
    if args.cmd == "append":
        print(append(args.role, args.content, platform=args.platform))
    elif args.cmd == "read":
        for entry in read_last(args.n, platform=args.platform):
            print(json.dumps(entry, ensure_ascii=False))
    elif args.cmd == "search":
        for entry in search(args.query, tier=args.tier, platform=args.platform, limit=args.limit):
            print(json.dumps(entry, ensure_ascii=False))
    elif args.cmd == "cold":
        print(write_cold(args.category, json.loads(args.knowledge_json)))
