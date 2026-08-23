#!/usr/bin/env python3
"""verify_manifest.py — verify the file-hash manifest against current tree.

Usage:
  python3 tools/verify_manifest.py [--quiet] [--json] [--strict]

Exit codes:
  0  no drift
  1  drift detected (MODIFIED, MISSING)
  2  manifest missing (run build_manifest.py)
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / ".superpowers" / "manifest" / "cortexagent.manifest.json"


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except (FileNotFoundError, IsADirectoryError):
        return ""
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify CortexAgent file-hash manifest")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="Only return exit code, no output")
    ap.add_argument("--strict", action="store_true",
                    help="Treat NEW files as drift too")
    args = ap.parse_args(argv)
    if not MANIFEST.exists():
        if not args.quiet:
            print(f"manifest missing: {MANIFEST}", file=sys.stderr)
            print("run: python3 tools/build_manifest.py", file=sys.stderr)
        return 2
    # Import the canonical file list from build_manifest.
    # (Reusing build_manifest._iter_files keeps verifier + builder in lockstep.)
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from build_manifest import _iter_files, TOPLEVEL_FILES, ROOTS
    manifest = json.loads(MANIFEST.read_text())
    expected: Dict[str, Dict] = manifest.get("files", {})
    modified: List[str] = []
    missing: List[str] = []
    new: List[str] = []
    matched = 0
    checked_paths: set = set()
    actual_files: Dict[str, str] = {}
    for f in _iter_files():
        rel = str(f.relative_to(REPO_ROOT))
        actual_files[rel] = _hash(f)
        if rel not in expected:
            new.append(rel)
            continue
        checked_paths.add(rel)
        if _hash(f) != expected[rel].get("sha256"):
            modified.append(rel)
        else:
            matched += 1
    # Anything in expected that we didn't visit = MISSING
    for rel in expected:
        if rel not in checked_paths and rel != MANIFEST.name:
            missing.append(rel)
    summary = {
        "matched": matched,
        "modified": len(modified),
        "missing": len(missing),
        "new": len(new),
        "strict": args.strict,
    }
    drift = bool(modified or missing or (args.strict and new))
    summary["drift"] = drift
    if args.json:
        print(json.dumps({
            "summary": summary,
            "modified": modified[:50],
            "missing": missing[:50],
            "new": new[:50],
        }, indent=2))
    elif not args.quiet:
        print(f"\n{'='*60}")
        print(f"Manifest: {matched} matched | {len(modified)} modified | "
              f"{len(missing)} missing | {len(new)} new")
        print(f"{'='*60}")
        for group, label in [(modified, "MODIFIED"), (missing, "MISSING"),
                             (new, "NEW")]:
            for r in group[:20]:
                print(f"  {label}: {r}")
        if len(modified) > 20 or len(missing) > 20 or len(new) > 20:
            print(f"  ... (truncated; see --json for full list)")
        if drift:
            print(f"\n❌ DRIFT DETECTED")
        else:
            print("\n✅ NO DRIFT")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
