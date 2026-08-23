#!/usr/bin/env python3
"""lib/adapters — API proxy layer.

Drop a new `<backend>.py` module here that subclasses BaseAdapter and calls
`register(...)` at import time. Then add an import line below. No edits to
core agent logic needed.

Public surface:
  - `BaseAdapter`         (from .base)
  - `register, get, list_adapters, search_all` (from .registry)
  - `reset_for_tests`     (from .registry)

Side-effect: importing `lib.adapters` (or any submodule) auto-registers
every concrete adapter that's listed below.
"""
from __future__ import annotations

from .base import BaseAdapter
from .registry import (
    register,
    unregister,
    get,
    list_adapters,
    all_adapters_dict,
    search_all,
    reset_for_tests,
)

# ── Side-effect imports — every concrete adapter self-registers on import ──
# To add a new adapter: drop `lib/adapters/foo.py` with a BaseAdapter subclass
# that calls `register(...)`, then add one line below.
from . import google_search        # noqa: E402, F401
from . import searxng_adapter      # noqa: E402, F401

__all__ = [
    "BaseAdapter",
    "register",
    "unregister",
    "get",
    "list_adapters",
    "all_adapters_dict",
    "search_all",
    "reset_for_tests",
]