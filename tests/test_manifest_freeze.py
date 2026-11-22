"""Freeze-gate regression tests: what the boot manifest must never pin.

2026-11-21 audit: the synced lane modules (mcp/greysearch/*.py,
mcp/kbserver/*.py) were pinned with size+sha256 even though bin/cortex-agent's
_lane_sync overwrites them with newer owner-tree copies at every boot — every
owner-side edit then failed the frozen-tree gate until gen_manifest.py was
rerun by hand. lane-pins.json (regenerated each boot) is their pin instead;
the manifest keeps pinning the lanes' non-synced data.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_gen_manifest():
    spec = importlib.util.spec_from_file_location(
        "gen_manifest", ROOT / "scripts" / "gen_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lane_synced_files_are_never_pinned(tmp_path, monkeypatch):
    gm = _load_gen_manifest()
    monkeypatch.setattr(gm, "ROOT", tmp_path)
    lane_py = tmp_path / "mcp/greysearch/greysearch_mcp.py"
    kb_py = tmp_path / "mcp/kbserver/kbserver.py"
    portal = tmp_path / "mcp/greysearch/portal/index.html"
    run_row = tmp_path / "mcp/greysearch/runs/run-1.json"
    research = tmp_path / "mcp/greysearch/research/data/sites.json"
    for f in (lane_py, kb_py, portal, run_row, research):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    # synced by _lane_sync every boot — never frozen
    assert gm._runtime(lane_py)
    assert gm._runtime(kb_py)
    assert gm._runtime(portal)
    assert gm._runtime(run_row)
    # non-synced lane data keeps its pin
    assert not gm._runtime(research)
