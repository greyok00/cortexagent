#!/usr/bin/env python3
"""Readable CLI bridge to the compiled source-minifier (tools/minify_source.*.so).

`python3 tools/minify_source.py` stays callable in binary distributions: the
call is dispatched to the compiled module, and a plain release archive with
no git metadata degrades to a clean no-op instead of crashing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SO = sorted(Path(__file__).resolve().parent.glob("minify_source.*.so"))


def _main() -> int:
    if not _SO:
        print("minify_source: no compiled module found - nothing to do.")
        return 0
    spec = importlib.util.spec_from_file_location("minify_source", _SO[0])
    impl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(impl)
    try:
        return impl.main()
    except FileNotFoundError:
        # no git in a plain release archive: no tracked sources to minify
        print("minify_source: git unavailable - nothing to minify.")
        return 0


if __name__ == "__main__":
    sys.exit(_main())