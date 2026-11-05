#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for path in (ROOT, SCRAPER):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest
pytest.importorskip("course_builder", reason="external course_builder module not installed")
import course_builder  # noqa: E402
import course_spec  # noqa: E402
import site_render  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def _build(tmp_path: Path):
    course = course_spec.load_course(FIX)
    report = course_builder.build_course(course, tmp_path)
    assert not report.errors, report.errors
    return course


def _module_page(tmp_path: Path, number: int) -> str:
    matches = list((tmp_path / "course" / "modules").glob(
        f"{number:02d}-*/index.html"))
    assert len(matches) == 1, matches
    return matches[0].read_text(encoding="utf-8")


def test_guide_sources_are_collapsed_with_clickable_bare_urls(tmp_path):
    _build(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<details class='sources'>" in page
    assert "<summary>Sources (2)</summary>" in page

    assert 'href="https://example.gov/doc"' in page
    assert 'href="https://example.org/paper"' in page


def test_course_map_bibliography_is_collapsed(tmp_path):
    _build(tmp_path)
    page = (tmp_path / "course" / "index.html").read_text(encoding="utf-8")
    assert "<details class='sources'>" in page
    assert "<summary>Bibliography (" in page


def test_internal_links_rewrite_at_module_depth():
    html = site_render.rewrite_internal_links(
        "<a href='course/modules/02-memory/'>next</a>"
        "<a href='course/glossary/'>glossary</a>"
        "<a href='../../glossary'>glossary two</a>"
        "<a href='index.html#top'>self</a>",
        page_rel="course/modules/01-why/index.html")
    assert "href='../02-memory/index.html'" in html
    assert "href='../../glossary/index.html'" in html
    assert "href='index.html#top'" in html


def test_internal_links_rewrite_from_guide_root():
    html = site_render.rewrite_internal_links(
        "<a href='course/modules/01-why/'>m</a>"
        "<a href='course/glossary/'>g</a>"
        "<a href='https://example.org/x'>e</a>"
        "<a href='#content'>skip</a>",
        page_rel="index.html")
    assert "href='course/modules/01-why/index.html'" in html
    assert "href='course/glossary/index.html'" in html
    assert "href='https://example.org/x'" in html
    assert "href='#content'" in html


def test_built_module_links_resolve_from_its_own_directory(tmp_path):

    src = tmp_path / "course-src"
    shutil.copytree(FIX, src)
    body = src / "modules" / "01-why.md"
    body.write_text(
        body.read_text(encoding="utf-8")
        + "\n\nSee [module two](course/modules/02-memory/).\n",
        encoding="utf-8")
    course = course_spec.load_course(src)
    course_builder.build_course(course, tmp_path / "site")
    page = (tmp_path / "site" / "course" / "modules"
            / "01-why" / "index.html").read_text(encoding="utf-8")
    assert "href='../02-memory/index.html'" in page
    assert "course/modules/02-memory" not in page


def test_tables_get_caption_from_nearest_heading_and_column_scope():
    html, _ = site_render.render_markdown(
        "## Telemetry\n\n### Event classes\n\n"
        "| Event | Meaning |\n|---|---|\n| 1 | Process Create |\n")
    assert "<caption class='sr-only'>Table: Event classes</caption>" in html
    assert '<th scope="col">Event</th>' in html
    assert "<div class='tablewrap'><table>" in html


def test_no_video_note_appears_once_and_only_in_watch(tmp_path):
    src = tmp_path / "course-src"
    shutil.copytree(FIX, src)
    body = src / "modules" / "01-why.md"
    body.write_text(
        body.read_text(encoding="utf-8")
        + "\n\nNo verified video for this module. The readings carry the "
          "evidence above.\n",
        encoding="utf-8")
    course = course_spec.load_course(src)

    modules = tuple(replace(m, videos=()) if m.number == 1 else m
                    for m in course.modules)
    course = replace(course, modules=modules)
    course_builder.build_course(course, tmp_path / "site")
    page = (tmp_path / "site" / "course" / "modules"
            / "01-why" / "index.html").read_text(encoding="utf-8")
    assert page.count("No verified video for this module") == 1

    assert "The readings carry the evidence above." in page


def test_no_worked_example_placeholder_is_suppressed(tmp_path):
    _build(tmp_path)
    page = _module_page(tmp_path, 1)
    assert "No worked example is recorded" not in page
    assert "Worked examples" not in page


def test_module_pages_have_prev_next_navigation(tmp_path):
    _build(tmp_path)
    page = _module_page(tmp_path, 2)
    assert "modnav" in page
    assert "rel='prev'" in page and "rel='next'" in page
    assert "href='../01-why/index.html'" in page
    assert "href='../03-powershell/index.html'" in page
    assert "Course map" in page


def test_course_pages_share_wide_shell_print_and_motion_contract():
    css = site_render.CSS
    assert "--shell:80%" in css
    assert "--maxw:1500px" in css
    assert "width:var(--shell)" in css
    assert "@media print" in css
    assert "@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}" in css
    assert "white-space:pre" in css
    assert "overflow-x:auto" in css
    assert ".sr-only" in css
    assert "details.sources" in css
    assert ".modnav" in css

    assert "width:100%;max-width:none" in css


def test_course_pages_have_lang_description_focus_and_skip_link(tmp_path):
    _build(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in page
    assert '<meta name="description"' in page
    assert 'class="skip" href="#content"' in page
    assert ":focus-visible" in page
