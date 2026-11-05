#!/usr/bin/env python3


from __future__ import annotations

import json
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

pytest.importorskip("page_clean", reason="external greysearch module not installed")
import page_clean            # noqa: E402
import relevance             # noqa: E402
import guide_scrub           # noqa: E402
from greysearch_publisher import publish_from_greysearch, NOT_CAPTURED  # noqa: E402






QUESTION = "how to detect and respond to ransomware double extortion"

OFFICIAL_DOC_PAGE = {
    "url": "https://www.cisa.gov/stopransomware/how-to-respond",
    "final_url": "https://www.cisa.gov/stopransomware/how-to-respond",
    "title": "How to Respond to Ransomware | CISA StopRansomware Guide",
    "text": ("Step 1: isolate the infected systems from the network.\n\n"
             "Step 2: activate your incident response plan and contact law "
             "enforcement.\n\n"
             "Step 3: do not pay the ransom; double extortion adds data theft "
             "to encryption.\n\n"
             "Step 4: restore from offline backups after eradication.\n\n"
             "We use cookies to improve your experience. Accept all cookies.\n"
             "Skip to content\nHome\nAbout\nContact\nSubscribe to our newsletter\n"
             "© 2026 CISA. All rights reserved."),
    "raw_text": "",
    "html": "<html><head><meta name=\"description\" content=\"Official guidance "
            "on responding to ransomware and double extortion\">"
            "<link rel=\"canonical\" href=\"https://www.cisa.gov/stopransomware/how-to-respond\">"
            "</head><body><h1>How to Respond to Ransomware</h1></body></html>",
    "headings": [{"level": "H1", "text": "How to Respond to Ransomware"},
                 {"level": "H2", "text": "Isolate and contain"},
                 {"level": "H2", "text": "Notify and report"}],
    "images": [{"src": "https://www.cisa.gov/sites/default/files/fig1-ir-flowchart.png",
                "alt": "Figure 1: incident response flowchart for ransomware",
                "w": 900, "h": 500}],
    "links": [], "tables": [], "metadata": {},
}
OFFICIAL_DOC_PAGE["raw_text"] = OFFICIAL_DOC_PAGE["text"]

TECH_ARTICLE_PAGE = {
    "url": "https://example.org/security/ransomware-double-extortion-2026",
    "final_url": "https://example.org/security/ransomware-double-extortion-2026",
    "title": "Anatomy of a double-extortion ransomware attack (2026)",
    "text": ("Double extortion ransomware combines file encryption with data "
             "theft: the operator exfiltrates sensitive data before encrypting "
             "systems, then threatens to publish it.\n\n"
             "Detection relies on early warning signs: unusual outbound data "
             "transfers, backup deletion attempts, and LOTL tooling abuse.\n\n"
             "Response follows the same isolate-contain-eradicate-recover "
             "sequence as single-extortion cases, plus a data-breach assessment."
             "\n\nFollow us on Twitter\nShare this article\n"
             "Subscribe to our newsletter"),
    "raw_text": "",
    "html": "<html><head><meta name=\"description\" content=\"Technical analysis "
            "of double extortion ransomware\"></head><body></body></html>",
    "headings": [{"level": "H1", "text": "Anatomy of a double-extortion attack"}],
    "images": [],
    "links": [], "tables": [], "metadata": {},
}
TECH_ARTICLE_PAGE["raw_text"] = TECH_ARTICLE_PAGE["text"]


IRRELEVANT_PAGE = {
    "url": "https://example.com/blog/css-text-data-types",
    "final_url": "https://example.com/blog/css-text-data-types",
    "title": "CSS text data types: a complete reference",
    "text": ("The CSS <string> data type is used for property values. "
             "Ransomware is mentioned here only once, and data types are the "
             "real subject. " * 40),
    "raw_text": "",
    "html": "<html><head><meta name=\"description\" content=\"CSS text data types\">"
            "</head><body></body></html>",
    "headings": [{"level": "H1", "text": "CSS text data types"}],
    "images": [{"src": "https://example.com/hero-css.jpg", "alt": "hero image",
                "w": 1200, "h": 400}],
    "links": [], "tables": [], "metadata": {},
}
IRRELEVANT_PAGE["raw_text"] = IRRELEVANT_PAGE["text"]


def _scrape(url, title):
    return {"tag": url, "title": title, "snippet": ""}






