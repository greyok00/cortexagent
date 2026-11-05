#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
pytest.importorskip("research_integration", reason="external greysearch module not installed")
import research_integration as ri  # noqa: E402


def test_judge_batch_judges_cleaned_view_and_keeps_original_page(monkeypatch):
    page = {
        "url": "https://www.cisa.gov/stopransomware/how-to-respond",
        "title": "Wrapper title",
        "text": "raw text the judge must not need",
        "clean": {
            "canonical_url": "https://www.cisa.gov/stopransomware/how-to-respond",
            "title": "How to Respond to Ransomware",
            "h2s": ["Isolate the infected systems", "Report the incident"],
            "excerpt": ("Step 1: isolate the infected systems from the network. "
                        "Step 2: report the incident to CISA."),
            "body_text": ("Step 1: isolate the infected systems from the "
                          "network.\n\nStep 2: report the incident to CISA."),
        },
    }
    seen = {}

    def fake_judge(question, pages):
        seen["question"] = question
        seen["page"] = pages[0]
        return [{"decision": "accept", "relevance_score": 90,
                 "source_type": "official_docs", "reason": "on topic"}]

    monkeypatch.setattr(ri._relevance, "judge_pages", fake_judge)

    decisions = ri._judge_batch("how to respond to ransomware", [page])

    judged = seen["page"]
    assert seen["question"] == "how to respond to ransomware"
    assert judged["h2s"] == ["Isolate the infected systems",
                             "Report the incident"]
    assert "isolate the infected systems" in judged["excerpt"].lower()
    assert "report the incident" in judged["body_text"].lower()
    assert judged["canonical_url"].startswith("https://www.cisa.gov/")


    assert decisions[0]["decision"] == "accept"
    assert page["relevance"] is decisions[0]
    assert "h2s" not in page
    assert page["clean"]["h2s"] == ["Isolate the infected systems",
                                    "Report the incident"]


def test_judge_view_passes_through_pages_without_clean():
    page = {"url": "https://example.org/a", "title": "Already flat"}
    assert ri._judge_view(page) is page
