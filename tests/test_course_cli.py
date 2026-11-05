#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
pytest.importorskip("course_cli", reason="external course module not installed")
import course_cli  # noqa: E402
import course_validate  # noqa: E402
import relevance  # noqa: E402
import yaml  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"
GUIDE_H2 = [
    "The short answer", "How it works", "Evidence and disagreements",
    "Procedure", "Verify it worked", "Failure modes",
    "Limits and what this does not cover", "Sources",
]


def _mute_research(monkeypatch):
    monkeypatch.setattr(course_cli, "research_deep", lambda *a, **k: {})
    monkeypatch.setattr(course_cli, "compose_topic", lambda *a, **k: None)


def _gate_passing_copy(tmp_path: Path) -> Path:

    topic = tmp_path / "topic"
    shutil.copytree(FIX, topic)

    data = yaml.safe_load((topic / "course.yaml").read_text(encoding="utf-8"))
    data["modules"][0]["guide_sections"] = list(GUIDE_H2)
    for module in data["modules"][1:]:
        module["guide_sections"] = ["How it works"]
    (topic / "course.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    for module in data["modules"]:
        number = module["number"]
        body = (
            f"# {module['title']}\n\n"
            "### The assumption\n\n"
            f"Module {number} examines assumption {number} in one short "
            "paragraph that differs from every other module body so the "
            "duplicate-paragraph gate stays quiet.\n\n"
            "### The failure\n\n"
            f"Module {number} then measures failure {number} in a distinct "
            "second paragraph that carries no number, no command, and no "
            "shared sentence.\n"
        )
        path = topic / "modules" / f"{number:02d}-{module['slug']}.md"
        path.write_text(body, encoding="utf-8")

    guide = (topic / "guide.md").read_text(encoding="utf-8")
    guide = guide.replace(
        "The old model fails", "The signature model, the old model, fails", 1)
    (topic / "guide.md").write_text(guide, encoding="utf-8")
    return topic


def test_run_stops_when_validation_fails(tmp_path, monkeypatch):
    topic = tmp_path / "topic"
    topic.mkdir()
    (topic / "course.yaml").write_text("{}")
    monkeypatch.setattr(course_cli, "research_deep", lambda *a, **k: {})
    monkeypatch.setattr(course_cli, "compose_topic", lambda *a, **k: None)
    rc = course_cli.run(topic, "q", scope="s", required_entities=[], research=False)
    assert rc == 1


def test_run_builds_when_validation_passes(tmp_path, monkeypatch):
    topic = _gate_passing_copy(tmp_path)
    _mute_research(monkeypatch)


    monkeypatch.setattr(course_validate, "_default_url_resolver",
                        lambda url: True)
    rc = course_cli.run(topic, "q", scope="s", required_entities=[],
                        research=False)
    assert rc == 0
    assert (topic / "site" / "index.html").exists()


def test_reconcile_failure_returns_one_without_site(tmp_path, monkeypatch,
                                                    capsys):



    topic = tmp_path / "topic"
    shutil.copytree(FIX, topic)
    _mute_research(monkeypatch)

    class _Passing:
        passed = True
        issues: list = []
        stats: dict = {}

    monkeypatch.setattr(course_cli, "validate_course", lambda *a, **k: _Passing())
    rc = course_cli.run(topic, "q", scope="s", required_entities=[],
                        research=False)
    assert rc == 1
    assert "not supported by any module" in capsys.readouterr().out
    assert not (topic / "site").exists()


def test_validation_failure_returns_one_without_site(tmp_path, monkeypatch,
                                                     capsys):


    topic = tmp_path / "topic"
    shutil.copytree(FIX, topic)
    _mute_research(monkeypatch)
    monkeypatch.setattr(course_cli, "reconcile", lambda course: [])
    monkeypatch.setattr(course_validate, "_default_url_resolver",
                        lambda url: True)
    rc = course_cli.run(topic, "q", scope="s", required_entities=[],
                        research=False)
    assert rc == 1
    assert "duplicate-paragraph" in capsys.readouterr().out
    assert not (topic / "site").exists()


def test_research_gate_passes_scope_and_entities_and_drops_quarantine(
        tmp_path, monkeypatch):
    topic = tmp_path / "topic"
    topic.mkdir()
    good = {"url": "https://good.example/a", "title": "Good",
            "clean": {"canonical_url": "https://good.example/a",
                      "body_text": "In 2024 the tool blocked 87% of attacks."}}
    bad = {"url": "https://bad.example/b", "title": "Bad",
           "clean": {"canonical_url": "https://bad.example/b",
                     "body_text": "Unrelated content."}}
    calls = {}
    captured = {}

    def fake_research(query, **kwargs):
        calls["research"] = (query, kwargs)
        return {"pages_fetched": [good, bad], "findings": [],
                "quarantined_pages": []}

    def fake_judge(query, pages, **kwargs):
        calls["judge"] = (query, list(pages), kwargs)
        return [
            {"decision": "accept", "relevance_score": 90,
             "source_type": "official_docs", "reason": "on topic"},
            {"decision": "quarantine", "relevance_score": 60,
             "source_type": "news", "reason": "off topic"},
        ]

    def fake_distill(result):
        captured["result"] = result
        return []

    monkeypatch.setattr(course_cli, "research_deep", fake_research)
    monkeypatch.setattr(course_cli, "judge_pages", fake_judge)
    monkeypatch.setattr(course_cli, "distill_evidence", fake_distill)
    monkeypatch.setattr(course_cli, "compose_topic", lambda *a, **k: None)

    entities = [["fileless", "in-memory"], ["event log"]]
    course_cli.run(topic, "fileless malware", scope="Windows detection",
                   required_entities=entities, research=True)

    assert calls["research"][1]["max_pages"] == 14
    assert calls["research"][1]["max_total_seconds"] == 280.0
    _, judged_pages, judge_kwargs = calls["judge"]
    assert len(judged_pages) == 2
    assert judge_kwargs["scope"] == "Windows detection"
    assert judge_kwargs["required_entities"] == entities
    assert "official_docs" in judge_kwargs["expected_source_types"]

    pages = captured["result"]["pages_fetched"]
    assert [p["url"] for p in pages] == ["https://good.example/a"]
    assert pages[0]["relevance"]["decision"] == "accept"
    assert captured["result"]["quarantined_pages"][0]["url"] == (
        "https://bad.example/b")


def test_course_gate_flattens_clean_fields_for_the_judge(tmp_path, monkeypatch):

    topic = tmp_path / "topic"
    topic.mkdir()
    page = {
        "url": "https://good.example/a",
        "title": "Wrapper title",
        "clean": {
            "canonical_url": "https://good.example/a",
            "title": "Clean title",
            "h2s": ["Event log analysis", "Detection coverage"],
            "excerpt": "Event log analysis explains detection coverage.",
            "body_text": "Full body about event log analysis and coverage.",
        },
    }
    seen = {}

    def fake_judge(query, pages, **kwargs):
        judged = pages[0]
        seen["h2s"] = judged.get("h2s")
        seen["excerpt"] = judged.get("excerpt")
        seen["body_text"] = judged.get("body_text")
        seen["contamination"] = relevance.contamination_check(
            judged, kwargs["required_entities"])
        return [{"decision": "accept", "relevance_score": 90,
                 "source_type": "official_docs", "reason": "on topic"}]

    monkeypatch.setattr(course_cli, "research_deep",
                        lambda *a, **k: {"pages_fetched": [page],
                                         "findings": []})
    monkeypatch.setattr(course_cli, "judge_pages", fake_judge)
    monkeypatch.setattr(course_cli, "distill_evidence", lambda result: [])
    monkeypatch.setattr(course_cli, "compose_topic", lambda *a, **k: None)

    course_cli.run(topic, "event log analysis", scope="detection",
                   required_entities=[["event log"], ["detection coverage"]],
                   research=True)

    assert seen["h2s"] == ["Event log analysis", "Detection coverage"]
    assert "detection coverage" in seen["excerpt"].lower()
    assert "event log analysis" in seen["body_text"].lower()
    assert seen["contamination"]["clean"] is True


def test_run_writes_topic_and_scope_before_composing(tmp_path, monkeypatch):
    topic = tmp_path / "topic"
    topic.mkdir()
    captured = {}

    def fake_compose(topic_dir, notes, **kwargs):
        captured["topic"] = (topic_dir / "topic.txt").read_text()
        captured["scope"] = (topic_dir / "scope.txt").read_text()

    monkeypatch.setattr(course_cli, "research_deep", lambda *a, **k: {})
    monkeypatch.setattr(course_cli, "compose_topic", fake_compose)

    rc = course_cli.run(topic, "the pinned query", scope="the pinned scope",
                        required_entities=[], research=False)



    assert rc == 1
    assert captured == {"topic": "the pinned query",
                        "scope": "the pinned scope"}


def test_run_returns_one_when_composition_cannot_load(tmp_path, monkeypatch):

    topic = tmp_path / "topic"
    topic.mkdir()
    monkeypatch.setattr(course_cli, "research_deep", lambda *a, **k: {})
    monkeypatch.setattr(course_cli, "compose_topic", lambda *a, **k: None)
    rc = course_cli.run(topic, "q", scope="s", required_entities=[],
                        research=False)
    assert rc == 1
    assert not (topic / "site").exists()
