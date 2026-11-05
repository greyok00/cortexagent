#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRAPER = os.path.join(ROOT, "lib", "scraper")
for p in (ROOT, SCRAPER):
    if p not in sys.path:
        sys.path.insert(0, p)

pytest.importorskip("site_render", reason="external site-render module not installed")
import site_render  # noqa: E402

FIX = Path(HERE) / "fixtures" / "render" / "simple-guide.md"


def test_render_markdown_keeps_authority_links_and_drops_level_labels():
    html, collapsed = site_render.render_markdown(FIX.read_text())
    assert "nist.gov/example" in html
    assert "example.com/blog" not in html
    assert "ELI5" not in html
    assert "Under" not in html
    assert collapsed >= 1


def test_render_markdown_sanitizes_svg_and_keeps_figure_caption():
    html, _ = site_render.render_markdown(FIX.read_text())
    assert "<script" not in html
    assert "figure class='diagram'" in html
    assert "Figure 1: Sysmon event flow" in html


def test_fenced_code_angle_brackets_are_escaped_once():

    md = "```cmd\nsysmon64 -i [<configfile>]\n```\n"
    html, _ = site_render.render_markdown(md)
    assert "&lt;configfile&gt;" in html
    assert "&amp;lt;" not in html


def test_inline_code_angle_brackets_are_escaped_once():
    md = "Use `sysmon64 -c [<configfile>]` to update.\n"
    html, _ = site_render.render_markdown(md)
    assert "&lt;configfile&gt;" in html
    assert "&amp;lt;" not in html


def test_prose_unknown_tag_is_still_escaped():
    html, _ = site_render.render_markdown("Use <configfile> here.")
    assert "&lt;configfile&gt;" in html
    assert "<configfile>" not in html


def test_render_document_has_tabs_and_wide_shell():
    html = site_render.render_document(
        FIX.read_text(), title="A Small Guide", hub="#",
        when="2026-01-01 00:00 UTC",
        guide_href="index.html", course_href="course/")
    assert "<h1>A Small Guide</h1>" in html
    assert "Guide" in html and "Course" in html
    # live 4K workbench shell (was 80%/1500px in the old kit)
    assert "--shell:97%" in html and "--maxw:2240px" in html
    assert "--measure:68ch" not in html


def test_render_document_without_course_href_has_no_dead_course_link():
    html = site_render.render_document(
        FIX.read_text(), title="A Small Guide", hub="#",
        when="2026-01-01 00:00 UTC", course_href=None)
    assert "href='course/'" not in html
    assert ">Course<" not in html
    assert ">Guide<" in html


def test_chart_rejects_dashboard_table():
    assert site_render.chart_is_teachable([
        "| Metric | Value |", "|---|---|", "| Price | $82,359 |",
        "| MVRV | 1.53 |", "| Fear & Greed | 59 |",
    ]) is False


def test_chart_accepts_single_unit_table():
    assert site_render.chart_is_teachable([
        "| Cycle | Peak stretch (%) |", "|---|---|",
        "| 2011–2013 | 518 |", "| 2013–2017 | 277 |", "| 2017–2021 | 146 |",
    ]) is True


def test_gate_drops_stock_and_ad_network_images():
    md = ("![AdobeStock 1754904224 Preview](https://x/adobestock_1.jpg)\n\n"
          "![AI is changing the economics](https://ids4.ad.gt/pixel)\n\n"
          "![Figure 2: Sysmon event pipeline](assets/sysmon.svg)\n")
    kept_md, kept, dropped = site_render.gate_section_images(md, "Sysmon telemetry")
    assert len(kept) == 1 and kept[0]["alt"].startswith("Figure 2")
    assert len(dropped) == 2


def test_image_gate_drops_stock_hero_and_ad_networks():
    md = ("![AdobeStock 1754904224 Preview](https://a/adobestock_1.jpg)\n\n"
          "![SOC analysts facing wall displays](https://b/_next/image?url=x)\n\n"
          "![AI is changing the economics](https://ids4.ad.gt/api/v1/ip_match)\n\n"
          "![AI is changing the economics](https://image2.pubmatic.com/AdServer/x)\n\n"
          "![Figure 3: PowerShell script block logging pipeline](assets/ps.svg)\n")
    _, kept, dropped = site_render.gate_section_images(md, "PowerShell logging")
    assert [k["alt"] for k in kept] == ["Figure 3: PowerShell script block logging pipeline"]
    assert len(dropped) == 4


def test_image_gate_enforces_cap():
    md = "\n\n".join(
        f"![Figure {i}: Sysmon event flow in process monitoring](assets/{i}.svg)"
        for i in range(1, 20))
    _, kept, dropped = site_render.gate_section_images(md, "Sysmon", max_images=5)
    assert len(kept) == 5
    assert any(d["reason"] == "image cap" for d in dropped)


def test_percentage_comparison_is_not_called_a_whole():

    html, n = site_render._chart_html(
        0, 1, ["Technique", "Customers affected (%)"],
        [["Technique", "Customers affected (%)"],
         ["Cloud Accounts", "21"], ["PowerShell", "12.6"],
         ["Windows Command Shell", "10"],
         ["Windows Management Instrumentation", "2.6"]],
        "How common is each technique?")
    assert n == 4
    assert "percentage comparison" in html
    assert "shares of a whole" not in html
    assert "Show source table" not in html


def test_percentage_series_summing_to_100_is_a_whole():
    html, n = site_render._chart_html(
        0, 1, ["Share", "Percent (%)"],
        [["Share", "Percent (%)"], ["A", "50"], ["B", "30"], ["C", "20"]],
        "A whole")
    assert n == 3
    assert "shares of a whole" in html


def test_markdown_table_headers_have_column_scope():
    html, _ = site_render.render_markdown(
        "| Event | Meaning |\n|---|---|\n| 1 | Process Create |\n")
    assert '<th scope="col">' in html


def test_chart_rejects_mixed_unit_column():
    assert site_render.chart_is_teachable([
        "| Asset | Measure |", "|---|---|", "| BTC | $82,359 |",
        "| Rate | 5% |", "| Delay | 3 days |",
    ]) is False


def test_chart_cap_stops_after_limit():
    md = "\n\n".join([
        "| A | B (%) |\n|---|---|\n| x | 10 |\n| y | 20 |\n| z | 30 |"
        for _ in range(5)])
    _, charts, n, _ = site_render.inject_charts(md, "Data", max_charts=2)
    assert n == 2


def test_scrub_keeps_sources_urls():
    import guide_scrub
    md = ("# Guide\n\n## Sources\n\n"
          "[1] NIST — https://nist.gov/x\n[2] CISA — https://cisa.gov/y\n")
    out, _ = guide_scrub.scrub_guide_md(md)
    assert "https://nist.gov/x" in out
    assert "https://cisa.gov/y" in out
