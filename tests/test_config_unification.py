#!/usr/bin/env python3
"""Regression tests for config-path unification and the launcher's
skip-write-when-equal render contract. All tests run in a sandbox HOME — never the
live ~/.cortexagent tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _sandbox_env(home: Path) -> dict:
    env = dict(os.environ, HOME=str(home), CORTEXAGENT_CLI="/bin/true")
    env.pop("CORTEXAGENT_MCP_CONFIG", None)
    env.pop("CORTEXAGENT_CONFIG_DIR", None)
    return env


def test_mcp_config_constant_single_source():
    """The constant defaults to CONFIG_DIR/mcp.json and follows
    CORTEXAGENT_CONFIG_DIR when set."""
    code = (
        "import sys, os; sys.path.insert(0, {repo!r});"
        "from lib.config import CONFIG_DIR, MCP_CONFIG;"
        "print(MCP_CONFIG); assert MCP_CONFIG == CONFIG_DIR / 'mcp.json';"
        "os.environ['CORTEXAGENT_CONFIG_DIR'] = os.path.join(os.environ['ALT'], 'd');"
        "import importlib, lib.config; importlib.reload(lib.config);"
        "print(lib.config.MCP_CONFIG);"
        "assert lib.config.MCP_CONFIG == lib.config.CONFIG_DIR / 'mcp.json'"
    ).format(repo=str(REPO))
    env = dict(os.environ, ALT="/tmp/alt-root-xyz")
    env.pop("CORTEXAGENT_MCP_CONFIG", None)
    env.pop("CORTEXAGENT_CONFIG_DIR", None)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr


def test_doctor_migrates_legacy_mcp_and_merges():
    """Migration: legacy ~/.cortexagent/mcp.json is adopted at the
    canonical path; user servers survive the managed-key merge."""
    home = Path(tempfile.mkdtemp(prefix="ca-doctor-"))
    try:
        legacy_dir = home / ".cortexagent"
        legacy_dir.mkdir()
        legacy = legacy_dir / "mcp.json"
        legacy.write_text(json.dumps(
            {"mcpServers": {"mycustom": {"command": "echo", "args": ["hi"]}}}) + "\n")
        env = _sandbox_env(home)

        def doc(*flags):
            r = subprocess.run(
                [sys.executable, str(REPO / "lib" / "doctor.py"), "--no-patch", *flags],
                capture_output=True, text=True, env=env, timeout=120)
            return json.loads(r.stdout)

        dry = doc("--dry-run", "--json")
        row = next(c for c in dry if c.get("name") == "mcp.json")
        assert row["status"] == "would-fix", row
        assert "migrate" in row["detail"], row
        assert not (home / ".cortexagent-config").exists(), "dry-run created config dir"

        doc("--fix", "--json")
        migrated = (home / ".cortexagent-config" / "mcp.json").read_text()
        user_server = json.loads(migrated).get("mcpServers", {}).get("mycustom")
        assert user_server == {"command": "echo", "args": ["hi"]}, migrated

        doc("--fix", "--json")
        final = json.loads((home / ".cortexagent-config" / "mcp.json").read_text())
        assert "mycustom" in final["mcpServers"], final
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_launcher_skip_write_when_equal(tmp_path):
    """Identical render → no rewrite (mtime stable), no .previous;
    differing content → one .previous snapshot, then the real write."""
    home = tmp_path / "home"
    home.mkdir()
    env = _sandbox_env(home)
    src = (REPO / "bin" / "cortexagent").read_text().splitlines(True)
    start = next(i for i, l in enumerate(src) if l.startswith("CONFIG_DIR="))
    end = max(i for i, l in enumerate(src) if l.rstrip("\n") == "PY")
    slab = (f"REPO_ROOT={REPO}\n" + "".join(src[start:end + 1])
            + "\nexport CORTEXAGENT_CONFIG_DIR=${CONFIG_DIR}\n"
              "export CORTEXAGENT_MCP_CONFIG=${CONFIG_DIR}/mcp.json\n")
    writers = tmp_path / "writers.sh"
    writers.write_text(slab)

    def launch():
        r = subprocess.run(["bash", str(writers)], env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr

    launch()
    cfgdir = home / ".cortexagent-config"
    mcp = cfgdir / "mcp.json"
    assert mcp.exists()
    first = mcp.read_text()
    first_mtime = mcp.stat().st_mtime_ns
    time.sleep(0.02)
    launch()
    assert mcp.read_text() == first, "identical render rewritten"
    assert mcp.stat().st_mtime_ns == first_mtime, "identical render touched"
    assert not (cfgdir / "mcp.json.previous").exists()
    assert not (cfgdir / "settings.json.previous").exists()

    user = json.loads(first)
    user["mcpServers"]["usercustom"] = {"command": "echo", "args": ["user"]}
    user_text = json.dumps(user, indent=2) + "\n"
    mcp.write_text(user_text)
    launch()
    prev = cfgdir / "mcp.json.previous"
    assert prev.exists(), "no .previous before real overwrite"
    assert prev.read_text() == user_text, "user edit not snapshotted"
    assert "usercustom" not in mcp.read_text(), "file should hold the render now"