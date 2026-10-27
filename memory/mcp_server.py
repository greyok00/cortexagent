#!/usr/bin/env python3


from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PLATFORM = os.environ.get("CORTEXAGENT_PLATFORM", "cortexagent")
PROFILE = f"platform:{PLATFORM}"

STORE = Path(os.path.expanduser(os.environ.get(
    "CORTEXAGENT_MEMORY_DIR", "~/.cortexagent/memory")))
HOT_FILE = STORE / "hot" / f"{PLATFORM}.jsonl"
COLD_JSONL = STORE / "cold" / f"{PLATFORM}.jsonl"
COLD_MD = STORE / "cold" / f"{PLATFORM}.md"


def _send_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj,ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_json() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _ok(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _tool(name: str, description: str, params: Dict[str, Any],
          required: List[str]) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": params, "required": required}}


def _append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = path.open("a", encoding="utf-8")
    try:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
    finally:
        fp.close()


def _read_tail(path: Path, n: int) -> List[dict]:
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - min(size, n * 4096)))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [l for l in tail.split("\n") if l.strip()]
        return [json.loads(l) for l in lines[-n:]]
    except (OSError, ValueError):
        return []


def _search_file(path: Path, query: str, limit: int) -> List[dict]:
    if not path.exists():
        return []
    q = query.lower()
    hits: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
            if line.strip() and q in line.lower():
                hits.append(line)
                if len(hits) >= limit:
                    break
    except OSError:
        pass
    out = []
    for h in hits:
        try:
            out.append(json.loads(h))
        except json.JSONDecodeError:
            out.append({"content": h})
    return out


def _cold_jsonl() -> List[dict]:
    if not COLD_JSONL.exists():
        return []
    try:
        return [json.loads(l) for l in COLD_JSONL.read_text().strip().split("\n") if l.strip()]
    except (OSError, ValueError):
        return []


TOOLS = [
    _tool("memory_read", "Read hot or cold memory.", {
        "tier": {"type": "string", "enum": ["hot", "cold"], "description": "Memory tier."},
        "limit": {"type": "number", "description": "Max entries (default 20)."},
    }, ["tier"]),
    _tool("memory_write", "Write to memory. Hot = working buffer (this session's history). Cold = permanent curated fact.", {
        "content": {"type": "string", "description": "Text or fact to save."},
        "tier": {"type": "string", "enum": ["hot", "cold"], "description": "Target tier (default hot)."},
        "role": {"type": "string", "description": "Role for hot entries (default user)."},
    }, ["content"]),
    _tool("memory_search", "Search hot and cold memory. Returns matching entries.", {
        "query": {"type": "string"},
        "limit": {"type": "number", "description": "Max matches (default 10)."},
    }, ["query"]),
    _tool("memory_stats", "Show hot/cold entry counts and file sizes.", {}, []),
    _tool("memory_clear", "Clear hot or cold memory for this platform.", {
        "tier": {"type": "string", "enum": ["hot", "cold"]},
    }, ["tier"]),
]


def _handle_read(args: Dict[str, Any]) -> Dict[str, Any]:
    tier = args.get("tier", "hot")
    limit = int(args.get("limit", 20))
    if tier == "hot":
        rows = _read_tail(HOT_FILE, limit)
    elif tier == "cold":
        rows = _cold_jsonl()
        if COLD_MD.exists():
            md = COLD_MD.read_text(encoding="utf-8", errors="replace")
            rows = rows + [{"content": l} for l in md.split("\n") if l.strip()]
        rows = rows[-limit:]
    else:
        return _err(f"Unknown tier: {tier} (hot + cold only)")
    return _ok(json.dumps(rows, ensure_ascii=False, indent=2))


def _handle_write(args: Dict[str, Any]) -> Dict[str, Any]:
    from time import strftime
    content = args.get("content", "")
    tier = args.get("tier", "hot")
    if not content.strip():
        return _err("empty content")
    entry = {"timestamp": strftime("%Y-%m-%d %H:%M:%S"), "content": content}
    if tier == "cold":
        _append_jsonl(COLD_JSONL, entry)
    elif tier == "hot":
        entry["role"] = args.get("role", "user")
        _append_jsonl(HOT_FILE, entry)
        return _ok(f"saved to hot ({HOT_FILE})")
    else:
        return _err(f"Unknown tier: {tier} (hot + cold only)")
    return _ok(f"saved to cold ({COLD_JSONL})")


def _handle_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query", "")
    limit = int(args.get("limit", 10))
    if not query.strip():
        return _ok("[]")
    out = {"hot": _search_file(HOT_FILE, query, limit),
           "cold": _cold_jsonl() and _search_file(COLD_JSONL, query, limit)}
    return _ok(json.dumps(out, ensure_ascii=False, indent=2))


def _handle_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    def _stat(p: Path):
        return {"path": str(p), "exists": p.exists(),
                "bytes": p.stat().st_size if p.exists() else 0}
    hot_n = sum(1 for _ in HOT_FILE.open("rb")) if HOT_FILE.exists() else 0
    cold_n = len(_cold_jsonl())
    return _ok(json.dumps({
        "platform": PLATFORM, "store": str(STORE),
        "hot": {"entries": hot_n, "file": str(HOT_FILE), "bytes": _stat(HOT_FILE)["bytes"]},
        "cold": {"entries": cold_n, "files": [str(COLD_JSONL), str(COLD_MD)]},
        "tiers": ["hot", "cold"],
    }, ensure_ascii=False, indent=2))


def _handle_clear(args: Dict[str, Any]) -> Dict[str, Any]:
    tier = args.get("tier", "hot")
    if tier == "hot":
        path = HOT_FILE
    elif tier == "cold":
        path = COLD_JSONL
    else:
        return _err(f"Unknown tier: {tier} (hot + cold only)")
    cleared = path.stat().st_size if path.exists() else 0
    if path.exists():
        path.write_text("")
    return _ok(f"cleared {tier} ({cleared} bytes)")


def _dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "memory_read":
        return _handle_read(args)
    if name == "memory_write":
        return _handle_write(args)
    if name == "memory_search":
        return _handle_search(args)
    if name == "memory_stats":
        return _handle_stats(args)
    if name == "memory_clear":
        return _handle_clear(args)
    return _err(f"Unknown tool: {name}")


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": _id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "memory", "version": "2.0"}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": _id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        return {"jsonrpc": "2.0", "id": _id, "result": _dispatch(name, args)}

    return {"jsonrpc": "2.0", "id": _id, "error":
            {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        entry = {"timestamp": "smoke", "content": "memory smoke test", "role": "user"}
        _append_jsonl(HOT_FILE, entry)
        rows = _read_tail(HOT_FILE, 5)
        assert any(r.get("content") == "memory smoke test" for r in rows), rows
        stats = _handle_stats({})
        import json as _j
        print("tools: memory_read, memory_write, memory_search, memory_stats, memory_clear")
        print(_j.loads(stats["content"][0]["text"])["store"])
        print("memory server: OK")
        return
    while True:
        req = _read_json()
        if req is None:
            break
        resp = _handle_request(req)
        if resp is not None:
            _send_json(resp)


if __name__ == "__main__":
    main()