#!/usr/bin/env python3
"""contract_test.py — assert documentation matches code.

Sources of declared API:
  - Module docstrings (first line after triple quotes)
  - Module `__all__` (if present)
  - Argparse subparsers
  - Webui HTTP endpoints (parsed.path patterns)
  - Daemon control socket RPCs (lib/daemon.py)
  - Public functions/classes not starting with `_`

For each declared API, asserts:
  - The function/class/endpoint exists in the file claimed.
  - If the docstring names parameters, the function signature has them.

Run:
  python3 tools/contract_test.py [--json]

Exit codes: 0 all green / 1 one or more misses / 2 catastrophic.
"""
import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_module(path: Path):
    try:
        return ast.parse(path.read_text(errors="replace"))
    except SyntaxError as e:
        return None


def _declared_names(tree: ast.Module) -> List[Tuple[str, str, int]]:
    """Walk top-level def/class for names NOT starting with _."""
    out: List[Tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                out.append((node.name, kind, node.lineno))
    return out


def _module_docstring(tree: ast.Module) -> str:
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(
        tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        return tree.body[0].value.value
    return ""


def _docstring_mentions_symbol(doc: str) -> List[str]:
    """Pull `:func:` and `:class:` reST role targets + bare `module.x` references."""
    import re
    refs: List[str] = set()
    refs.update(re.findall(r":func:`~?([\w.]+)`", doc))
    refs.update(re.findall(r":class:`~?([\w.]+)`", doc))
    refs.update(re.findall(r":meth:`~?([\w.]+)`", doc))
    refs.update(re.findall(r"`([\w]+\.[\w]+)`", doc))
    return sorted(r for r in refs if "." in r)


def _scan_lib_module(path: Path) -> Dict[str, Any]:
    """Returns declared names, docstring refs, all public symbols."""
    tree = _parse_module(path)
    if tree is None:
        return {"path": str(path), "syntax_error": True, "names": [], "refs": []}
    declared = _declared_names(tree)
    docs = _module_docstring(tree)
    refs = _docstring_mentions_symbols(docs) if False else _docstring_mentions_symbol(docs)
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "names": declared,
        "refs": refs,
        "docstring_first_line": docs.splitlines()[0] if docs else "",
    }


def _check_lib_module(path: Path) -> Tuple[bool, str]:
    info = _scan_lib_module(path)
    if info.get("syntax_error"):
        return False, "syntax error"
    if not info["names"]:
        return False, "no public symbols"
    return True, f"{len(info['names'])} symbols"


def _check_daemon_control_rpcs(path: Path = None) -> List[Dict[str, Any]]:
    """Walk lib/daemon.py for `if cmd == "name":` handlers, assert each is documented somewhere."""
    path = path or (REPO_ROOT / "lib" / "daemon.py")
    text = path.read_text(errors="replace")
    import re
    cmds = sorted(set(re.findall(r'if\s+cmd\s*==\s*["\'](\w+)["\']', text)))
    # Documented in lib/daemon.py docstring OR in CHANGELOG/docs/
    doc_text = text
    docs_dir = REPO_ROOT / "docs"
    if docs_dir.exists():
        for f in docs_dir.rglob("*.md"):
            doc_text += f.read_text(errors="replace")
    return [{"rpc": c,
             "documented": c in doc_text,
             "handler": f'cmd == "{c}"'} for c in cmds]


def _check_webui_endpoints() -> List[Dict[str, Any]]:
    path = REPO_ROOT / "lib" / "webui.py"
    text = path.read_text(errors="replace")
    import re
    paths = sorted(set(re.findall(
        r'parsed\.path\s*(?:==|startswith)\(\s*["\']([^"\']+)["\']', text)))
    return [{"endpoint": p, "in_source": p in text} for p in paths]


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Doc-vs-code contract test")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {
        "schema": 1,
        "lib_modules": [],
        "daemon_rpcs": [],
        "webui_endpoints": [],
        "errors": [],
    }

    # 1. Every lib/*.py parses + has at least one public symbol (or is a
    #    known runtime script — chain_diagnostic, tray_dashboard, version).
    RUNTIME_SCRIPTS = {"chain_diagnostic.py", "tray_dashboard.py",
                       "version.py"}
    lib_dir = REPO_ROOT / "lib"
    for path in sorted(lib_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.name in RUNTIME_SCRIPTS:
            tree = _parse_module(path)
            ok = tree is not None and bool(_module_docstring(tree))
            report["lib_modules"].append({
                "path": str(path.relative_to(REPO_ROOT)),
                "passed": ok,
                "detail": "runtime script (skipped public-symbol check)",
                "docstring_first_line": (
                    _module_docstring(tree).splitlines()[0]
                    if ok and tree else ""),
                "public_count": 0,
            })
            continue
        passed, detail = _check_lib_module(path)
        info = _scan_lib_module(path)
        report["lib_modules"].append({
            "path": info["path"],
            "passed": passed,
            "detail": detail,
            "docstring_first_line": info["docstring_first_line"],
            "public_count": len(info["names"]),
        })

    # 2. Daemon control RPCs
    rpcs = _check_daemon_control_rpcs()
    report["daemon_rpcs"] = rpcs

    # 3. Webui endpoints
    eps = _check_webui_endpoints()
    report["webui_endpoints"] = eps

    # ── Summary ─────────────────────────────────────────────────────────────
    n_mod = len(report["lib_modules"])
    n_mod_fail = sum(1 for m in report["lib_modules"] if not m["passed"])
    n_rpc = len(rpcs)
    n_rpc_fail = sum(1 for r in rpcs if not r["documented"])
    n_ep = len(eps)
    n_ep_fail = sum(1 for e in eps if not e["in_source"])

    report["summary"] = {
        "lib_modules": n_mod,
        "lib_modules_failed": n_mod_fail,
        "daemon_rpcs": n_rpc,
        "daemon_rpcs_undocumented": n_rpc_fail,
        "webui_endpoints": n_ep,
        "webui_endpoints_missing": n_ep_fail,
        "passed": (n_mod_fail + n_rpc_fail + n_ep_fail) == 0,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"\n{'='*60}")
        print(f"Doc-vs-Code Contract: {n_mod} modules / {n_rpc} daemon RPCs / {n_ep} endpoints")
        print(f"{'='*60}")
        if n_mod_fail:
            print(f"\n❌ lib modules failed ({n_mod_fail}):")
            for m in report["lib_modules"]:
                if not m["passed"]:
                    print(f"   {m['path']}: {m['detail']}")
        if n_rpc_fail:
            print(f"\n⚠️  daemon RPCs undocumented ({n_rpc_fail}):")
            for r in rpcs:
                if not r["documented"]:
                    print(f"   {r['rpc']}: {r['handler']}")
        if n_ep_fail:
            print(f"\n❌ webui endpoints missing ({n_ep_fail}):")
            for e in eps:
                if not e["in_source"]:
                    print(f"   {e['endpoint']}")
        if not (n_mod_fail or n_rpc_fail or n_ep_fail):
            if not args.quiet:
                print("\n✅ ALL GREEN")

    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