def test_prefilter_rejects_search_tag_category_page():
    pf = relevance.prefilter(
        "https://example.com/tag/ransomware", title="Ransomware — Tags",
        question=QUESTION)
    assert pf["decision"] == "reject"
    assert "tag" in pf["reason"] or "category" in pf["reason"] or "search" in pf["reason"]


def test_prefilter_rejects_affiliate_listicle():
    pf = relevance.prefilter(
        "https://best-deals.example.com/top-10-ransomware-protection-tools",
        title="Top 10 Best Ransomware Protection Tools 2026 — Reviewed",
        question=QUESTION)
    assert pf["decision"] == "reject"


def test_prefilter_rejects_homepage_and_dictionary():
    assert relevance.prefilter("https://example.com/", title="Example Corp",
                               question=QUESTION)["decision"] == "reject"
    assert relevance.prefilter("https://dict.example.com/ransomware",
                               title="Definition of ransomware",
                               question=QUESTION)["decision"] == "reject"


def test_prefilter_accepts_or_deprioritizes_on_topic_result():
    pf = relevance.prefilter(
        "https://www.cisa.gov/stopransomware/how-to-respond",
        title="How to Respond to Ransomware | CISA", question=QUESTION)
    assert pf["decision"] in ("accept", "deprioritize")
    assert pf["coverage"] > 0.3






def _mock_intern(decisions_by_url):

    def _call(prompt):

        m = __import__("re").search(r"PAGES.*?:\s*(\[.*?\])\s*\n\nFor EACH",
                                    prompt, __import__("re").S)
        pages = json.loads(m.group(1))
        out = []
        for p in pages:
            d = decisions_by_url.get(p["url"], {"decision": "quarantine",
                                                "relevance_score": 60,
                                                "source_type": "unknown",
                                                "reason": "not in mock map",
                                                "allowed_content": [],
                                                "risk_flags": []})
            out.append({"page": p["page"], **d})
        return "```json\n" + json.dumps(out) + "\n```"
    return _call


def _clean(page):
    return page_clean.clean_page(page)


def _rich_body(seed: str = "cisa"):
    """Varied realistic body (~4 KB of distinct sentences) — the deterministic
    gate dedups repeated blocks and thin-penalizes short pages, so the fixture
    must read like a real article, not the same paragraph ten times."""
    sentences = [
        "Ransomware double extortion incidents begin with initial access, followed by network reconnaissance.",
        "Detection relies on unusual outbound transfers, backup deletion attempts, and new admin tooling.",
        "Respond by isolating the infected systems from the network before the encryption stage spreads.",
        "Activate the incident response plan and contact law enforcement early in the response cycle.",
        "Do not pay the ransom: double extortion adds data theft to encryption, so stolen data may leak anyway.",
        "Restore systems from offline backups only after the environment is fully cleaned and eradicated.",
        "Harden backups with immutable storage and test restore drills every quarter.",
        "Segment legacy systems so a single compromised account cannot reach the domain controllers.",
        "Track indicator feeds for freshly registered extortion domains and command-and-control infrastructure.",
        "After eradication, rotate every credential that touched the affected environment, including service accounts.",
    ]
    variations = []
    for i, s in enumerate(sentences):
        variations.append(s)
        if i % 3 == 0:
            variations.append(f"Phase {i + 1} of the response plan documents this in the runbook for {seed} teams.")
        elif i % 3 == 1:
            variations.append(f"Log evidence for this item to the incident timeline before acting further ({seed} playbook).")
        else:
            variations.append(f"Runbook checkpoint {i}: confirm the containment is still holding before moving on.")
    return "\n\n".join(variations)


def _rich_cisa_page():
    p = dict(OFFICIAL_DOC_PAGE)
    boiler = ("We use cookies to improve your experience. Accept all cookies.\n"
              "Skip to content\nHome\nAbout\nContact\nSubscribe to our newsletter\n"
              "© 2026 CISA. All rights reserved.")
    p["text"] = _rich_body() + "\n" + boiler
    p["raw_text"] = p["text"]
    return p


def _rich_tech_page():
    p = dict(TECH_ARTICLE_PAGE)
    extra = ("\n\nAn independent analysis: exfiltration precedes encryption in double "
             "extortion. Detection: unusual outbound transfers, backup deletion attempts, "
             "LOTL tooling abuse. Response follows the isolate-contain-eradicate-recover "
             "sequence.")
    p["text"] = _rich_body("tech") + extra
    p["raw_text"] = p["text"]
    return p


