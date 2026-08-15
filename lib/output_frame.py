#!/usr/bin/env python3
"""output_frame.py — Structure final output for domain-specific presentation.

This module performs an "output frame of reference pass" that:
1. Structures the output for the domain (business, OSINT, cybersecurity, professional)
2. Adds executive summary, key findings, recommendations
3. Adds context, references, sources
4. Adds action items, next steps

This happens AFTER beautification.

Usage:
  python3 lib/output_frame.py --smoke          # self-test
  python3 lib/output_frame.py "text"           # frame output
"""
import re
import sys
from typing import Dict, List, Optional, Tuple

# ── Output Structure Templates ──────────────────────────────────────────────
OUTPUT_TEMPLATES = {
    "cybersecurity": {
        "sections": [
            "THREAT CLASSIFICATION",
            "KEY FINDINGS",
            "INDICATORS OF COMPROMISE",
            "MITIGATION STEPS",
            "PREVENTION RECOMMENDATIONS",
        ],
        "format": "### {section}\n\n{content}",
        "style": "Technical, precise, actionable",
    },
    "osint": {
        "sections": [
            "KEY FINDINGS",
            "SOURCES & CONFIDENCE",
            "TIMELINE",
            "NEXT INVESTIGATION STEPS",
        ],
        "format": "### {section}\n\n{content}",
        "style": "Evidence-based, structured, traceable",
    },
    "business": {
        "sections": [
            "EXECUTIVE SUMMARY",
            "KEY METRICS",
            "TRENDS & PATTERNS",
            "RECOMMENDATIONS",
            "RISK ASSESSMENT",
        ],
        "format": "### {section}\n\n{content}",
        "style": "Data-driven, structured, strategic",
    },
    "professional": {
        "sections": [
            "EXECUTIVE SUMMARY",
            "DETAILED FINDINGS",
            "RECOMMENDATIONS",
            "ACTION ITEMS",
        ],
        "format": "### {section}\n\n{content}",
        "style": "Clear, concise, well-structured",
    },
}


def classify_output_domain(output: str) -> str:
    """Classify the output into a domain based on content."""
    lower = output.lower()
    scores = {}
    for domain, template in OUTPUT_TEMPLATES.items():
        # Simple keyword matching based on template sections
        score = sum(1 for section in template["sections"] if section.lower() in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return "professional"
    return max(scores, key=scores.get)


def add_output_structure(output: str, domain: str) -> str:
    """Add domain-specific structure to the output."""
    template = OUTPUT_TEMPLATES.get(domain, OUTPUT_TEMPLATES["professional"])
    sections = template["sections"]

    # Check if output already has section headers
    has_sections = any(section in output for section in sections)
    if has_sections:
        return output

    # Split output into logical sections
    paragraphs = output.split("\n\n")
    if len(paragraphs) < 2:
        paragraphs = [paragraph.strip() for paragraph in output.split("\n") if paragraph.strip()]

    # Structure the output
    structured = []
    for i, section in enumerate(sections):
        # Get content for this section
        if i < len(paragraphs):
            content = paragraphs[i]
        else:
            content = "No data available."

        structured.append(template["format"].format(section=section, content=content))

    return "\n\n".join(structured)


def add_context_references(output: str) -> str:
    """Add context and references to the output."""
    # Check if output has a sources/references section
    has_references = any(keyword in output.lower() for keyword in ["source", "reference", "citation"])
    if has_references:
        return output

    # Add a references section if output is long enough
    if len(output) > 100:
        output += "\n\n### REFERENCES\n\nSources and methodology used in this analysis."
    return output


def add_action_items(output: str) -> str:
    """Add action items to the output."""
    # Check if output already has action items
    has_actions = any(keyword in output.lower() for keyword in ["action", "next steps", "recommended"])
    if has_actions:
        return output

    # Add action items if output is long enough
    if len(output) > 100:
        output += "\n\n### ACTION ITEMS\n\n1. Review the findings above\n2. Implement recommended changes\n3. Monitor for improvements"
    return output


def frame_output(output: str, domain: str = None) -> Tuple[str, str]:
    """Full framing pass: classify, structure, add context.

    Returns: (framed_output, domain)
    """
    # 1. Classify domain
    if not domain:
        domain = classify_output_domain(output)

    # 2. Add domain-specific structure
    framed = add_output_structure(output, domain)

    # 3. Add context and references
    framed = add_context_references(framed)

    # 4. Add action items
    framed = add_action_items(framed)

    return framed, domain


def main():
    """Self-test and demo."""
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        # Self-test
        test_output = """The investigation found three vulnerabilities:
- SQL injection in the login form
- XSS in the search function
- Insecure file upload

The server is running Ubuntu 20.04 with outdated packages."""

        framed, domain = frame_output(test_output)
        print(f"Domain: {domain}")
        print(f"Framed output:\n{framed}")
        return

    # Frame a user-provided output
    output = " ".join(sys.argv[1:])
    framed, domain = frame_output(output)
    print(f"Domain: {domain}")
    print(f"Framed output:\n{framed}")


if __name__ == "__main__":
    main()
