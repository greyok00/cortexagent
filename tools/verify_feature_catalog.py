#!/usr/bin/env python3

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))

CATALOG = REPO_ROOT / "tools" / "feature_catalog.json"


def _check_mcp_tool(f: Dict) -> Tuple[bool, str]:

    try:
        from lib.converted_mcp_tools import TOOL_MAP
        name = f["id"]
        if name not in TOOL_MAP:
            return False, f"not in TOOL_MAP"
        fn = TOOL_MAP[name]
        if not callable(fn):
            return False, "not callable"
        return True, "reachable"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _check_registered_tool(f: Dict) -> Tuple[bool, str]:

    name = f["schema"]["name"]
    try:
        import lib.tool_registry as tr
        names = set()
        for t in tr.list_tools():
            if isinstance(t, dict):
                if "name" in t:
                    names.add(t["name"])
                elif "function" in t and isinstance(t["function"], dict):
                    names.add(t["function"].get("name"))
        if name in names:
            return True, "registered"

        text = (REPO_ROOT / "lib" / "tool_registry.py").read_text(errors="replace")
        if f'register_tool("{name}"' in text or f"register_tool('{name}'" in text:
            return True, "in source"
        return False, f"not in list_tools() nor source (have {len(names)} tools: {sorted(names)[:5]})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _check_cli(f: Dict) -> Tuple[bool, str]:

    rel, sub = f["id"].split(":", 1)
    try:
        import subprocess
        cp = subprocess.run(
            ["python3", f"lib/{rel}", sub, "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        if cp.returncode == 0 or "usage" in cp.stdout.lower() or "usage" in cp.stderr.lower():
            return True, "parses"
        return False, f"rc={cp.returncode} | err={cp.stderr[:100]!r}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _check_control(f: Dict) -> Tuple[bool, str]:

    cmd = f["schema"]["cmd"]
    path = REPO_ROOT / "lib" / "daemon.py"
    text = path.read_text(errors="replace")
    if f'cmd == "{cmd}"' in text or f"cmd == '{cmd}'" in text:
        return True, "handled"
    return False, "no handler in daemon.py"


CHECKERS = {
    "mcp_tool": _check_mcp_tool,
    "registered_tool": _check_registered_tool,
    "cli_subcommand": _check_cli,
    "control_socket_rpc": _check_control,
}


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify feature catalog")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--kind", help="Restrict to kind")
    args = ap.parse_args(argv)
    if not CATALOG.exists():
        print(f"catalog missing: {CATALOG}", file=sys.stderr)
        return 2
    catalog = json.loads(CATALOG.read_text())
    results: List[Dict[str, Any]] = []
    for f in catalog["features"]:
        if "error" in f:
            results.append({"id": f["id"], "passed": False, "detail": f["error"]})
            continue
        if args.kind and f.get("kind") != args.kind:
            continue
        kind = f.get("kind", "?")
        checker = CHECKERS.get(kind)
        if checker is None:
            results.append({"id": f["id"], "passed": None,
                            "detail": f"no checker for kind={kind}"})
            continue
        passed, detail = checker(f)
        results.append({"id": f["id"], "kind": kind, "passed": passed,
                        "detail": detail})
    total = len(results)
    passed = sum(1 for r in results if r["passed"] is True)
    failed = sum(1 for r in results if r["passed"] is False)
    skipped = total - passed - failed
    if args.json:
        print(json.dumps({
            "summary": {"total": total, "passed": passed,
                        "failed": failed, "skipped": skipped},
            "results": results,
        }, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Feature Catalog: {passed} passed / {failed} failed / "
              f"{skipped} skipped (of {total})")
        print(f"{'='*60}")
        for r in results:
            if r["passed"] is True:
                mark = "✅"
            elif r["passed"] is False:
                mark = "❌"
            else:
                mark = "  "
            print(f"  {mark} {r['id']:<45} {r.get('detail', '')}")
        if failed > 0 and not args.quiet:
            print(f"\nFAILED: {failed} features")
        elif not args.quiet:
            print("\nALL GREEN")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
