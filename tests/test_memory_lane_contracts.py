#!/usr/bin/env python3
"""Regression tests for the JSONL memory lane contracts.

Covers the shared tail reader, the clear-both-
stores contract, md-fallback searchability, and the memory daemon ack
protocol with oversized payloads.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENVROOT = dict(os.environ)


def _env(store: str) -> dict:
    return dict(ENVROOT, CORTEXAGENT_MEMORY_DIR=str(store))


def test_read_jsonl_tail_semantics(tmp_path):
    (tmp_path / "f.jsonl").write_text(
        "\n".join(json.dumps({"i": i}) for i in range(10)) + "\n")
    res = (subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "import json; from lib.memory_readers import read_jsonl_tail as t;"
         "print(json.dumps(t('%s', 5)))" % (tmp_path / "f.jsonl")],
        cwd=str(REPO), capture_output=True, text=True, timeout=60))
    out = json.loads(res.stdout)
    assert out["status"] == "ok" and [r["i"] for r in out["rows"]] == [5, 6, 7, 8, 9]


def test_read_jsonl_tail_bigger_than_window(tmp_path):
    # 20 x ~1 KB rows; window 4 KB → boundary row is partial and must be
    # dropped, not parsed, and the tail's own rows must still come back.
    rows = [json.dumps({"i": i, "pad": "x" * 1000}) for i in range(20)]
    (tmp_path / "big.jsonl").write_text("\n".join(rows) + "\n")
    r = subprocess.run(
        [sys.executable, "-c",
         "import json; from lib.memory_readers import read_jsonl_tail as t;"
         "print(json.dumps(t(%r, 8, window_bytes=4096)))" % str(tmp_path / "big.jsonl")],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert out["status"] == "ok", out
    assert out["skipped_bytes"] > 0
    assert [r["i"] for r in out["rows"]] == [16, 17, 18, 19], out["rows"]


def test_read_jsonl_tail_corrupt_and_missing(tmp_path):
    f = tmp_path / "c.jsonl"
    f.write_text('{"i":1}\nGARBAGE\n{"i":2}\n')
    r = subprocess.run(
        [sys.executable, "-c",
         "import json; from lib.memory_readers import read_jsonl_tail as t;"
         "print(json.dumps(t(%r, 10)))" % str(f)],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert out["status"] == "ok" and out["dropped"] == 1 and len(out["rows"]) == 2

    (tmp_path / "all.jsonl").write_text("GARBAGE\nNOT JSON\n")
    r = subprocess.run(
        [sys.executable, "-c",
         "import json; from lib.memory_readers import read_jsonl_tail as t;"
         "print(json.dumps(t(%r, 10)))" % str(tmp_path / "all.jsonl")],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert json.loads(r.stdout)["status"] == "corrupt"

    r = subprocess.run(
        [sys.executable, "-c",
         "import json; from lib.memory_readers import read_jsonl_tail as t;"
         "print(json.dumps(t(%r, 5)))" % str(tmp_path / "nofile.jsonl")],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert json.loads(r.stdout)["status"] == "missing"


def _mcp(reqs, store):
    lines = "\n".join(json.dumps(r) for r in reqs) + "\n"
    return subprocess.run(
        [sys.executable, str(REPO / "memory" / "mcp_server.py")],
        input=lines, env=_env(store), cwd=str(REPO),
        capture_output=True, text=True, timeout=60)


def _call(rpc_out, i):
    for line in rpc_out.stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("id") == i:
            return obj.get("result") or obj.get("error") or {}
    raise AssertionError(f"no response for id {i}")


def test_clear_cold_clears_both_stores(tmp_path):
    resp = _mcp([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "memory_write",
            "arguments": {"content": "alpha fact", "tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "memory_read", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "memory_clear", "arguments": {"tier": "cold"}}},
    ], tmp_path)
    assert "alpha fact" in json.dumps(_call(resp, 3))
    cleared = _call(resp, 4)["content"][0]["text"]
    assert "cortexagent.jsonl" in cleared, cleared

    # markdown fallback corpus present before clear → after clear both gone
    md = tmp_path / "cold" / "cortexagent.md"
    md.parent.mkdir(parents=True, exist_ok=True)

    resp = _mcp([
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "memory_write", "arguments": {"content": "alpha fact", "tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "memory_read", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "memory_search", "arguments": {"query": "alpha fact"}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "memory_clear", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
            "name": "memory_read", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {
            "name": "memory_search", "arguments": {"query": "alpha fact"}}},
    ], tmp_path)
    assert "alpha fact" in json.dumps(_call(resp, 6))
    assert "alpha fact" in json.dumps(_call(resp, 7))
    md.write_text("mdword: markdown fallback line\n")
    resp = _mcp([
        {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {
            "name": "memory_search", "arguments": {"query": "mdword"}}},
        {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {
            "name": "memory_read", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {
            "name": "memory_clear", "arguments": {"tier": "cold"}}},
        {"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": {
            "name": "memory_search", "arguments": {"query": "mdword"}}},
        {"jsonrpc": "2.0", "id": 15, "method": "tools/call", "params": {
            "name": "memory_read", "arguments": {"tier": "cold"}}},
    ], tmp_path)
    assert "mdword" in json.dumps(_call(resp, 11)), "search must read the md store"
    assert "markdown fallback line" in json.dumps(_call(resp, 12)), "read must include md"
    assert "cortexagent.md" in _call(resp, 13)["content"][0]["text"], _call(resp, 13)
    assert "mdword" not in json.dumps(_call(resp, 14)), _call(resp, 14)
    text15 = _call(resp, 15)["content"][0]["text"]
    assert json.loads(text15) == [], text15


def test_daemon_ack_and_oversized(tmp_path):
    store = tmp_path / "store"
    sock = tmp_path / "mem.sock"
    daemon = subprocess.Popen(
        [sys.executable, str(REPO / "lib" / "memory_daemon.py"),
         "--store", str(store), "--socket", str(sock), "--name", "testmem"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.05)
        assert sock.exists(), "daemon socket never appeared"

        snippet = (
            "import lib.memory_thin as mt\n"
            f"mt.DAEMON_SOCKET = __import__('pathlib').Path({str(sock)!r})\n"
            "small = mt._try_daemon({'role': 'user', 'content': 'tiny note'})\n"
            "big = mt._try_daemon({'role': 'user', 'content': 'x' * 6000})\n"
            "got = mt.read_last(5)\n"
            "print('ACK', small, big, len(got))\n")
        r = subprocess.run([sys.executable, "-c", snippet], cwd=str(REPO),
                           env=_env(store), capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "ACK True True 2" in r.stdout, r.stdout
    finally:
        daemon.send_signal(signal.SIGTERM)
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.kill()


def test_converted_read_corrupt_is_error(tmp_path):
    store = tmp_path
    (store / "hot").mkdir(parents=True, exist_ok=True)
    (store / "hot" / "cortexagent.jsonl").write_text("GARBAGE\nNOT JSON\n")
    r = subprocess.run(
        [sys.executable, "-c",
         "import json; from lib.converted_mcp_tools import memory_read;"
         "print(json.dumps(memory_read('hot')))"],
        cwd=str(REPO), env=_env(store), capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert out.get("error") and "corrupt" in out["error"], out