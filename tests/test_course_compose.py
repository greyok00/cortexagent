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

pytest.importorskip("course_compose", reason="external course_compose module not installed")
import course_compose  # noqa: E402
import course_spec  # noqa: E402

FIX = Path(HERE) / "fixtures" / "course-valid"


def test_plan_course_returns_ten_high_level_issues(monkeypatch):
    calls = []
    def fake_call(prompt):
        calls.append(prompt)
        return "\n".join(f"ISSUE {i}: High-level issue {i}" for i in range(1, 11))
    plan = course_compose.plan_course(
        "fileless malware", "Windows detection", [], fake_call)
    assert len(plan.modules) == 10
    assert plan.modules[0].title.startswith("High-level issue")


def test_compose_topic_writes_files_and_manifest(tmp_path):
    topic = tmp_path / "topic"
    topic.mkdir()
    def fake_call(prompt):
        if "MODULE 1" in prompt:
            return "### Lesson one\n\nText.\n\n### Lesson two\n\nText.\n"
        if "GUIDE" in prompt:
            return ("# Guide\n\n## The short answer\n\nText.\n\n## How it works\n\nText.\n"
                    "## Evidence and disagreements\n\nText.\n\n## Procedure\n\nText.\n"
                    "## Verify it worked\n\nText.\n\n## Failure modes\n\nText.\n"
                    "## Limits and what this does not cover\n\nText.\n\n## Sources\n\n"
                    "[1] https://example.gov/doc\n")
        return "### Lesson one\n\nText.\n\n### Lesson two\n\nText.\n"
    course_compose.compose_topic(topic, [], fake_call)
    assert (topic / "course.yaml").exists()
    assert (topic / "guide.md").exists()
    assert len(list((topic / "modules").glob("*.md"))) == 10






def test_plan_course_parses_lessons_terms_and_guide_sections():
    def fake_call(prompt):
        lines = [
            "ISSUE 1: Detection assumes code lives in files.",
            "LESSONS: Signature model | Fileless execution | Measurement",
            "TERMS: signature, fileless",
            "SECTIONS: How it works | Procedure",
        ]
        lines += [f"ISSUE {i}: Issue {i}" for i in range(2, 11)]
        return "\n".join(lines)

    plan = course_compose.plan_course(
        "fileless malware", "Windows detection", [], fake_call)
    first = plan.modules[0]
    assert first.lessons == (
        "Signature model", "Fileless execution", "Measurement")
    assert "signature" in first.key_terms
    assert "How it works" in first.guide_sections
    assert len(plan.modules) == 10


def test_plan_prompt_requires_primary_literature_and_work():
    prompts = []
    course_compose.plan_course(
        "fileless malware", "Windows detection", [],
        lambda prompt: prompts.append(prompt) or "\n".join(
            f"ISSUE {i}: Issue {i}" for i in range(1, 11)))
    prompt = prompts[0].lower()
    assert "primary literature" in prompt
    assert "measurement" in prompt
    assert "contested" in prompt
    assert "problem set" in prompt or "lab" in prompt


def test_distill_evidence_keeps_only_accepted_pages():
    result = {
        "findings": [
            {"text": "In 2024 the tool blocked 87% of fileless attacks.",
             "source_urls": ["https://example.gov/report?utm=1"]},
        ],
        "pages_fetched": [
            {
                "url": "https://example.gov/report?utm=1",
                "title": "Report",
                "clean": {
                    "canonical_url": "https://example.gov/report",
                    "title": "Report",
                    "body_text": (
                        "Run the command to collect events.\n\n"
                        "In 2024 the tool blocked 87% of fileless attacks."),
                },
                "relevance": {"decision": "accept",
                              "source_type": "official_docs"},
                "videos": [{"src": "https://example.gov/talk",
                            "title": "Briefing"}],
            },
            {
                "url": "https://bad.example/x",
                "title": "Quarantined page",
                "clean": {"body_text": "This must not reach the notes."},
                "relevance": {"decision": "quarantine",
                              "source_type": "news"},
            },
        ],
    }

    notes = course_compose.distill_evidence(result)
    assert len(notes) == 1
    note = notes[0]
    assert note.url == "https://example.gov/report"
    assert note.source_type == "official_docs"
    assert any("87%" in item for item in note.numbers)
    assert any("Run the command" in item for item in note.procedures)
    assert note.videos and note.videos[0].url == "https://example.gov/talk"


