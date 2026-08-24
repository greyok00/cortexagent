#!/usr/bin/env python3

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from .base import BaseAdapter

_REGISTRY: Dict[str, BaseAdapter] = {}
_LOCK = threading.Lock()


def register(adapter: BaseAdapter) -> None:

    if not adapter.name:
        raise ValueError(f"{type(adapter).__name__} has empty .name")
    with _LOCK:
        _REGISTRY[adapter.name] = adapter


def unregister(name: str) -> bool:

    with _LOCK:
        return _REGISTRY.pop(name, None) is not None


def get(name: str) -> Optional[BaseAdapter]:

    return _REGISTRY.get(name)


def list_adapters(only_enabled: bool = False) -> List[BaseAdapter]:

    items = sorted(_REGISTRY.values(), key=lambda a: a.name)
    if only_enabled:
        items = [a for a in items if a.enabled]
    return items


def all_adapters_dict(only_enabled: bool = False) -> List[Dict[str, Any]]:

    return [a.to_dict() for a in list_adapters(only_enabled=only_enabled)]


def search_all(
    query: str,
    limit: int = 5,
    only_enabled: bool = True,
    per_adapter_limit: Optional[int] = None,
) -> Dict[str, Any]:

    out: Dict[str, Any] = {}
    cap = per_adapter_limit if per_adapter_limit is not None else limit
    for adapter in list_adapters(only_enabled=only_enabled):
        try:
            out[adapter.name] = adapter.search(query, limit=cap)
        except Exception as e:
            out[adapter.name] = {"error": str(e), "source": adapter.name}
    return out


def reset_for_tests() -> None:
       with _LOCK:
        _REGISTRY.clear()