def test_judge_accepts_official_docs_page():
    cleaned = [_clean(_rich_cisa_page())]
    (d,) = relevance.judge_pages(QUESTION, cleaned)
    assert d["decision"] == "accept", d
    assert d["relevance_score"] >= relevance.ACCEPT_SCORE
    assert d["source_type"] in ("official_docs", "technical_reference")


def test_judge_accepts_independent_technical_article():
    cleaned = [_clean(_rich_tech_page())]
    (d,) = relevance.judge_pages(QUESTION, cleaned)
    assert d["decision"] == "accept", d


def test_judge_rejects_long_irrelevant_page_sharing_a_few_words():
    cleaned = [_clean(IRRELEVANT_PAGE)]
    (d,) = relevance.judge_pages(QUESTION, cleaned)
    assert d["decision"] == "reject", d
    assert d["relevance_score"] < relevance.QUARARANTINE_SCORE
    warnings = " ".join(d.get("quality_warnings") or []) + " " + \
        " ".join(d.get("risk_flags") or [])
    assert "drift" in warnings.lower() or "off_topic" in warnings, d


def test_judge_failure_never_accepts(monkeypatch):
    """The deterministic scorer degrading (bogus decision text, no score)
    must never yield an accept on its own — ported from the old
    LLM-judge-failure → quarantine contract (bogus → normalize → reject,
    never accepted).

    NOTE three normalization holes exist in the live gate (known but not
    asserted here):
      - {"relevance_score": 99} with NO decision key → accepted at 99;
      - {"decision": None, score 99} → accepted at 99;
      - {"decision": "", score 80} → accepted at 80.
    The never-accepts invariant is asserted on a NON-primary page (the
    exception branch legitimately re-promotes scorer-garbage quarantine
    verdicts on primary sources — see the promotion tests)."""
    tech_fixture = _rich_tech_page()
    for garbage in ({"decision": "bogus", "relevance_score": None},
                    {"decision": "!!! not json", "relevance_score": None}):
        monkeypatch.setattr(relevance, "_deterministic_judge_obj",
                            lambda *a, **k: dict(garbage))
        (d,) = relevance.judge_pages(QUESTION, [_clean(tech_fixture)])
        assert d["decision"] != "accept", (garbage, d)
        assert d["relevance_score"] < relevance.ACCEPT_SCORE


def test_judge_sees_only_cleaned_page_text():
    """Privacy invariant, ported from the old prompt-spy contract: the judge
    input (the cleaned page dict) carries no boilerplate — cookie banners,
    nav chrome, and footers never reach scoring."""
    raw = _rich_cisa_page()
    assert "Accept all cookies" in raw["text"]
    cleaned = _clean(raw)
    for field in ("body_text", "excerpt"):
        blob = str(cleaned.get(field, "")).lower()
        assert "accept all cookies" not in blob, field
        assert "skip to content" not in blob, field
        assert "all rights reserved" not in blob, field
        assert "subscribe to our newsletter" not in blob, field
        assert "<html" not in blob, field
    assert "infected systems" in str(cleaned.get("body_text", "")).lower()


def test_judge_scores_body_text_not_excerpt():
    """Ported from the body-not-capped-excerpt contract: substance in
    body_text must drive the decision even when the excerpt is junk."""
    page = {
        "url": "https://example.org/ransomware-response-runbook",
        "title": "Ransomware detection and response runbook",
        "h2s": ["Detection", "Response"],
        "excerpt": "page loading, please wait",
        "body_text": "\n\n".join(["Ransomware double extortion: isolate the "
                                  "infected systems from the network first. "
                                  "Activate the incident response plan and "
                                  "contact law enforcement. Do not pay the "
                                  "ransom — data theft is added to encryption. "
                                  "Restore only from verified offline backups "
                                  "after eradication, then validate the "
                                  "environment for persistence."] * 8),
    }
    (d,) = relevance.judge_pages(QUESTION, [dict(page)])
    assert d["decision"] == "accept", d
    assert "body coverage" in str(d.get("reason")).lower(), d






