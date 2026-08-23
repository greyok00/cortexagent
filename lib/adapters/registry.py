#!/usr/bin/env python3
"""registry.py — Module-level adapter registry.

Self-registration: adapters import `register` and call it at module import.
Re-registering the same name overwrites (idempotent for hot-reload use).

`safe_search_all` swallows per-adapter exceptions and returns per-adapter
status — one bad backend never poisons the fan-out. `search_all` raises
on the first failure (use only when the caller wants strict semantics).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from .base import BaseAdapter

_REGISTRY: Dict[str, BaseAdapter] = {}
_LOCK = threading.Lock()


def register(adapter: BaseAdapter) -> None:
    """Register or overwrite an adapter. Thread-safe."""
    if not adapter.name:
        raise ValueError(f"{type(adapter).__name__} has empty .name")
    with _LOCK:
        _REGISTRY[adapter.name] = adapter


def unregister(name: str) -> bool:
    """Remove an adapter by name. Returns True if it existed."""
    with _LOCK:
        return _REGISTRY.pop(name, None) is not None


def get(name: str) -> Optional[BaseAdapter]:
    """Look up one adapter, or None."""
    return _REGISTRY.get(name)


def list_adapters(only_enabled: bool = False) -> List[BaseAdapter]:
    """Return registered adapters. Sorted by name for stable ordering."""
    items = sorted(_REGISTRY.values(), key=lambda a: a.name)
    if only_enabled:
        items = [a for a in items if a.enabled]
    return items


def all_adapters_dict(only_enabled: bool = False) -> List[Dict[str, Any]]:
    """JSON-safe list of `to_dict()` snapshots, for tool/webui surface."""
    return [a.to_dict() for a in list_adapters(only_enabled=only_enabled)]


def search_all(
    query: str,
    limit: int = 5,
    only_enabled: bool = True,
    per_adapter_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Fan-out across every registered (enabled) adapter.

    Returns {adapter_name: list-of-results-or-error}. One failing adapter
    never blocks the rest — its slot becomes {"error": str(e), "source": name}.
    """
    out: Dict[str, Any] = {}
    cap = per_adapter_limit if per_adapter_limit is not None else limit
    for adapter in list_adapters(only_enabled=only_enabled):
        try:
            out[adapter.name] = adapter.search(query, limit=cap)
        except Exception as e:
            out[adapter.name] = {"error": str(e), "source": adapter.name}
    return out


def reset_for_tests() -> None:
    """Wipe the registry. Tests only — never call from production code."""
    with _LOCK:
        _REGISTRY.clear()