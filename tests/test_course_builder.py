#!/usr/bin/env python3
from __future__ import annotations

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
pytest.importorskip("course_builder", reason="external course_builder module not installed")
import course_builder  # noqa: E402
import course_spec  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def test_build_course_writes_guide_course_and_ten_modules(tmp_path):
    course = course_spec.load_course(FIX)
    report = course_builder.build_course(course, tmp_path)
    assert not report.errors
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "course" / "index.html").exists()
    assert (tmp_path / "course" / "glossary" / "index.html").exists()
    for n in range(1, 11):
        matches = list((tmp_path / "course" / "modules").glob(f"{n:02d}-*/index.html"))
        assert len(matches) == 1, (n, matches)
    guide = (tmp_path / "index.html").read_text()
    assert "Guide" in guide and "Course" in guide
    assert "<script" not in guide.lower()
    assert len(report.pages) == 13


def test_module_page_contains_readings_videos_and_assignment(tmp_path):
    course = course_spec.load_course(FIX)
    course_builder.build_course(course, tmp_path)
    page = next((tmp_path / "course" / "modules").glob("01-*/index.html")).read_text()
    assert "Required reading" in page
    assert "Watch" in page
    assert "Assignment" in page
    assert "Rubric" in page


def test_module_page_keeps_reading_and_glossary_links(tmp_path):
    course = course_spec.load_course(FIX)
    course_builder.build_course(course, tmp_path)
    page = next((tmp_path / "course" / "modules").glob("01-*/index.html")).read_text()
    assert "https://example.org/paper" in page
    assert "https://youtu.be/example" in page
    assert "glossary/index.html#term-signature" in page


def test_course_map_has_ten_module_cards_with_issue_lessons_and_visuals(tmp_path):
    course = course_spec.load_course(FIX)
    course_builder.build_course(course, tmp_path)
    page = (tmp_path / "course" / "index.html").read_text()
    assert page.count("class='mcard'") == 10
    assert "The old model assumes files." in page
    assert "The assumption" in page
    assert "problem_set" in page
    assert "Tables/diagrams:" in page
    assert "modules/01-why/index.html" in page


def test_glossary_page_has_anchors_and_module_links(tmp_path):
    course = course_spec.load_course(FIX)
    course_builder.build_course(course, tmp_path)
    page = (tmp_path / "course" / "glossary" / "index.html").read_text()
    assert "id='term-signature'" in page
    assert "reusable pattern" in page
    assert "../modules/01-why/index.html" in page


def test_nav_tabs_marks_the_active_view_and_orders_guide_first():
    html = course_builder.nav_tabs("course", "course/index.html", "index.html")
    assert html.index(">Guide<") < html.index(">Course<")
    assert "class='tab active' href='course/index.html'>Course</a>" in html
    assert "class='tab' href='index.html'>Guide</a>" in html


def test_nav_tabs_without_a_course_is_one_tab():
    html = course_builder.nav_tabs("guide", "", "index.html")
    assert ">Guide<" in html
    assert ">Course<" not in html