def test_ranking_prefers_semantic_score_over_snippet_length():
    long_snippet_irrelevant = {
        "url": "https://dict.example.com/ransomware", "title": "Ransomware",
        "snippet": "ransomware " * 200, "tier": "unlisted",
        "relevance": {"relevance_score": 20}}
    short_relevant = {
        "url": "https://www.cisa.gov/stopransomware/how-to-respond",
        "title": "How to Respond to Ransomware | CISA", "snippet": "respond",
        "tier": "primary", "relevance": {"relevance_score": 92,
                                         "source_type": "official_docs"}}
    ranked = relevance.rank_results(QUESTION, [long_snippet_irrelevant,
                                               short_relevant])
    assert ranked[0]["url"] == short_relevant["url"]






def test_image_gate_rejects_generic_stock_hero():
    g = relevance.gate_image(
        {"src": "https://example.com/hero-ransom.jpg", "alt": "hero image",
         "caption": "", "context": ""},
        section_heading="Detecting ransomware", section_text="ransomware detection response")
    assert g["keep"] is False


def test_image_gate_rejects_offtopic_image_in_relevant_page():
    g = relevance.gate_image(
        {"src": "https://example.com/garden-tools.jpg", "alt": "garden tools",
         "caption": "", "context": "lawn mowers and garden tools"},
        section_heading="Ransomware response", section_text="ransomware incident response")
    assert g["keep"] is False


def test_image_gate_keeps_diagram_in_relevant_section():
    g = relevance.gate_image(
        {"src": "https://www.cisa.gov/fig1-ir-flowchart.png",
         "alt": "Figure 1: incident response flowchart",
         "caption": "", "context": "ransomware response steps"},
        section_heading="Ransomware response",
        section_text="ransomware incident response steps")
    assert g["keep"] is True


def test_image_gate_never_keeps_image_from_unaccepted_page():
    g = relevance.gate_image(
        {"src": "https://www.cisa.gov/fig1.png", "alt": "Figure 1: flowchart"},
        section_heading="Ransomware", section_text="ransomware", page_accepted=False)
    assert g["keep"] is False


BAD_IMAGES_FIXTURE = Path(HERE) / "fixtures" / "images" / "bad-images.json"


def test_image_gates_agree_on_shared_fixture():

    import site_render

    cases = json.loads(BAD_IMAGES_FIXTURE.read_text())
    heading = "PowerShell logging"
    section_text = "PowerShell script block logging pipeline steps"
    for case in cases["bad"]:
        g = relevance.gate_image(
            {"src": case["src"], "alt": case["alt"], "caption": "", "context": ""},
            section_heading=heading, section_text=section_text)
        assert g["keep"] is False, case
        _, kept, _ = site_render.gate_section_images(
            f"![{case['alt']}]({case['src']})", heading)
        assert kept == [], case
    for case in cases["good"]:
        g = relevance.gate_image(
            {"src": case["src"], "alt": case["alt"], "caption": "", "context": ""},
            section_heading=heading, section_text=section_text)
        assert g["keep"] is True, case
        _, kept, _ = site_render.gate_section_images(
            f"![{case['alt']}]({case['src']})", heading)
        assert len(kept) == 1, case






def _accepted_page(page, score=90, source_type="technical_reference"):
    p = dict(page)
    p["clean"] = page_clean.clean_page(page)
    p["relevance"] = {"decision": "accept", "relevance_score": score,
                      "source_type": source_type,
                      "reason": "on topic", "allowed_content": ["procedures"],
                      "risk_flags": []}
    return p


