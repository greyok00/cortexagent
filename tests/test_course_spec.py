#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("course_spec", reason="external course_spec module not installed")
import course_spec  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def test_load_valid_course():
    course = course_spec.load_course(FIX)
    assert course.slug == "proof-course"
    assert len(course.modules) == 10
    assert course.modules[0].number == 1
    assert course.modules[-1].number == 10
    assert course.modules[0].readings[0].type == "official_docs"


def test_manifest_requires_exactly_ten_modules(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    data = yaml.safe_load((dst / "course.yaml").read_text())
    data["modules"] = data["modules"][:9]
    (dst / "course.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("exactly 10" in e for e in exc.value.errors)


def test_manifest_rejects_duplicate_slugs(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    data = yaml.safe_load((dst / "course.yaml").read_text())
    data["modules"][1]["slug"] = data["modules"][0]["slug"]
    (dst / "course.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("duplicate slug" in e for e in exc.value.errors)


def test_manifest_rejects_bad_assignment_type(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    data = yaml.safe_load((dst / "course.yaml").read_text())
    data["modules"][0]["assignments"][0]["type"] = "quiz"
    (dst / "course.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("assignment type" in e for e in exc.value.errors)


def test_manifest_rejects_more_than_four_lessons(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    data = yaml.safe_load((dst / "course.yaml").read_text())
    data["modules"][0]["lessons"] = ["One", "Two", "Three", "Four", "Five"]
    (dst / "course.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("2-4 lessons" in e for e in exc.value.errors)


def test_manifest_requires_numbers_one_to_ten(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    data = yaml.safe_load((dst / "course.yaml").read_text())
    data["modules"][-1]["number"] = 11
    (dst / "course.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("module numbers must be 1..10" in e for e in exc.value.errors)


def test_manifest_requires_guide_file(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    (dst / "guide.md").unlink()
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("guide.md" in e for e in exc.value.errors)


def test_manifest_requires_module_body_file(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    (dst / "modules" / "01-why.md").unlink()
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("01-why.md" in e for e in exc.value.errors)


def test_manifest_requires_glossary_file(tmp_path):
    dst = tmp_path / "c"
    shutil.copytree(FIX, dst)
    (dst / "glossary.yaml").unlink()
    with pytest.raises(course_spec.CourseSpecError) as exc:
        course_spec.load_course(dst)
    assert any("glossary.yaml" in e for e in exc.value.errors)


def test_valid_course_has_no_validation_errors():
    course = course_spec.load_course(FIX)
    assert course_spec.validate_manifest(course) == []
