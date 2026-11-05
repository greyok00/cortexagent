#!/usr/bin/env python3


from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRAPER = ROOT / "lib" / "scraper"
for p in (str(ROOT), str(SCRAPER)):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("searxng_integrated", reason="external greysearch module not installed")
import searxng_integrated as sx  # noqa: E402

QUERY = "infostealer banking trojan"

FISH_RESULTS = [
    {"url": f"https://recipes.example/fish-{i}",
     "title": f"Fish recipe {i}: baked salmon",
     "content": "A dictionary of fish recipes. Season, bake, serve."}
    for i in range(6)
]
TOPICAL_RESULTS = [
    {"url": f"https://security.example/infostealer-{i}",
     "title": f"Infostealer banking trojan analysis {i}",
     "content": "How the banking trojan steals credentials."}
    for i in range(4)
]


class FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _manager(monkeypatch, local_results, public_results):
    mgr = sx.SearXNGEngineManager(searxng_urls=["http://127.0.0.1:8888"])

    monkeypatch.setattr(sx, "_local_alive", lambda *a, **k: True)
    monkeypatch.setattr(mgr, "get_working_engines", lambda: ["google"])
    monkeypatch.setattr(mgr, "_discover_public_instances",
                        lambda max_instances=6: ["https://pub.example"])

    def fake_urlopen(req, timeout=0):
        url = getattr(req, "full_url", str(req))
        if "127.0.0.1:8888" in url:
            return FakeResponse({"results": local_results})
        if "pub.example" in url:
            return FakeResponse({"results": public_results})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(sx.urllib.request, "urlopen", fake_urlopen)
    return mgr






def test_looks_topical_rejects_fish_for_security_query():
    assert sx._looks_topical(QUERY, FISH_RESULTS) is False
    assert sx._looks_topical(QUERY, TOPICAL_RESULTS) is True


def test_looks_topical_ignores_stopword_only_query():

    assert sx._looks_topical("how to 2026", FISH_RESULTS) is True
    assert sx._looks_topical(QUERY, []) is True


def test_looks_topical_prefix_match():
    results = [{"title": "Infostealers and banking trojans",
                "content": "", "url": "https://x.example/a"}]
    assert sx._looks_topical(QUERY, results) is True






def test_offtopic_local_lane_escalates_to_public(monkeypatch):
    mgr = _manager(monkeypatch, FISH_RESULTS, TOPICAL_RESULTS)
    out = mgr.search(QUERY, max_results=3)

    assert out["ok"] is True
    assert any(entry.startswith("local: off-topic (6 results)")
               for entry in out["ladder"]), out["ladder"]
    assert not any("local: 6 results" in entry for entry in out["ladder"])
    assert any(entry.startswith("searx.space: total after lane")
               for entry in out["ladder"]), out["ladder"]

    assert out["results"]
    assert all("fish" not in (r["title"] or "").lower()
               and "fish" not in (r["url"] or "").lower()
               for r in out["results"])
    assert all("infostealer" in (r["title"] or "").lower()
               for r in out["results"])


def test_topical_local_lane_is_accepted(monkeypatch):
    mgr = _manager(monkeypatch, TOPICAL_RESULTS, [])
    out = mgr.search(QUERY, max_results=3)

    assert out["ok"] is True
    assert any("local: 4 results" in entry for entry in out["ladder"]), out["ladder"]
    assert not any("off-topic" in entry for entry in out["ladder"])
    assert len(out["results"]) == 3


def test_offtopic_public_instance_is_skipped(monkeypatch):

    mgr = sx.SearXNGEngineManager(searxng_urls=["http://127.0.0.1:8888"])
    monkeypatch.setattr(sx, "_local_alive", lambda *a, **k: False)
    monkeypatch.setattr(mgr, "_discover_public_instances",
                        lambda max_instances=6: ["https://pub.example"])

    def fake_urlopen(req, timeout=0):
        return FakeResponse({"results": FISH_RESULTS})

    monkeypatch.setattr(sx.urllib.request, "urlopen", fake_urlopen)

    out = mgr.search(QUERY, max_results=3)
    assert out["results"] == []
    assert any("off-topic results dropped" in entry for entry in out["ladder"]), \
        out["ladder"]
