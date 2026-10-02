#!/usr/bin/env python3
"""Startup shim for MCP servers spawned by the cortexagent TUI.

The TUI spawns its MCP servers into its own process group, so a Ctrl+C at the
terminal (the operator aborting a runaway agent) delivers SIGINT to every
python child as well. A child sitting in subprocess.wait() or a stdin read
dies with a KeyboardInterrupt traceback dumped straight into the operator's
terminal on top of the TUI's own exit output (2026-10-02 incident).

This shim installs a quiet SIGINT/SIGTERM handler — exit, no traceback — and
then runs the real server script with its original argv and its script
directory on sys.path, exactly as `python3 <script> ...` would have.

Usage (built by bin/cortexagent):  python3 mcp-sigint-shim.py <server.py> [server-args...]
"""

from __future__ import annotations

import os
import runpy
import signal
import sys

_TARGET = sys.argv[1]


def _quiet_exit(signum, _frame):
    # Operator interrupt / shutdown inside a background MCP server: exit
    # silently instead of printing a KeyboardInterrupt traceback into the
    # TUI's terminal. Exit code mirrors the conventional signal exit code.
    sys.exit(128 + signum)


def main() -> None:
    signal.signal(signal.SIGINT, _quiet_exit)
    signal.signal(signal.SIGTERM, _quiet_exit)
    script_dir = os.path.dirname(os.path.abspath(_TARGET))
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    sys.argv[0] = _TARGET
    runpy.run_path(_TARGET, run_name="__main__")


if __name__ == "__main__":
    main()