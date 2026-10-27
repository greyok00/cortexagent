#!/usr/bin/env python3
"""Readable CLI bridge to the compiled build module (tools/build_opt.*.so).

The binary release ships this module compiled. `python3 tools/build_opt.py`
stays callable in both trees: a source checkout (lib/*.py sources present)
gets the normal build pass, a binary tree (sources absent) gets a compiled
state report - there is nothing to build there.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SO = sorted(Path(__file__).resolve().parent.glob("build_opt.*.so"))


def _main() -> int:
    if not _SO:
        print("build_opt: no compiled build module and no dev sources - nothing to do.")
        return 0
    spec = importlib.util.spec_from_file_location("build_opt", _SO[0])
    impl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(impl)
    if not any((impl.REPO / m).exists() for m in impl.MODULES):
        return impl._check()
    return impl.main()


if __name__ == "__main__":
    sys.exit(_main())