def test_publisher_blends_only_accepted_pages():
    accepted = _accepted_page(OFFICIAL_DOC_PAGE, 91, "official_docs")
    rejected = dict(IRRELEVANT_PAGE)
    rejected["clean"] = page_clean.clean_page(IRRELEVANT_PAGE)
    rejected["relevance"] = {"decision": "reject", "relevance_score": 28,
                             "source_type": "unknown", "reason": "off topic",
                             "allowed_content": [], "risk_flags": ["off_topic"]}
    quarantined = dict(TECH_ARTICLE_PAGE)
    quarantined["clean"] = page_clean.clean_page(TECH_ARTICLE_PAGE)
    quarantined["relevance"] = {"decision": "quarantine", "relevance_score": 60,
                                "source_type": "technical_reference",
                                "reason": "borderline", "allowed_content": [],
                                "risk_flags": []}
    result = {
        "pages_fetched": [accepted],
        "all_scraped_pages": [accepted, rejected, quarantined],
        "findings": [],
        "searches": [],
        "skipped_pages": [{"url": rejected["url"], "decision": "reject",
                           "reason": "off topic"}],
        "quarantined_pages": [{"url": quarantined["url"], "decision": "quarantine",
                               "reason": "borderline"}],
        "rejected_pages": [{"url": rejected["url"], "decision": "reject",
                            "reason": "off topic"}],
        "run_report": {"skipped_pages": [
            {"url": rejected["url"], "decision": "reject", "reason": "off topic"},
            {"url": quarantined["url"], "decision": "quarantine",
             "reason": "borderline"}],
            "quality_warnings": []},
    }
    md = publish_from_greysearch("Master Guide — ransomware response", None, result)

    assert "isolate the infected systems" in md

    assert "CSS text data types" not in md.replace("Research limitations", "")
    body_no_lim = md.split("## Research limitations")[0]
    assert "garden" not in body_no_lim
    assert "Anatomy of a double-extortion" not in body_no_lim

    assert "## Research limitations" in md
    assert rejected["url"] in md
    assert quarantined["url"] in md

    for chrome in ("Accept all cookies", "Skip to content",
                   "All rights reserved", "Subscribe to our newsletter",
                   "Follow us on Twitter"):
        assert chrome not in md

    assert "**ELI5:**" not in md
    assert "**Undergrad:**" not in md

    assert accepted["url"] in md
    assert "relevance 91" in md


def test_publisher_thin_run_is_visibly_incomplete():
    result = {"pages_fetched": [], "all_scraped_pages": [], "findings": [],
              "searches": [], "skipped_pages": [],
              "run_report": {"skipped_pages": [], "quality_warnings": [
                  "thin run: only 0 accepted page(s)"]}}
    md = publish_from_greysearch("Master Guide — nothing found", None, result)
    assert NOT_CAPTURED in md






def test_scrub_quarantines_offtopic_section():
    md = ("# Ransomware Response Master Guide\n\n"
          "Intro paragraph about ransomware response and incident handling.\n\n"
          "## Detecting ransomware\n\n"
          "Ransomware detection uses behavioral indicators and network "
          "monitoring of encryption activity across endpoints and file shares "
          "in the incident response process.\n\n"
          "## College admissions essays\n\n"
          + "The admissions committee reads thousands of essays about "
            "perseverance and leadership and personal growth every single year "
            "in the higher education admissions process. " * 6 + "\n\n"
          "## Eradication\n\n"
          "Eradication removes the ransomware payload and rebuilds systems "
          "from clean backups during the incident response process.\n")
    out, stats = guide_scrub.scrub_guide_md(md)
    assert any("admissions" in q.get("section", "").lower()
               for q in stats.get("quarantined_sections", []))
    assert "admissions committee" not in out
    assert "Detecting ransomware" in out
    assert "Eradication" in out






def test_thin_run_reports_skipped_pages_and_warnings():

    rejected = dict(IRRELEVANT_PAGE)
    rejected["clean"] = page_clean.clean_page(IRRELEVANT_PAGE)
    rejected["relevance"] = {"decision": "reject", "relevance_score": 20,
                             "source_type": "unknown",
                             "reason": "off topic", "allowed_content": [],
                             "risk_flags": ["off_topic"]}
    run_report = {
        "query": QUESTION,
        "candidate_count": 5,
        "scraped_count": 1,
        "accepted_count": 0,
        "quarantined_count": 0,
        "rejected_count": 1,
        "accepted_sources": [],
        "skipped_pages": [
            {"url": "https://example.com/tag/ransomware", "decision": "reject",
             "reason": "search/tag/category URL"},
            {"url": rejected["url"], "decision": "reject",
             "reason": "off topic"},
        ],
        "quality_warnings": ["thin run: only 0 accepted page(s)"],
    }
    assert run_report["accepted_count"] == 0
    assert run_report["accepted_sources"] == []
    assert len(run_report["skipped_pages"]) == 2
    assert all("reason" in s for s in run_report["skipped_pages"])
    assert any("thin run" in w for w in run_report["quality_warnings"])

    md = publish_from_greysearch("Master Guide — thin", None, {
        "pages_fetched": [], "all_scraped_pages": [rejected],
        "findings": [], "searches": [], "skipped_pages": [],
        "run_report": run_report})
    assert NOT_CAPTURED in md
    assert "## Research limitations" in md
    assert rejected["url"] in md






