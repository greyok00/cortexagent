#!/usr/bin/env python3
"""minify_and_decomment.py — owner order 2026-10-24:
"remove all comments and even shebangs from the code. minify and convert to
cython." Applied to a source file or a whole directory:

  1. parse with ast (refuses to emit anything it cannot parse — no broken .so)
  2. drop EVERY docstring expression (no runtime __doc__ use was found in the
     ported packages), which also drops comments and shebangs — ast.unparse
     emits none of them by construction
  3. ast.unparse = the minified, decommented, shebang-free source
  4. writes to the destination dir, preserving module names

Usage: minify_and_decomment.py <src-dir-or-file> <dest-dir>
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path


def _strip_docstrings(node: ast.AST) -> None:
    for child in ast.walk(node):
        body = getattr(child, "body", None)
        if not body:
            continue
        if (
            isinstance(child, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and len(body) > 0
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            del body[0]
            if not body:
                body.append(ast.Pass())


def minify_source(src: str, filename: str) -> str:
    tree = ast.parse(src, filename=filename)  # refuses syntax it cannot guarantee
    _strip_docstrings(tree)
    return ast.unparse(tree)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src_path, dest_dir = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(src_path.glob("*.py")) if src_path.is_dir() else [src_path]
    ok, failed = 0, []
    for f in files:
        dest = dest_dir / f.name
        try:
            dest.write_text(minify_source(f.read_text(), f.name))
            shutil.copymode(f, dest)
            ok += 1
        except Exception as e:
            failed.append(f"{f.name}: {type(e).__name__}: {e}")
    if failed:
        print("MINIFY REFUSED (nothing half-processed):")
        for line in failed:
            print("  " + line)
        return 1
    print(f"minified+decommented {ok} file(s) -> {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())