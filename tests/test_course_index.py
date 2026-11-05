#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from dataclasses import replace
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
pytest.importorskip("course_index", reason="external course_index module not installed")
import course_index  # noqa: E402
import course_spec  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def _course(**changes):

    return replace(course_spec.load_course(FIX), **changes)


def _category_headings(section: str) -> list[str]:
    return re.findall(r"<h3>([^<]+)</h3>", section)


def test_course_card_shows_title_modules_and_visuals():
    course = course_spec.load_course(FIX)
    card = course_index.course_card(course, "course/index.html")
    assert course.title in card
    assert "10 modules" in card
    assert "Guide + Course" in card
    assert "0 visuals" in card
    assert 'href="course/index.html"' in card


def test_course_card_escapes_href():
    course = course_spec.load_course(FIX)
    card = course_index.course_card(
        course, "course/index.html?a=1&b=2")
    assert "?a=1&amp;b=2" in card


def test_build_hub_writes_course_section(tmp_path):
    course = course_spec.load_course(FIX)
    course_index.build_hub([course], tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")
    assert 'id="courses"' in section
    assert course.title in section
    assert "10 modules" in section
    assert "site/course/index.html" in section


def test_build_hub_empty_state(tmp_path):
    course_index.build_hub([], tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")
    assert "Nothing published here yet." in section


def test_display_category_family_map():
    expected = {
        "malware": "Cyber",
        "finance": "Finance",
        "osint-pi": "OSINT",
        "web-design": "Web Design",
    }
    for family, category in expected.items():
        assert course_index.display_category(_course(family=family)) == category


def test_display_category_explicit_manifest_value_wins():
    course = _course(family="malware", category="Finance")
    assert course_index.display_category(course) == "Finance"


def test_build_hub_groups_two_families_under_their_categories(tmp_path):
    cyber = _course(family="malware", title="Fileless Detection Course")
    finance = _course(
        family="finance", slug="finance-course", title="Portfolio Risk Course")
    course_index.build_hub([cyber, finance], tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")

    cyber_at = section.index("<h3>Cyber</h3>")
    finance_at = section.index("<h3>Finance</h3>")
    assert cyber_at < finance_at

    assert cyber_at < section.index("Fileless Detection Course") < finance_at
    assert section.index("Portfolio Risk Course") > finance_at


def test_build_hub_skips_empty_categories(tmp_path):
    course_index.build_hub([_course(family="malware")], tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")
    headings = _category_headings(section)
    assert headings == ["Cyber"]


def test_build_hub_orders_the_four_categories(tmp_path):
    courses = [_course(family=family, slug=family)
               for family in ("web-design", "finance", "malware", "osint-pi")]
    course_index.build_hub(courses, tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")
    assert _category_headings(section) == [
        "Cyber", "Finance", "OSINT", "Web Design"]


def test_build_hub_has_no_status_bucket_headings(tmp_path):
    courses = [_course(family=family, slug=family)
               for family in ("malware", "finance", "osint-pi", "web-design")]
    course_index.build_hub(courses, tmp_path)
    section = (tmp_path / "courses.html").read_text(encoding="utf-8")
    headings = [h.lower() for h in _category_headings(section)]
    for forbidden in ("saved", "recovered", "earlier"):
        assert forbidden not in headings
