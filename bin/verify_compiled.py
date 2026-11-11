#!/usr/bin/env python3
"""Boot gate (development mode 2026-11-06, owner order).

Owner 2026-11-06: the .so freezing requirement is REMOVED — "remove the .so
requirement so we can keep modifying it and we'll .so it when it's fully done
and never needs changed". Raw .py sources are now authoritative wherever one
exists beside or in place of a compiled module; Cython freezing returns at
final ship time. This gate therefore checks:
  1. every pinned NON-.so manifest file exists with matching sha256/size
  2. the TUI's frozen dependencies are linked: @cortexagent/* (10)
  3. the TUI entry parses: node --check on dist cli.js (catches src/dist desync)

Fails loudly with the exact missing/mismatched path. Exit 0 = boot may proceed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "state" / "MANIFEST.json"
CLI = ROOT / "tui" / "packages" / "coding-agent" / "dist" / "cli.js"
NM = ROOT / "tui" / "node_modules"

EXPECTED_SO: dict = {}  # .so enforcement removed 2026-11-06 (see module docstring)
CORTEXAGENT_LINKS = ["agent-core", "ai", "client", "coding-agent", "evals", "protocol",
              "server", "telemetry", "tui", "session-backend-sqlite-node"]
CORTEX_LINKS = ["agent-core", "ai", "coding-agent", "tui"]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# Runtime-mutable state must never be frozen in the manifest (see
# scripts/gen_manifest.py); if it reappears, the generator regressed.
RUNTIME_NAMES = {"engine-status.json", "task-registry.json", "tuning.json"}
RUNTIME_DIRS = {"guides", "photo-cache"}


def _is_runtime(rel: str) -> bool:
    parts = Path(rel).parts
    return Path(rel).name in RUNTIME_NAMES or any(p in RUNTIME_DIRS for p in parts)


# 2026-11-06 owner: stale-module / twin-recythonize checks are GONE with the
# .so requirement. While iterating, .py edits are expected to drift from
# compiled artifacts — that is normal development mode now, not a boot error.
# Wherever a .py sibling exists, the raw file is treated as authoritative
# (the launcher imports it ahead of any compiled twin).

def main() -> int:
    bad: list[str] = []

    try:
        manifest = json.loads(MANIFEST.read_text())
    except FileNotFoundError:
        print(f"verify_compiled: {MANIFEST} missing — run scripts/gen_manifest.py")
        return 1
    for rel, meta in manifest.get("files", {}).items():
        if rel.endswith(".so"):
            # 2026-11-06 owner development mode: compiled artifacts are not
            # frozen — they regenerate when the project is done. Not pinned.
            continue
        p = ROOT / rel
        if _is_runtime(rel):
            bad.append(f"manifest pins runtime state: {rel} — rerun scripts/gen_manifest.py")
            continue
        if not p.exists():
            bad.append(f"missing: {rel}")
            continue
        if p.stat().st_size != meta.get("size"):
            bad.append(f"size mismatch: {rel}")
            continue
        want_hash = meta.get("sha256")
        if want_hash and _sha256(p) != want_hash:
            bad.append(f"hash mismatch: {rel}")

    for link in CORTEXAGENT_LINKS:
        if not (NM / "@cortexagent" / link).exists():
            bad.append(f"missing workspace link: @cortexagent/{link}")
    # 2026-10-24 hardened: the renamed dist imports @cortexagent/* only — any
    # surviving @(cortex|claude|anthropic|openai) scope link = desync residue
    for scope in ["@cortex", "@anthropic-ai-fork"]:
        if (NM / scope).exists():
            bad.append(f"stale compat scope must not exist: {scope}/")

    try:
        r = subprocess.run(["node", "--check", str(CLI)], capture_output=True, timeout=30)
        if r.returncode != 0:
            bad.append(f"dist cli.js fails node --check (src/dist desync?): {(r.stderr or b'').decode()[:200]}")
    except (OSError, subprocess.TimeoutExpired):
        bad.append("node --check could not run")

    if bad:
        print("verify_compiled: FROZEN TREE OUT OF SYNC — fixing required before boot:")
        for line in bad[:25]:
            print(f"  ✗ {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())