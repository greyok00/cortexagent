#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("page_clean", reason="external greysearch module not installed")
from lib.scraper import greysearch_mcp as gm  # noqa: E402
from lib.scraper import page_clean  # noqa: E402
from lib.scraper import relevance  # noqa: E402
from lib.scraper import searx_fallback  # noqa: E402


def test_thin_fill_judge_sees_cleaned_fields(monkeypatch):
    query = "how to detect ransomware"
    result = {}
    cleaned = {
        "canonical_url": "https://good.example/ransomware",
        "title": "Ransomware detection guide",
        "h2s": ["Isolate the infected hosts", "Report the incident"],
        "excerpt": ("Isolate the infected hosts and report the incident to the "
                    "authorities."),
        "body_text": ("Isolate the infected hosts.\n\nReport the incident to "
                      "the authorities."),
    }

    class FakeBridge:
        def _extract_domain(self, url):
            return "good.example"

        def _get_tier(self, domain):
            return "primary"

        def research_scrape(self, url):
            return {"ok": True, "url": url, "title": "Wrapper title",
                    "tier": "primary", "domain": "good.example",
                    "text": "raw text the judge must not need"}

    monkeypatch.setattr(gm, "get_bridge", lambda: FakeBridge())
    monkeypatch.setattr(
        searx_fallback, "search",
        # live ladder call passes engines= (engine picker split); fake must match
        lambda q, max_results=10, engines=None: {
            "ok": True, "source": "test-ladder",
            "results": [{"url": "https://good.example/ransomware",
                         "title": "Wrapper title",
                         "content": "ransomware detection",
                         "domain": "good.example"}]})
    monkeypatch.setattr(relevance, "prefilter",
                        lambda *a, **k: {"decision": "keep", "reason": "on topic"})
    monkeypatch.setattr(page_clean, "clean_page", lambda sr: cleaned)
    monkeypatch.setattr(page_clean, "is_thin", lambda c: False)
    monkeypatch.setattr(relevance, "judge_available", lambda: True)

    seen = {}

    def fake_judge(q, pages):
        seen["query"] = q
        seen["page"] = pages[0]
        return [{"decision": "accept", "relevance_score": 90,
                 "source_type": "official_docs", "reason": "on topic"}]

    monkeypatch.setattr(relevance, "judge_pages", fake_judge)

    gm._thin_fill(query, result)

    judged = seen["page"]
    assert seen["query"] == query
    assert judged["h2s"] == ["Isolate the infected hosts",
                             "Report the incident"]
    assert "isolate the infected hosts" in judged["excerpt"].lower()
    assert "report the incident" in judged["body_text"].lower()
    assert judged["canonical_url"] == "https://good.example/ransomware"


    accepted = result["pages_fetched"][0]
    assert accepted["relevance"]["decision"] == "accept"
    assert accepted["clean"] is cleaned
    assert "h2s" not in accepted
    assert result["fill_lane"]["accepted"] == 1