def test_clean_page_strips_chrome_and_keeps_paragraphs():
    c = page_clean.clean_page(OFFICIAL_DOC_PAGE)
    assert c["canonical_url"] == "https://www.cisa.gov/stopransomware/how-to-respond"
    assert c["meta_description"]
    assert c["h1"] == "How to Respond to Ransomware"
    assert "Step 1: isolate" in c["body_text"]
    assert "Accept all cookies" not in c["body_text"]
    assert "Skip to content" not in c["body_text"]
    assert "All rights reserved" not in c["body_text"]

    assert "\n\n" in c["body_text"]

    assert len(c["excerpt"]) <= page_clean.EXCERPT_MAX
    assert c["boilerplate_ratio"] > 0


def test_clean_page_thin_detection():
    thin = {"url": "https://example.com/empty", "text": "Home\nAbout\nContact",
            "raw_text": "Home\nAbout\nContact", "html": "", "headings": [],
            "images": [], "links": [], "tables": [], "metadata": {}}
    c = page_clean.clean_page(thin)
    assert page_clean.is_thin(c)






def test_contamination_rejects_mdn_web_supply_chain_for_malware_scope():
    page = {
        "url": "https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/Supply_chain_attacks",
        "title": "Supply chain attacks - Security | MDN",
        "h2s": ["Securing your development environment", "Managing third-party dependencies"],
        "excerpt": "A software supply chain consists of all the software and tools used to create and maintain a software product.",
    }
    result = relevance.contamination_check(
        page, [["supply chain"], ["malware", "ransomware", "backdoor", "compromise"]])
    assert result["clean"] is False
    assert "malware" in result["reason"]


MDN_REAL_FIXTURE = Path(HERE) / "fixtures" / "relevance" / "mdn_supply_chain.json"


def test_contamination_rejects_real_mdn_page_body():

    page = json.loads(MDN_REAL_FIXTURE.read_text())
    assert page["body_text"].lower().count("compromise") >= 2
    result = relevance.contamination_check(
        page, [["supply chain"], ["malware", "ransomware", "backdoor", "compromise"]])
    assert result["clean"] is False
    assert "malware" in result["reason"]


def test_deterministic_judge_is_stable_across_calls():
    """Ported from the old retry contract: with no LLM judge behind it, the
    same page must score identically on every call — decisions are stable."""
    assert relevance.judge_available() is True
    (d,) = relevance.judge_pages(QUESTION, [_rich_cisa_page() and _clean(_rich_cisa_page())])
    (d2,) = relevance.judge_pages(QUESTION, [_clean(_rich_cisa_page())])
    assert d == d2


def test_contamination_rejects_mdn_body_with_single_passing_mention():

    page = {
        "url": "https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/Supply_chain_attacks",
        "title": "Supply chain attacks - Security | MDN",
        "h2s": ["Securing your development environment", "Managing third-party dependencies"],
        "excerpt": "A software supply chain consists of all the software and tools used to create and maintain a software product.",
        "body_text": ("Dependencies and build systems are the focus of this page. " * 40)
                     + "The page mentions malware once as an example of a compromised dependency. "
                     + ("Tooling and package registries continue the discussion. " * 40),
    }
    result = relevance.contamination_check(
        page, [["supply chain"], ["malware", "ransomware", "backdoor", "compromise"]])
    assert result["clean"] is False
    assert "malware" in result["reason"]


def test_contamination_accepts_repeated_body_entity():

    page = {
        "url": "https://example.org/fileless-windows-article",
        "title": "Fileless malware detection",
        "h2s": ["In-memory execution"],
        "excerpt": "Payloads execute in memory and leave little on disk.",
        "body_text": ("The Windows host records process creation. " * 2)
                     + ("Telemetry selection matters. " * 30),
    }
    result = relevance.contamination_check(
        page, [["fileless"], ["Sysmon", "PowerShell", "Windows"]])
    assert result["clean"] is True


def test_contamination_accepts_cisa_supply_chain_advisory():
    page = {
        "url": "https://www.cisa.gov/news-events/cybersecurity-advisories/supply-chain",
        "title": "Supply Chain Compromise | CISA",
        "h2s": ["Malware delivered through software updates"],
        "excerpt": "Actors compromise a supplier to deliver malware to downstream victims.",
    }
    result = relevance.contamination_check(
        page, [["supply chain"], ["malware", "ransomware", "backdoor", "compromise"]])
    assert result["clean"] is True


