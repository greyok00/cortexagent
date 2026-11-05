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
pytest.importorskip("course_spec", reason="external course_spec module not installed")
import course_spec  # noqa: E402
import course_validate as cv  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def test_long_paragraph_fails():
    text = "word " * 91
    issues = cv.check_density(text + ".\n")
    assert any(i.code == "paragraph-too-long" for i in issues)


def test_missing_h3_break_fails():
    text = "\n\n".join(["word " * 60 + "." for _ in range(12)])
    issues = cv.check_density(text)
    assert any(i.code == "no-h3-break" for i in issues)


def test_duplicate_paragraph_fails():
    text = ("This is a substantial paragraph with enough words to be counted.\n\n"
            "This is a substantial paragraph with enough words to be counted.\n")
    issues = cv.check_density(text)
    assert any(i.code == "duplicate-paragraph" for i in issues)


def test_prohibited_marker_fails():
    issues = cv.check_density("**ELI5:** something\n")
    assert any(i.code == "prohibited-marker" for i in issues)


def test_guide_requires_all_h2s():
    issues = cv.check_guide_structure("# T\n\n## How it works\n\ntext\n")
    assert any(i.code == "missing-guide-section" for i in issues)


def test_module_requires_assignment_and_reading():
    course = course_spec.load_course(FIX)
    module = course.modules[0].__class__(
        **{**course.modules[0].__dict__, "assignments": (), "readings": ()})
    issues = cv.check_module(course, module)
    assert any(i.code == "module-no-assignment" for i in issues)
    assert any(i.code == "module-not-enough-readings" for i in issues)


def test_valid_fixture_passes_structure():
    course = course_spec.load_course(FIX)
    assert cv.check_guide_structure(course.guide_path.read_text()) == []
    for module in course.modules:
        assert cv.check_module(course, module) == []


def test_twelve_item_list_does_not_fail_density():
    text = "\n".join(
        f"- Item {i} with a few explanatory words attached" for i in range(12))
    assert cv.check_density(text) == []


def test_twelve_row_table_does_not_fail_density():
    rows = ["| Year | Value |", "|---|---|"]
    rows += [f"| {2000 + i} | {i} |" for i in range(12)]
    assert cv.check_density("\n".join(rows)) == []


def test_check_terms_flags_orphan_and_missing_glossary_term():
    course = course_spec.load_course(FIX)
    glossary_text = (course.glossary_path.read_text()
                     + "\norphanterm:\n  definition: x\n")
    issues = cv.check_terms(course, glossary_text=glossary_text)
    assert any(i.code == "orphan-glossary-term" and i.message == "orphanterm"
               for i in issues)

    module = course.modules[0].__class__(
        **{**course.modules[0].__dict__,
           "key_terms": ("signature", "not-in-glossary")})
    course2 = course.__class__(
        **{**course.__dict__, "modules": (module,) + course.modules[1:]})
    issues2 = cv.check_terms(course2)
    assert any(i.code == "term-not-in-glossary"
               and i.message == "not-in-glossary" for i in issues2)


def test_check_sources_uses_injected_resolver_without_network():
    course = course_spec.load_course(FIX)
    calls = []

    def resolver(url):
        calls.append(url)
        return not url.endswith("/paper")

    issues = cv.check_sources(course, url_resolver=resolver)
    unresolved = [i for i in issues if i.code == "source-unresolved"]
    assert len(unresolved) == 10
    assert all("example.org/paper" in i.message for i in unresolved)
    assert sorted(set(calls)) == [
        "https://example.gov/doc", "https://example.org/paper",
        "https://youtu.be/example"]


def test_guide_sources_urls_are_resolved(tmp_path):

    topic = tmp_path / "course"
    shutil.copytree(FIX, topic)
    guide_path = topic / "guide.md"
    guide_path.write_text(
        guide_path.read_text(encoding="utf-8")
        + "- Dead link, https://dead.invalid/source\n", encoding="utf-8")
    course = course_spec.load_course(topic)

    issues = cv.check_sources(
        course, url_resolver=lambda url: "dead.invalid" not in url)
    dead = [i for i in issues if i.code == "guide-source-unresolved"]
    assert len(dead) == 1
    assert "dead.invalid/source" in dead[0].message
    assert dead[0].path == str(guide_path)


def test_check_visuals_requires_alt_and_caption():
    codes = {i.code for i in
             cv.check_visuals("![diagram](a.png)\n\n![](b.png)\n")}
    assert "image-missing-caption" in codes
    assert "image-missing-alt" in codes


def test_check_visuals_allows_mixed_unit_table():
    text = ("| Asset | Measure |\n|---|---|\n| BTC | $82,359 |\n"
            "| Rate | 5% |\n| Delay | 3 days |\n")
    assert cv.check_visuals(text) == []


def test_check_visuals_accepts_teachable_chart_table():
    text = ("| Cycle | Peak stretch (%) |\n|---|---|\n"
            "| 2011-2013 | 518 |\n| 2013-2017 | 277 |\n| 2017-2021 | 146 |\n")
    assert cv.check_visuals(text) == []


def test_validate_course_reports_issues_and_stats():
    course = course_spec.load_course(FIX)
    report = cv.validate_course(course, url_resolver=lambda url: True)
    assert report.passed is False
    assert report.issues
    assert set(report.stats) == {
        "modules", "guide_words", "module_words", "sources", "images",
        "charts", "issues"}
    assert report.stats["modules"] == 10


class _FakeResponse:
    def __init__(self, code):
        self._code = code

    def getcode(self):
        return self._code

    def read(self, _n):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _fake_urlopen(monkeypatch, head_code, get_code):
    import urllib.error

    calls = []

    def fake(req, timeout=0):
        method = req.get_method()
        calls.append((method, req.headers.get("Range")))
        code = head_code if method == "HEAD" else get_code
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "error", None, None)
        return _FakeResponse(code)

    monkeypatch.setattr(cv.urllib.request, "urlopen", fake)
    return calls


def test_url_resolver_falls_back_to_get_after_head_404(monkeypatch):
    calls = _fake_urlopen(monkeypatch, head_code=404, get_code=200)
    assert cv._default_url_resolver("https://example.com/page") is True
    assert [method for method, _ in calls] == ["HEAD", "GET"]
    assert calls[1][1] == "bytes=0-0"


def test_url_resolver_still_fails_when_head_and_get_are_404(monkeypatch):
    _fake_urlopen(monkeypatch, head_code=404, get_code=404)
    assert cv._default_url_resolver("https://example.com/missing") is False