def test_compose_module_adds_the_no_video_note_and_keeps_lessons():
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope", modules=[],
        guide_outline=list(course_compose.GUIDE_H2))
    module = course_compose.ModulePlan(
        number=1, slug="one", title="One", high_level_issue="Issue one.",
        objectives=(), lessons=("First lesson", "Second lesson"),
        key_terms=(), guide_sections=("How it works",))
    body = course_compose.compose_module(
        plan, module, [],
        lambda prompt: "### First lesson\n\nText.\n\n### Second lesson\n\nText.\n")
    assert "### First lesson" in body
    assert "No verified video for this module" in body


def test_compose_guide_enforces_the_eight_h2s_in_order():
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope", modules=[],
        guide_outline=list(course_compose.GUIDE_H2))
    guide = course_compose.compose_guide(
        plan, [], lambda prompt: "# Guide\n\n## How it works\n\nText.\n")
    positions = [guide.index(f"## {heading}")
                 for heading in course_compose.GUIDE_H2]
    assert positions == sorted(positions)


def test_reconcile_reports_guide_sections_no_module_supports():
    course = course_spec.load_course(FIX)
    problems = course_compose.reconcile(course)
    assert any("Limits and what this does not cover" in p for p in problems)


def _course_copy(tmp_path: Path) -> Path:
    topic = tmp_path / "course"
    shutil.copytree(FIX, topic)
    return topic


def test_reconcile_treats_empty_videos_as_no_video_state(tmp_path):

    topic = _course_copy(tmp_path)
    manifest_path = topic / "course.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for module in data["modules"]:
        module["videos"] = []
    manifest_path.write_text(yaml.safe_dump(data, sort_keys=False),
                             encoding="utf-8")

    problems = course_compose.reconcile(course_spec.load_course(topic))
    assert not any("no verified video" in problem for problem in problems)


def test_reconcile_does_not_require_a_module_to_support_sources():

    problems = course_compose.reconcile(course_spec.load_course(FIX))
    assert not any(
        "'Sources'" in problem and "not supported" in problem
        for problem in problems)


def test_reconcile_grounds_command_variants_by_program(tmp_path):

    topic = _course_copy(tmp_path)
    module_path = topic / "modules" / "01-why.md"
    module_path.write_text(
        module_path.read_text(encoding="utf-8")
        + "\n`exampletool --init`\n", encoding="utf-8")
    guide_path = topic / "guide.md"
    guide_path.write_text(
        guide_path.read_text(encoding="utf-8").replace(
            "Read the manifest, walk the ten modules, and review the glossary "
            "terms.",
            "Read the manifest, walk the ten modules, and review the glossary "
            "terms. Run `exampletool --status` afterward."),
        encoding="utf-8")

    problems = course_compose.reconcile(course_spec.load_course(topic))
    assert not any("exampletool --status" in problem for problem in problems)


def test_reconcile_allows_guide_sources_beyond_module_readings(tmp_path):

    topic = _course_copy(tmp_path)
    guide_path = topic / "guide.md"
    guide_path.write_text(
        guide_path.read_text(encoding="utf-8")
        + "- Extra direct source, https://example.net/extra-source\n",
        encoding="utf-8")

    problems = course_compose.reconcile(course_spec.load_course(topic))
    assert not any("example.net" in problem for problem in problems)






def _plan_with_terms():
    def fake_call(prompt):
        lines = [
            "ISSUE 1: Detection assumes code lives in files.",
            "TERMS: signature, fileless",
        ]
        lines += [f"ISSUE {i}: Issue {i}" for i in range(2, 11)]
        return "\n".join(lines)

    return course_compose.plan_course(
        "fileless malware", "Windows detection", [], fake_call)


def test_guide_prompt_includes_module_key_terms():
    prompts = []
    plan = _plan_with_terms()
    course_compose.compose_guide(
        plan, [], lambda prompt: prompts.append(prompt) or "# Guide\n")
    prompt = prompts[-1]
    assert "signature" in prompt
    assert "fileless" in prompt
    assert "defined at first use" in prompt.lower()


