#!/usr/bin/env python3
"""searxng_adapter.py — SearXNG RSS adapter.

Wraps the existing _web_search SearXNG behaviour as a structured adapter
so `adapter_search` can fan out to the same local instances (:9999 first,
:8888 fallback) without re-implementing the chain. No query behaviour
change vs `lib/tool_registry.py:_web_search` lines 324-345 — same URLs,
same RSS format, same XML regex parse.

Env:
  SEARXNG_URLS  — comma-separated base URLs, default
                  "http://127.0.0.1:9999,http://127.0.0.1:8888"

Always enabled when at least one URL is configured. health_check probes
each URL sequentially with the same timeout.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from .base import BaseAdapter
from .registry import register

TIMEOUT = 15.0
DEFAULT_URLS = ("http://127.0.0.1:9999", "http://127.0.0.1:8888")


def _parse_rss(xml: str) -> List[Dict[str, str]]:
    """Extract (title, link, description) triples from a SearXNG RSS feed."""
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out: List[Dict[str, str]] = []
    for item in items:
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        desc = re.search(r"<description>(.*?)</description>", item, re.S)
        out.append({
            "title": re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else "",
            "url": link.group(1).strip() if link else "",
            "description": re.sub(r"<[^>]+>", "", desc.group(1)).strip() if desc else "",
        })
    return out


def _fetch_rss(base_url: str, query: str, timeout: float = TIMEOUT) -> List[Dict[str, str]]:
    url = (f"{base_url}/search?q={urllib.parse.quote(query)}"
           f"&format=rss&safesearch=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        xml = r.read().decode("utf-8", "replace")
    return _parse_rss(xml)


class SearXNGAdapter(BaseAdapter):
    name = "searxng"
    description = "Local SearXNG (RSS): :9999 first, :8888 fallback. Air-gapped."

    def __init__(self) -> None:
        raw = os.environ.get("SEARXNG_URLS", "").strip()
        if raw:
            self.urls = tuple(u.strip() for u in raw.split(",") if u.strip())
        else:
            self.urls = DEFAULT_URLS
        self.enabled = bool(self.urls)

    # ── contract ───────────────────────────────────────────────────────────
    def authenticate(self) -> bool:
        return self.enabled

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("searxng disabled (no URLs configured)")
        last_err: Exception | None = None
        for base in self.urls:
            try:
                items = _fetch_rss(base, query)[:max(1, int(limit))]
                if items:
                    return [
                        {
                            "title": it["title"],
                            "url": it["url"],
                            "snippet": it["description"][:300],
                            "source": self.name,
                        }
                        for it in items
                    ]
            except Exception as e:
                last_err = e
                continue
        # No instance returned items — bubble up the last error if we have one
        if last_err is not None:
            raise RuntimeError(f"all searxng instances failed: {last_err}")
        return []

    def health_check(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "detail": "no SEARXNG_URLS"}
        for base in self.urls:
            try:
                items = _fetch_rss(base, "test", timeout=5.0)
                return {"status": "ok", "url": base, "items": len(items)}
            except Exception as e:
                continue
        return {"status": "error", "detail": f"no searxng reachable on {self.urls}"}


# ── Self-register on import ──────────────────────────────────────────────────
register(SearXNGAdapter())