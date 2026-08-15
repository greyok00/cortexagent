#!/usr/bin/env python3
"""prompt_framing.py — Analyze and optimize user prompts before they hit the LLM.

This module performs a "prompt framing pass" that:
1. Classifies the prompt into a domain (business, OSINT, cybersecurity, professional)
2. Adds appropriate framing/context to the system prompt
3. Optimizes the prompt for clarity and conciseness
4. Shrinks redundant parts of the prompt

The framing pass happens BEFORE minification, so the optimized prompt
is what gets sent to the model.

Usage:
  python3 lib/prompt_framing.py smoke          # self-test
  python3 lib/prompt_framing.py "your prompt"  # frame a prompt
"""
import re
import sys
from typing import Dict, List, Optional, Tuple

# ── Domain Classification ──────────────────────────────────────────────────
DOMAIN_KEYWORDS = {
    "cybersecurity": [
        "security", "malware", "virus", "trojan", "ransomware", "phishing",
        "breach", "incident", "forensics", "exploit", "vulnerability",
        "attack", "defense", "firewall", "intrusion", "threat", "ioc",
        "indicator", "compromise", "breach", "anomaly", "suspicious",
    ],
    "osint": [
        "osint", "open source", "intelligence", "investigate", "search",
        "find", "locate", "track", "monitor", "watch", "surveillance",
        "reconnaissance", "scout", "probe", "scan", "enumeration",
    ],
    "business": [
        "business", "company", "market", "revenue", "profit", "cost",
        "budget", "forecast", "strategy", "plan", "growth", "investment",
        "ROI", "KPI", "metrics", "analytics", "dashboard", "report",
    ],
    "professional": [
        "professional", "report", "analysis", "research", "study",
        "review", "assessment", "evaluation", "audit", "compliance",
        "regulation", "policy", "procedure", "guideline", "standard",
    ],
}

def classify_domain(prompt: str) -> str:
    """Classify the prompt into a domain."""
    lower = prompt.lower()
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return "professional"
    return max(scores, key=scores.get)


# ── System Prompt Templates ────────────────────────────────────────────────
DOMAIN_FRAMING = {
    "cybersecurity": """You are a senior cybersecurity analyst. Provide thorough,
actionable security analysis. Include: (1) Threat classification, (2) IOCs if
applicable, (3) Mitigation steps, (4) Prevention recommendations.""",

    "osint": """You are an OSINT investigator. Provide structured, evidence-based
findings. Include: (1) Key findings, (2) Sources and confidence levels,
(3) Timeline if applicable, (4) Next investigation steps.""",

    "business": """You are a business analyst. Provide structured, data-driven
insights. Include: (1) Key metrics, (2) Trends and patterns, (3)
Recommendations, (4) Risk assessment.""",

    "professional": """You are a professional analyst. Provide clear, concise,
well-structured analysis. Include: (1) Executive summary, (2) Detailed findings,
(3) Recommendations, (4) Action items.""",
}


def add_domain_framing(system_prompt: str, domain: str) -> str:
    """Add domain-specific framing to the system prompt."""
    framing = DOMAIN_FRAMING.get(domain, DOMAIN_FRAMING["professional"])
    if "You are CortexAgent" in system_prompt:
        # Insert framing after the "You are CortexAgent" line
        idx = system_prompt.find("You are CortexAgent")
        if idx >= 0:
            insert_point = system_prompt.find("\n", idx)
            if insert_point >= 0:
                return system_prompt[:insert_point+1] + f"  {framing}\n\n" + system_prompt[insert_point+1:]
    return system_prompt + f"\n\n{framing}"


# ── Prompt Optimization ────────────────────────────────────────────────────
def optimize_prompt(prompt: str) -> str:
    """Optimize the user prompt for clarity and conciseness.

    - Remove redundant phrases ("I want to know", "Can you tell me", etc.)
    - Fix common typos and grammar
    - Ensure the prompt is clear and actionable
    """
    # Remove redundant phrases
    redundant = [
        (r"\bi want to know\s+", ""),
        (r"\bcan you tell me\s+", ""),
        (r"\bwhat is the\s+capital\s+of\s+", ""),  # keep "capital" but remove "what is the"
        (r"\bwhat\s+is\s+(a|the)\s+", "What is "),
        (r"\bcan you\s+", ""),
        (r"\bplease\s+", ""),
        (r"\bcould you\s+", ""),
        (r"\bi need you to\s+", ""),
        (r"\bi'd like you to\s+", ""),
        (r"\bhelp me with\s+", ""),
    ]
    for pattern, replacement in redundant:
        prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)

    # Capitalize first letter
    if prompt and prompt[0].islower():
        prompt = prompt[0].upper() + prompt[1:]

    # Remove trailing punctuation if present
    prompt = prompt.rstrip("!?")

    return prompt.strip()


# ── Prompt Shrinking ───────────────────────────────────────────────────────
def shrink_prompt(prompt: str, max_tokens: int = 50) -> str:
    """Shrink the prompt if it's too long, keeping the core meaning.

    This is a lightweight pass — only shrink if over the token limit.
    """
    # Rough token estimate: ~4 chars per token
    if len(prompt) <= max_tokens * 4:
        return prompt

    # Shrink: take the first 60% and last 40%, remove middle
    first = int(len(prompt) * 0.6)
    last = int(len(prompt) * 0.4)
    return prompt[:first] + " ... [truncated] ..." + prompt[-last:]


# ── Main Entry ──────────────────────────────────────────────────────────────
def frame_prompt(prompt: str, system_prompt: str, domain: Optional[str] = None) -> Tuple[str, str, str]:
    """Full framing pass: classify, optimize, shrink, and add framing.

    Returns: (optimized_prompt, framed_system_prompt, domain)
    """
    # 1. Classify domain
    if not domain:
        domain = classify_domain(prompt)

    # 2. Optimize prompt
    optimized = optimize_prompt(prompt)

    # 3. Shrink if needed
    optimized = shrink_prompt(optimized)

    # 4. Add domain framing to system prompt
    framed_system = add_domain_framing(system_prompt, domain)

    return optimized, framed_system, domain


def main():
    """Self-test and demo."""
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        # Self-test
        tests = [
            "What is the capital of France?",
            "Investigate the security posture of this server",
            "Write a business plan for a coffee shop",
            "Help me with my homework",
            "Scan the network for vulnerabilities",
            "Analyze the market for electric vehicles",
        ]
        for text in tests:
            optimized, framed, domain = frame_prompt(text, "You are CortexAgent.")
            print(f"Domain: {domain}")
            print(f"Original: {text}")
            print(f"Optimized: {optimized}")
            print(f"System framing: {framed[:80]}...")
            print("-" * 70)
        return

    # Frame a user-provided prompt
    prompt = " ".join(sys.argv[1:])
    optimized, framed, domain = frame_prompt(prompt, "You are CortexAgent.")
    print(f"Domain: {domain}")
    print(f"Optimized prompt: {optimized}")
    print(f"Framed system: {framed[:200]}...")


if __name__ == "__main__":
    main()
