#!/usr/bin/env python3

import re
import sys
from typing import Dict, List, Optional, Tuple


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

    lower = output.lower()
    scores = {}
    for domain, template in OUTPUT_TEMPLATES.items():

        score = sum(1 for section in template["sections"] if section.lower() in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return "professional"
    return max(scores, key=scores.get)


def add_output_structure(output: str, domain: str) -> str:

    template = OUTPUT_TEMPLATES.get(domain, OUTPUT_TEMPLATES["professional"])
    sections = template["sections"]


    has_sections = any(section in output for section in sections)
    if has_sections:
        return output


    paragraphs = output.split("\n\n")
    if len(paragraphs) < 2:
        paragraphs = [paragraph.strip() for paragraph in output.split("\n") if paragraph.strip()]


    structured = []
    for i, section in enumerate(sections):

        if i < len(paragraphs):
            content = paragraphs[i]
        else:
            content = "No data available."

        structured.append(template["format"].format(section=section, content=content))

    return "\n\n".join(structured)


def add_context_references(output: str) -> str:


    has_references = any(keyword in output.lower() for keyword in ["source", "reference", "citation"])
    if has_references:
        return output


    if len(output) > 100:
        output += "\n\n### REFERENCES\n\nSources and methodology used in this analysis."
    return output


def add_action_items(output: str) -> str:


    has_actions = any(keyword in output.lower() for keyword in ["action", "next steps", "recommended"])
    if has_actions:
        return output


    if len(output) > 100:
        output += "\n\n### ACTION ITEMS\n\n1. Review the findings above\n2. Implement recommended changes\n3. Monitor for improvements"
    return output


def frame_output(output: str, domain: str = None) -> Tuple[str, str]:


    if not domain:
        domain = classify_output_domain(output)


    framed = add_output_structure(output, domain)


    framed = add_context_references(framed)


    framed = add_action_items(framed)

    return framed, domain


def main():

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":

        test_output = """The investigation found three vulnerabilities:
- SQL injection in the login form
- XSS in the search function
- Insecure file upload

The server is running Ubuntu 20.04 with outdated packages."""

        framed, domain = frame_output(test_output)
        print(f"Domain: {domain}")
        print(f"Framed output:\n{framed}")
        return


    output = " ".join(sys.argv[1:])
    framed, domain = frame_output(output)
    print(f"Domain: {domain}")
    print(f"Framed output:\n{framed}")


if __name__ == "__main__":
    main()
