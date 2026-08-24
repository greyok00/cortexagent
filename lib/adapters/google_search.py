#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from .base import BaseAdapter
from .registry import register

ENDPOINT = "https://www.googleapis.com/customsearch/v1"
TIMEOUT = 15.0
MAX_NUM = 10


class GoogleCustomSearchAdapter(BaseAdapter):
    name = "google_cse"
    description = "Google Custom Search JSON API (GOOGLE_API_KEY + GOOGLE_CSE_ID)"

    def __init__(self) -> None:
        self.api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        self.cse_id = os.environ.get("GOOGLE_CSE_ID", "").strip()
        self.enabled = bool(self.api_key and self.cse_id)


    def authenticate(self) -> bool:
        return self.enabled

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("google_cse disabled (GOOGLE_API_KEY/GOOGLE_CSE_ID unset)")
        num = max(1, min(int(limit), MAX_NUM))
        params = urllib.parse.urlencode({
            "q": query,
            "key": self.api_key,
            "cx": self.cse_id,
            "num": num,
            "safe": "off",
        })
        url = f"{ENDPOINT}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "cortexagent-adapter/google_cse (+local)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.load(r)
        items = payload.get("items") or []
        out: List[Dict[str, Any]] = []
        for it in items:
            out.append({
                "title": it.get("title", ""),
                "url": it.get("link", ""),
                "snippet": it.get("snippet", ""),
                "source": self.name,
            })
        return out

    def health_check(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled",
                    "detail": "GOOGLE_API_KEY / GOOGLE_CSE_ID not set"}

        try:
            params = urllib.parse.urlencode({
                "q": "test",
                "key": self.api_key,
                "cx": self.cse_id,
                "num": 1,
            })
            url = f"{ENDPOINT}?{params}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "cortexagent-adapter/google_cse (+local)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                code = r.getcode()
            return {"status": "ok" if code == 200 else "error", "http": code}
        except urllib.error.HTTPError as e:
            return {"status": "error", "http": e.code, "detail": str(e)[:200]}
        except Exception as e:
            return {"status": "error", "detail": str(e)[:200]}



register(GoogleCustomSearchAdapter())