def test_guide_stubs_are_conditional_on_evidence():
    note = course_compose.EvidenceNote(
        url="https://example.gov/report", title="Report",
        source_type="official_docs")
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope", modules=[],
        guide_outline=list(course_compose.GUIDE_H2))
    guide = course_compose.compose_guide(
        plan, [note],
        lambda prompt: ("# Guide\n\n## The short answer\n\nText.\n\n"
                        "## Sources\n\nNo sources were accepted for this run.\n"))
    assert "Section not generated" in guide
    assert "No command or procedure was captured" not in guide
    assert "No sources were accepted" not in guide
    assert "https://example.gov/report" in guide


def test_guide_stubs_without_evidence_do_not_claim_generation_or_sources():
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope", modules=[],
        guide_outline=list(course_compose.GUIDE_H2))
    guide = course_compose.compose_guide(
        plan, [], lambda prompt: "# Guide\n")
    assert "No evidence notes were accepted for this run." in guide
    assert "Section not generated" not in guide
    assert "https://" not in guide


def test_module_stub_does_not_claim_absence_when_evidence_exists():
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope", modules=[],
        guide_outline=list(course_compose.GUIDE_H2))
    module = course_compose.ModulePlan(
        number=1, slug="one", title="One", high_level_issue="Issue one.",
        lessons=("First lesson", "Second lesson"))
    note = course_compose.EvidenceNote(
        url="https://example.gov/report", title="Report",
        source_type="official_docs")
    body = course_compose.compose_module(
        plan, module, [note], lambda prompt: "Prose with no H3.\n")
    assert "Section not generated" in body
    assert "No verified evidence was captured" not in body
    assert "No verified video for this module" in body
    assert "accepted evidence notes carry no video URL" in body


def test_plan_without_terms_derives_key_terms_from_evidence():
    notes = [course_compose.EvidenceNote(
        url="https://example.gov/report", title="Fileless execution report",
        source_type="official_docs",
        claims=("Telemetry records process creation.",))]

    def fake_call(prompt):
        return "\n".join(f"ISSUE {i}: Issue {i}" for i in range(1, 11))

    plan = course_compose.plan_course(
        "fileless malware", "Windows detection", notes, fake_call)
    assert all(module.key_terms for module in plan.modules)
    assert any("fileless" in term for term in plan.modules[0].key_terms)


def test_key_term_derivation_fails_when_nothing_can_be_derived():
    module = course_compose.ModulePlan(
        number=1, slug="one", title="", high_level_issue="")
    with pytest.raises(ValueError, match="no key term could be derived"):
        course_compose._derive_terms(module, [], "")


def test_placeholder_glossary_definition_is_empty_and_rejected(tmp_path):
    plan = course_compose.CoursePlan(
        topic="topic", scope="scope",
        modules=[course_compose.ModulePlan(
            number=1, slug="one", title="One", high_level_issue="One",
            key_terms=("signature",), guide_sections=("How it works",))],
        guide_outline=list(course_compose.GUIDE_H2))
    glossary = course_compose._compose_glossary(
        plan, [], lambda prompt: "unparseable response")
    assert glossary["signature"]["definition"] == ""

    topic = tmp_path / "course"
    shutil.copytree(FIX, topic)
    data = yaml.safe_load((topic / "glossary.yaml").read_text())
    data["signature"]["definition"] = "Working definition taught in Module 1."
    (topic / "glossary.yaml").write_text(yaml.safe_dump(data))
    problems = course_compose.reconcile(course_spec.load_course(topic))
    assert any("no usable definition" in problem for problem in problems)


def test_readings_come_from_reading_eligible_notes_not_the_top_four():
    notes = [course_compose.EvidenceNote(
        url=f"https://news{i}.example/story",
        title=f"Issue 1 report {i}", source_type="news",
        claims=("Issue 1 report.",)) for i in range(4)]
    notes.append(course_compose.EvidenceNote(
        url="https://example.org/paper", title="Unrelated measured paper",
        source_type="paper", claims=("A measured result.",)))

    def fake_call(prompt):
        return "\n".join(f"ISSUE {i}: Issue {i}" for i in range(1, 11))

    plan = course_compose.plan_course(
        "topic", "scope", notes, fake_call)
    module = plan.modules[0]
    prompt_notes = course_compose._module_notes(module, notes)

    assert all("news" in note.url for note in prompt_notes)
    assert [reading.url for reading in module.readings] == [
        "https://example.org/paper"]
