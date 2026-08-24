#!/usr/bin/env python3

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))

DEFAULT_OUT = REPO_ROOT / "tools" / "feature_catalog.json"


def _walk_converted_tools() -> list[dict]:
    try:
        from lib.converted_mcp_tools import CONVERTED_TOOLS, TOOL_MAP
        out = []
        for t in CONVERTED_TOOLS:
            name = t["function"]["name"]
            params = t["function"]["parameters"].get("properties", {})
            required = t["function"]["parameters"].get("required", [])
            out.append({
                "id": name,
                "kind": "mcp_tool",
                "advertised_in": "lib/converted_mcp_tools.py:CONVERTED_TOOLS",
                "implementation": f"lib/converted_mcp_tools.py:{name}",
                "schema": {"properties": list(params.keys()),
                           "required": required},
                "description": t["function"]["description"],
                "reachable": name in TOOL_MAP,
            })
        return out
    except Exception as e:
        return [{"id": "__error__", "kind": "mcp_tool", "error": str(e)}]


def _walk_argparse() -> list[dict]:

    out = []
    for path in sorted((REPO_ROOT / "lib").glob("*.py")):
        text = path.read_text(errors="replace")
        if "argparse" not in text or "add_subparsers" not in text:
            continue
        rel = path.name

        for m in re.finditer(r'(?:add_parser|add_argument)\(\s*["\'](\w+)["\']',
                             text):
            sub = m.group(1)
            if sub in ("help", "__default__"):
                continue
            out.append({
                "id": f"{rel}:{sub}",
                "kind": "cli_subcommand",
                "advertised_in": f"lib/{rel}",
                "schema": {"args": "<varies>"},
                "description": "",
            })
    return out


def _walk_control_socket() -> list[dict]:

    out = []
    path = REPO_ROOT / "lib" / "daemon.py"
    if not path.exists():
        return out
    text = path.read_text(errors="replace")

    for m in re.finditer(r'if\s+cmd\s*==\s*["\'](\w+)["\']', text):
        out.append({
            "id": f"control:{m.group(1)}",
            "kind": "control_socket_rpc",
            "advertised_in": "lib/daemon.py:_handle",
            "schema": {"cmd": m.group(1)},
            "description": "",
        })
    return out


def _walk_register_tool() -> list[dict]:

    out = []
    path = REPO_ROOT / "lib" / "tool_registry.py"
    if not path.exists():
        return out
    text = path.read_text(errors="replace")
    for m in re.finditer(r'register_tool\(\s*["\'](\w+)["\']', text):
        out.append({
            "id": f"tool_registry:{m.group(1)}",
            "kind": "registered_tool",
            "advertised_in": "lib/tool_registry.py",
            "schema": {"name": m.group(1)},
            "description": "",
        })
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        out.append(it)
    return out


def main() -> int:
    features = _dedupe(
        _walk_converted_tools()
        + _walk_argparse()
        + _walk_control_socket()
        + _walk_register_tool()
    )
    catalog = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_count": len(features),
        "by_kind": {},
        "features": features,
    }
    for f in features:
        k = f.get("kind", "?")
        catalog["by_kind"].setdefault(k, 0)
        catalog["by_kind"][k] += 1
    DEFAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUT.write_text(json.dumps(catalog, indent=2, sort_keys=True))
    print(f"wrote {len(features)} features to {DEFAULT_OUT}")
    for k, n in sorted(catalog["by_kind"].items()):
        print(f"  {k}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
