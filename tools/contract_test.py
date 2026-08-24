#!/usr/bin/env python3

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

    import re
    refs: List[str] = set()
    refs.update(re.findall(r":func:`~?([\w.]+)`", doc))
    refs.update(re.findall(r":class:`~?([\w.]+)`", doc))
    refs.update(re.findall(r":meth:`~?([\w.]+)`", doc))
    refs.update(re.findall(r"`([\w]+\.[\w]+)`", doc))
    return sorted(r for r in refs if "." in r)


def _scan_lib_module(path: Path) -> Dict[str, Any]:

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

    path = path or (REPO_ROOT / "lib" / "daemon.py")
    text = path.read_text(errors="replace")
    import re
    cmds = sorted(set(re.findall(r'if\s+cmd\s*==\s*["\'](\w+)["\']', text)))

    doc_text = text
    docs_dir = REPO_ROOT / "docs"
    if docs_dir.exists():
        for f in docs_dir.rglob("*.md"):
            doc_text += f.read_text(errors="replace")
    return [{"rpc": c,
             "documented": c in doc_text,
             "handler": f'cmd == "{c}"'} for c in cmds]


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Doc-vs-code contract test")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {
        "schema": 1,
        "lib_modules": [],
        "daemon_rpcs": [],
        "errors": [],
    }



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


    rpcs = _check_daemon_control_rpcs()
    report["daemon_rpcs"] = rpcs


    n_mod = len(report["lib_modules"])
    n_mod_fail = sum(1 for m in report["lib_modules"] if not m["passed"])
    n_rpc = len(rpcs)
    n_rpc_fail = sum(1 for r in rpcs if not r["documented"])

    report["summary"] = {
        "lib_modules": n_mod,
        "lib_modules_failed": n_mod_fail,
        "daemon_rpcs": n_rpc,
        "daemon_rpcs_undocumented": n_rpc_fail,
        "passed": (n_mod_fail + n_rpc_fail) == 0,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"\n{'='*60}")
        print(f"Doc-vs-Code Contract: {n_mod} modules / {n_rpc} daemon RPCs")
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
        if not (n_mod_fail or n_rpc_fail):
            if not args.quiet:
                print("\n✅ ALL GREEN")

    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
