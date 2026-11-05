#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
pytest.importorskip("course_batch", reason="external course_batch module not installed")
import course_batch  # noqa: E402
import course_spec  # noqa: E402
import yaml  # noqa: E402


def _write_manifest(tmp_path: Path, topics: list[dict],
                    queued: list[dict] | None = None) -> Path:
    data: dict = {"topics": topics}
    if queued is not None:
        data["queued"] = queued
    path = tmp_path / "topics.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _topics(count: int = 3, family: str = "malware") -> list[dict]:
    return [
        {"family": family, "slug": f"topic-{i}", "query": f"query {i}",
         "scope": "scope", "entities": [], "mode": "validate"}
        for i in range(1, count + 1)
    ]


def test_batch_stops_on_first_failure(tmp_path, monkeypatch):
    calls = []

    def fake_run(topic, *a, **k):
        calls.append(topic)
        return 1 if len(calls) == 2 else 0

    monkeypatch.setattr(course_batch, "run_one", fake_run)
    report = course_batch.run_batch(_write_manifest(tmp_path, _topics(3)),
                                    stop_on_failure=True)

    assert len(calls) == 2
    assert report["stopped_on"] == 2
    assert report["processed"] == 2
    assert [t["status"] for t in report["topics"]] == ["pass", "fail"]


def test_report_json_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(course_batch, "run_one",
                        lambda topic, *a, **k: 0)
    course_batch.run_batch(_write_manifest(tmp_path, _topics(2)))

    path = tmp_path / "batch-report.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ok"] is True
    assert saved["stopped_on"] is None
    assert saved["processed"] == 2
    assert saved["manifest"] == str(tmp_path / "topics.yaml")
    assert [t["slug"] for t in saved["topics"]] == ["topic-1", "topic-2"]


def test_exception_in_topic_is_recorded_and_report_written(tmp_path,
                                                           monkeypatch):
    calls = []

    def exploding(topic, *a, **k):
        calls.append(topic)
        if len(calls) == 2:
            raise RuntimeError("bad course.yaml")
        return 0

    monkeypatch.setattr(course_batch, "run_one", exploding)
    report = course_batch.run_batch(_write_manifest(tmp_path, _topics(3)))

    assert report["processed"] == 2
    assert report["stopped_on"] == 2
    assert [t["status"] for t in report["topics"]] == ["pass", "error"]
    assert any("RuntimeError" in issue and "bad course.yaml" in issue
               for issue in report["topics"][1]["issues"])
    saved = json.loads((tmp_path / "batch-report.json").read_text(
        encoding="utf-8"))
    assert saved["topics"][1]["status"] == "error"
    assert saved["failures"] == 1
    assert saved["ok"] is False


def test_empty_selection_fails_unless_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(course_batch, "run_one", lambda *a, **k: 0)
    path = _write_manifest(tmp_path, _topics(2))

    report = course_batch.run_batch(path, only="no-such-topic")
    assert report["empty_selection"] is True
    assert report["processed"] == 0
    assert report["ok"] is False
    assert (tmp_path / "batch-report.json").exists()

    allowed = course_batch.run_batch(path, only="no-such-topic",
                                     allow_empty=True)
    assert allowed["empty_selection"] is True
    assert allowed["ok"] is True

    assert course_batch.main([str(path), "--only", "no-such-topic"]) == 1
    assert course_batch.main([str(path), "--only", "no-such-topic",
                              "--allow-empty"]) == 0


def test_continue_on_failure_visits_every_topic(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        course_batch, "run_one",
        lambda topic, *a, **k: calls.append(topic) or 1)
    report = course_batch.run_batch(_write_manifest(tmp_path, _topics(3)),
                                    stop_on_failure=False)

    assert len(calls) == 3
    assert report["stopped_on"] is None
    assert report["failures"] == 3
    assert report["ok"] is False


def test_validate_mode_does_not_call_course_cli_run(tmp_path, monkeypatch):
    composed = []
    monkeypatch.setattr(course_batch.course_cli, "run",
                        lambda *a, **k: composed.append(a) or 0)

    def missing_course(path):
        raise course_spec.CourseSpecError([f"missing course.yaml in {path}"])

    monkeypatch.setattr(course_batch.course_spec, "load_course",
                        missing_course)

    report = course_batch.run_batch(_write_manifest(tmp_path, _topics(1)))

    assert composed == []
    assert report["topics"][0]["status"] == "fail"
    assert "missing course.yaml" in report["topics"][0]["issues"][0]
    assert report["stopped_on"] == 1


def test_include_queued_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(course_batch, "run_one",
                        lambda topic, *a, **k: 0)
    path = _write_manifest(
        tmp_path, _topics(2),
        queued=[{"family": "finance", "slug": "", "mode": "compose",
                 "note": "future work"}])

    without = course_batch.run_batch(path, include_queued=False)
    with_queued = course_batch.run_batch(path, include_queued=True)

    assert without["processed"] == 2
    assert with_queued["processed"] == 3
    assert with_queued["topics"][-1]["family"] == "finance"


def test_only_filters_by_family_and_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(course_batch, "run_one",
                        lambda topic, *a, **k: 0)
    path = _write_manifest(tmp_path, _topics(2) + [
        {"family": "finance", "slug": "markets", "mode": "validate"}])

    by_family = course_batch.run_batch(path, only="finance")
    by_slug = course_batch.run_batch(path, only="topic-2")
    by_path = course_batch.run_batch(path, only="malware/topic-1")

    assert [t["slug"] for t in by_family["topics"]] == ["markets"]
    assert [t["slug"] for t in by_slug["topics"]] == ["topic-2"]
    assert [t["slug"] for t in by_path["topics"]] == ["topic-1"]


def test_queued_topic_without_slug_fails_without_composing(tmp_path,
                                                           monkeypatch):
    composed = []
    monkeypatch.setattr(course_batch.course_cli, "run",
                        lambda *a, **k: composed.append(a) or 0)

    topic = {"family": "finance", "slug": "", "mode": "compose",
             "note": "future work"}
    assert course_batch.run_one(topic, courses_root=tmp_path) == 1
    assert composed == []
    assert "manual authoring" in topic["issues"][0]
