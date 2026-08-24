#!/usr/bin/env python3

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