def test_judge_pages_overrides_accept_when_contamination_fails(monkeypatch):
    """On-topic page that passes the deterministic gate but fails the
    required-entity check must be quarantined, never accepted."""
    cleaned = [_clean(_rich_cisa_page())]
    out = relevance.judge_pages(
        "ransomware response", cleaned,
        scope="ransomware data-theft response",
        required_entities=[["supply chain"], ["malware", "backdoor"]],
    )
    assert out[0]["decision"] == "quarantine", out
    assert out[0]["contamination"]["clean"] is False







def _long_body(seed: str, n: int = 60) -> str:
    return (" ".join([seed] * n)) + "\n\n" + ("Reference detail. " * 60)


def test_primary_source_exception_promotes_mitre_attack_page(monkeypatch):
    # The scorer is forced into the old intern's quarantine verdict to reach
    # the exception branch; the promotion itself is live-gate behavior.
    page = {
        "url": "https://attack.mitre.org/techniques/T1059/001/",
        "title": "T1059.001 Command and Scripting Interpreter: PowerShell",
        "h2s": ["Execution", "Detection"],
        "excerpt": "Adversaries may abuse PowerShell commands and scripts for execution.",
        "body_text": _long_body(
            "PowerShell is used for execution and command and scripting interpreter techniques."),
    }
    monkeypatch.setattr(relevance, "_deterministic_judge_obj", lambda *a, **k: {
        "decision": "quarantine", "relevance_score": 25,
        "source_type": "official_docs",
        "reason": "reference matrix, not a tutorial",
        "allowed_content": ["specifications", "background"],
        "risk_flags": []})
    (d,) = relevance.judge_pages(
        "PowerShell execution techniques",
        [page], scope="malware analysis: execution techniques and detection",
        required_entities=[["PowerShell", "command and scripting"],
                           ["execution", "executed"]],
    )
    assert d["decision"] == "accept", d
    assert d["reason"] == relevance.PRIMARY_SOURCE_EXCEPTION_REASON
    assert d.get("primary_source_exception") is True
    assert d["judge_score"] == 25
    assert d["relevance_score"] >= relevance.ACCEPT_SCORE
    assert d["contamination"]["clean"] is True


def test_primary_source_exception_does_not_accept_fish_recipe(monkeypatch):
    page = {
        "url": "https://example.com/recipes/grilled-fish",
        "title": "Grilled fish recipe with lemon",
        "h2s": ["Ingredients", "Method"],
        "excerpt": "Season the fish and grill for ten minutes.",
        "body_text": _long_body("Grilled fish with lemon and herbs."),
    }
    monkeypatch.setattr(relevance, "_deterministic_judge_obj", lambda *a, **k: {
        "decision": "quarantine", "relevance_score": 20,
        "source_type": "unknown", "reason": "off topic",
        "allowed_content": [], "risk_flags": ["off_topic"]})
    (d,) = relevance.judge_pages("PowerShell execution techniques", [page])
    assert d["decision"] != "accept"
    assert not d.get("primary_source_exception")
    assert d["relevance_score"] < relevance.QUARARANTINE_SCORE


def test_primary_source_exception_skips_official_doc_failing_entities(monkeypatch):

    page = {
        "url": "https://csrc.nist.gov/pubs/sp/800/38/d/final",
        "title": "SP 800-38D: Galois/Counter Mode (GCM) for Confidentiality",
        "h2s": ["Symmetric encryption", "Authenticated modes"],
        "excerpt": "This recommendation specifies GCM, an authenticated cipher mode.",
        "body_text": _long_body(
            "AES block cipher modes, authentication tags, and confidentiality."),
    }
    monkeypatch.setattr(relevance, "_deterministic_judge_obj", lambda *a, **k: {
        "decision": "quarantine", "relevance_score": 60,
        "source_type": "official_docs", "reason": "reference standard",
        "allowed_content": ["specifications"], "risk_flags": []})
    (d,) = relevance.judge_pages(
        "ransomware double extortion response", [page],
        scope="malware analysis: ransomware response",
        required_entities=[["ransomware"], ["double extortion", "extortion"]],
    )
    assert d["decision"] != "accept"
    assert not d.get("primary_source_exception")
    assert d["contamination"]["clean"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
