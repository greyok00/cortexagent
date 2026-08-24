#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / ".superpowers" / "manifest" / "cortexagent.manifest.json"


ROOTS = [
    "lib",
    "cortex",
    "cortexllm",
    "tests",
    "scripts",
    "bin",
    "engine",
    "hooks",
    "addons",
    "tools",
]


TOPLEVEL_FILES = [
    "install.sh",
    "patch_ub2560.py",
    "README.md",
    "LICENSE",
    ".SAFETY_QUICK_REF",
    ".SNAPSHOT_STATUS",
]


EXCLUDE_PATTERNS = {
    ".git", ".claude", ".superpowers", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "__pycache__", "node_modules", ".venv", "venv",
    ".swp", ".bak", ".tmp", ".pyc", ".pyo", ".log", ".lock", ".pid",
    "test_results", "out", "dist", "build",
}


def _should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    for ex in EXCLUDE_PATTERNS:
        if ex in parts:
            return True
    if path.name.startswith("~") or path.name.endswith(( ".pyc", ".pyo", ".swp", ".bak", ".tmp")):
        return True
    return False


def _iter_files() -> Iterable[Path]:
    seen = set()

    for name in TOPLEVEL_FILES:
        p = REPO_ROOT / name
        if p.is_file() and not _should_exclude(p):
            seen.add(p)
            yield p

    for root in ROOTS:
        rp = REPO_ROOT / root
        if not rp.exists():
            continue
        for path in rp.rglob("*"):
            if not path.is_file():
                continue
            if path in seen:
                continue
            if _should_exclude(path):
                continue
            seen.add(path)
            yield path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build(out_path: Path) -> Dict:
    files: Dict[str, Dict] = {}
    n = 0
    for f in _iter_files():
        rel = f.relative_to(REPO_ROOT).as_posix()
        try:
            st = f.stat()
            files[rel] = {
                "sha256": _sha256(f),
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            }
            n += 1
        except (OSError, PermissionError) as e:
            print(f"warn: skip {rel}: {e}", file=sys.stderr)
    manifest = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(REPO_ROOT),
        "file_count": n,
        "files": files,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _check(manifest: Dict) -> int:
    rows = []
    entries = manifest.get("files", {})
    for rel, meta in entries.items():
        p = REPO_ROOT / rel
        if not p.exists():
            rows.append(("MISSING", rel, ""))
            continue
        try:
            current_sha = _sha256(p)
            current_size = p.stat().st_size
        except (OSError, PermissionError) as e:
            rows.append(("ERROR", rel, str(e)))
            continue
        if current_sha != meta["sha256"] or current_size != meta["size"]:
            rows.append(("MODIFIED", rel, f"{meta['sha256'][:12]} -> {current_sha[:12]}"))

    seen = set(entries.keys())
    for f in _iter_files():
        rel = f.relative_to(REPO_ROOT).as_posix()
        if rel not in seen:
            rows.append(("NEW", rel, ""))
    if not rows:
        print(f"OK: {len(entries)} files, no drift")
        return 0
    rows.sort(key=lambda r: (r[0], r[1]))
    print(f"DRIFT: {len(rows)} files differ")
    print(f"{'STATUS':<10} {'PATH':<60} {'DETAIL'}")
    for status, rel, detail in rows[:200]:
        print(f"{status:<10} {rel:<60} {detail}")
    if len(rows) > 200:
        print(f"... and {len(rows) - 200} more")
    return 1


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Build / verify cortexagent file-hash manifest")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Manifest path")
    ap.add_argument("--check", action="store_true", help="Verify current files against manifest")
    ap.add_argument("--print", action="store_true", help="Print summary after build")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.check:
        if not out.exists():
            print(f"manifest not found: {out}", file=sys.stderr)
            return 2
        manifest = json.loads(out.read_text())
        return _check(manifest)
    manifest = _build(out)
    if args.print:
        print(f"built: {manifest['file_count']} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
