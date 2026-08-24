#!/usr/bin/env python3

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseAdapter(ABC):


    name: str = ""
    description: str = ""
    enabled: bool = False

    @abstractmethod
    def authenticate(self) -> bool:
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        pass

    def to_dict(self) -> Dict[str, Any]:

        return {
            "name": self.name,
            "description": self.description,
            "enabled": bool(self.enabled),
            "health": self.health_check(),
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} enabled={self.enabled}>"