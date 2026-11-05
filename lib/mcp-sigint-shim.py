#!/usr/bin/env python3


from __future__ import annotations

import os
import runpy
import signal
import sys

_TARGET = sys.argv[1]


def _quiet_exit(signum, _frame):



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