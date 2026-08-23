#!/usr/bin/env python3
"""base.py — Adapter contract for the API proxy layer.

Every external search/lookup backend plugs into cortexagent by subclassing
BaseAdapter and dropping the module under lib/adapters/. Self-registration
happens on import via lib/adapters/__init__.py.

Methods are explicit (not implicit ABC contract) so a typo fails loudly
at instantiation rather than silently returning NotImplementedError.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseAdapter(ABC):
    """Abstract base for all API proxy adapters.

    Subclasses must set `name` (unique, kebab-or-snake) and may override
    `description`. `enabled` is computed at __init__ from env / config.
    """

    name: str = ""
    description: str = ""
    enabled: bool = False

    @abstractmethod
    def authenticate(self) -> bool:
        """Return True if credentials are present + valid (cheap check).

        Must NOT make a network call; use health_check() for live probes.
        """

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Run a search/lookup. Each result: {"title", "url", "snippet", "source"}.

        May raise — callers should handle exceptions per-adapter.
        """

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Probe the backend live. Return {"status": "ok"|"error"|"disabled",
        "detail": str, ...extra}.
        """

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe summary for `adapter_list` tool surface."""
        return {
            "name": self.name,
            "description": self.description,
            "enabled": bool(self.enabled),
            "health": self.health_check(),
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} enabled={self.enabled}>"