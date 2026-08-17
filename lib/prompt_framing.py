#!/usr/bin/env python3
"""prompt_framing.py — Reframe + shrink + minify user prompts before the LLM.

Pipeline (per call to frame_prompt):
  1. classify_domain       — keyword match into {business, professional, osint,
                              cybersecurity, code, general}
  2. load_profile          — read profiles/default.json (or named profile).
                              No PII, no upstream-tool references.
  3. load_agent            — pick an "agent" persona from profile (default
                              planner / auditor / shrinker / generalist).
  4. reframe_prompt        — strip filler, dedupe sentences, normalize
                              whitespace, drop fragments, apply domain hint.
  5. shrink_prompt         — cap to N words/tokens per profile; pick the
                              most informative sentences.
  6. minify_prompt         — character-level squeeze: lower-case stopwords,
                              drop punctuation, collapse whitespace.
  7. build_system          — domain prompt + agent role + output format.

Every prompt leaves Stage 2 smaller, clearer, and matched to the profile.

Usage:
  python3 lib/prompt_framing.py smoke
  python3 lib/prompt_framing.py "your rambling prompt here"
  from lib.prompt_framing import frame_prompt
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Paths ───────────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent
_PROFILE_DIR = Path(os.environ.get(
    "CORTEXAGENT_PROFILES_DIR", str(_REPO / "profiles")))
_DEFAULT_PROFILE = os.environ.get("CORTEXAGENT_PROFILE", "default")


# ── Domain Classification ──────────────────────────────────────────────────
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "cybersecurity": [
        "security", "malware", "virus", "trojan", "ransomware", "phishing",
        "breach", "incident", "forensics", "exploit", "vulnerability",
        "attack", "defense", "firewall", "intrusion", "threat", "ioc",
        "indicator", "compromise", "anomaly", "suspicious",
    ],
    "osint": [
        "osint", "open source", "intelligence", "investigate", "search",
        "find", "locate", "track", "monitor", "watch", "surveillance",
        "reconnaissance", "scout", "probe", "scan", "enumeration",
    ],
    "business": [
        "business", "company", "market", "revenue", "profit", "cost",
        "budget", "forecast", "strategy", "plan", "growth", "investment",
        "roi", "kpi", "metrics", "analytics", "dashboard", "report",
    ],
    "code": [
        "code", "function", "class", "method", "compile", "import",
        "module", "refactor", "debug", "bug", "fix", "patch", "git",
        "merge", "commit", "branch", "test", "lint", "type",
    ],
    "professional": [
        "professional", "report", "analysis", "research", "study",
        "review", "assessment", "evaluation", "audit", "compliance",
        "regulation", "policy", "procedure", "guideline", "standard",
    ],
}


def classify_domain(prompt: str) -> str:
    """Classify the prompt into a domain. Falls back to 'general'."""
    lower = prompt.lower()
    scores: Dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


# ── Profile / Agent Loading ─────────────────────────────────────────────────
_PROFILE_CACHE: Dict[str, dict] = {}


def load_profile(name: Optional[str] = None) -> dict:
    """Load a profile by name. Cached. Falls back to defaults."""
    name = name or _DEFAULT_PROFILE
    if name in _PROFILE_CACHE:
        return _PROFILE_CACHE[name]
    path = _PROFILE_DIR / f"{name}.json"
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = _FALLBACK_PROFILE
    except Exception:
        data = _FALLBACK_PROFILE
    _PROFILE_CACHE[name] = data
    return data


_FALLBACK_PROFILE = {
    "name": "fallback",
    "preferred_style": "terse",
    "verbosity": "low",
    "default_shrink_mode": "aggressive",
    "agents": {
        "default": {"role": "generalist", "style": "terse",
                    "max_output_tokens": 1024},
    },
    "domain_prompts": {
        "general": "Plain language, no filler, lead with the answer.",
    },
    "explicit_rules": [
        "No filler ('a lot of', 'kind of', 'just', 'really', 'very').",
        "Lead with the answer or the action.",
    ],
}


def load_agent(profile: dict, agent_name: Optional[str] = None) -> dict:
    """Pick an agent persona from the profile."""
    agents = profile.get("agents", {}) or {}
    name = agent_name or "default"
    if name in agents:
        return {"name": name, **agents[name]}
    if "default" in agents:
        return {"name": "default", **agents["default"]}
    return {"name": "default",
            "role": "generalist", "style": "terse",
            "max_output_tokens": 1024}


# ── Filler / Stopword Sets ──────────────────────────────────────────────────
_FILLER_PHRASES = [
    "i want to know", "i want", "i'd like", "i would like",
    "can you tell me", "can you", "could you",
    "i need you to", "i need", "help me with", "help me",
    "please", "thanks", "thank you",
    "a lot of", "kind of", "sort of", "type of",
    "basically", "essentially", "literally", "actually",
    "just", "really", "very", "quite", "pretty",
    "in order to", "for the purpose of",
    "as well as", "in addition to",
    "due to the fact that", "in spite of the fact that",
    "at this point in time", "at the present time",
    "i was wondering", "i'm wondering",
    "do you think", "would you be able",
    "it's important to note", "it should be noted",
]

_FRAGMENT_PATTERNS = [
    r"\.{3,}",            # "..." "...."
    r"\b(\w+)\s+\1\b",    # "the the"
    r"\s+,",              # " ,"
    r",\s*,",             # ", ,"
    r"\s+\.",             # " ."
    r"\?{2,}", r"!{2,}",
]

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "must", "shall", "can",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "what", "which", "who", "whom", "whose", "where",
    "when", "why", "how", "if", "then", "than", "so", "such", "no", "not",
    "only", "own", "same", "too", "very", "just", "also",
}


# ── Stage: reframe (strip filler + dedupe + normalize) ─────────────────────
def reframe_prompt(prompt: str) -> str:
    """Strip filler phrases, drop fragments, dedupe sentences, fix whitespace."""
    if not prompt:
        return prompt
    s = prompt

    # 1. Drop filler phrases (case-insensitive)
    for phrase in _FILLER_PHRASES:
        s = re.sub(r"\b" + re.escape(phrase) + r"\b", "", s,
                   flags=re.IGNORECASE)

    # 2. Drop fragment patterns
    for pat in _FRAGMENT_PATTERNS:
        s = re.sub(pat, " ", s)

    # 3. Split into sentences, dedupe (case-insensitive, ignoring punctuation)
    raw_sents = re.split(r"(?<=[.!?])\s+|\n+", s)
    seen = set()
    kept: List[str] = []
    for sent in raw_sents:
        norm = re.sub(r"[^a-z0-9 ]", " ", sent.lower()).strip()
        norm = re.sub(r"\s+", " ", norm)
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        kept.append(sent.strip())

    # 4. Re-join, normalize whitespace
    out = " ".join(kept)
    out = re.sub(r"\s+", " ", out).strip()

    # 5. Capitalize first letter, ensure terminal punctuation
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    if out and out[-1] not in ".!?":
        out += "."

    return out


# ── Stage: shrink (rephrase via tiny, preserve intent) ─────────────────────
_SHRINK_SYSTEM = (
    "You are a prompt rewriter. Rephrase the user's message into a tight, "
    "clear prompt that PRESERVES the original intent exactly. Strip filler, "
    "fragments, false starts, and repetition. Keep every actionable detail. "
    "Output ONLY the rewritten prompt — no commentary, no quotes, no labels."
)


def _tiny_rephrase(prompt: str, max_words: int) -> Optional[str]:
    """Use the overseer (tiny model on :8082) to rephrase + shrink while
    preserving intent. Returns None if tiny is unavailable."""
    try:
        from lib import tiny_llm
        if not tiny_llm.is_available():
            return None
        instr = (f"Rewrite this prompt in at most {max_words} words. "
                 f"Keep every detail that affects what the user wants done. "
                 f"Drop filler only.\n\n{prompt}")
        out = tiny_llm.query(instr, system=_SHRINK_SYSTEM,
                             max_tokens=max(64, max_words * 2),
                             temperature=0.1)
        if not out:
            return None
        # Strip any quoting / labels the tiny may add
        out = out.strip().strip('"').strip("'").strip()
        out = re.sub(r"^(rewritten|output|prompt):\s*", "", out,
                     flags=re.IGNORECASE).strip()
        return out or None
    except Exception:
        return None


def shrink_prompt(prompt: str, max_tokens: int = 50,
                  mode: str = "balanced") -> str:
    """Rephrase to a tight prompt that preserves intent.

    Primary: route through the overseer (tiny model) which rephrases
    semantically. Falls back to local sentence-rank if the tiny is unavailable.

    mode='aggressive'  — ~20 words (caveman)
    mode='balanced'    — ~50 words (default; tight business prose)
    mode='preserve'    — ~150 words (light cleanup only)
    """
    if not prompt:
        return prompt
    if mode == "aggressive":
        max_words = 20
    elif mode == "balanced":
        max_words = 50
    else:
        max_words = 150

    # Primary path: tiny rephrases the rambling in its own words, preserving
    # intent. This is what makes the big model produce equivalent output.
    tiny_out = _tiny_rephrase(prompt, max_words)
    if tiny_out:
        return tiny_out

    # Fallback: sentence-rank + cap (no semantic guarantee, but better than
    # nothing when tiny is down)
    sents = re.split(r"(?<=[.!?])\s+|\n+", prompt)
    sents = [s.strip() for s in sents if s.strip()]
    query_words = {w for w in re.findall(r"[a-z0-9]+", prompt.lower())
                   if len(w) > 3}

    def _rank(s: str) -> float:
        ws = re.findall(r"[a-z0-9]+", s.lower())
        return sum(2 for w in ws if w in query_words) + len(ws)

    ranked = sorted(sents, key=_rank, reverse=True)
    order = {s: i for i, s in enumerate(sents)}
    ranked.sort(key=lambda s: order.get(s, 0))
    kept: List[str] = []
    word_count = 0
    for sent in ranked:
        sw = len(sent.split())
        if word_count + sw > max_words and kept:
            break
        kept.append(sent)
        word_count += sw
    out = " ".join(kept).strip()
    return out or prompt


# ── Stage: minify (character-level squeeze) ────────────────────────────────
def minify_prompt(prompt: str) -> str:
    """Further squeeze: collapse whitespace, drop redundant punctuation."""
    if not prompt:
        return prompt
    s = re.sub(r"\s+", " ", prompt).strip()
    s = re.sub(r"[,;:!?]{2,}", "", s)
    return s


# ── Stage: build system prompt from profile + agent + domain ───────────────
def build_system(profile: dict, agent: dict, domain: str) -> str:
    """Compose a tight system prompt from profile + agent + domain."""
    role = agent.get("role", "generalist")
    style = agent.get("style", "terse")
    rules = profile.get("explicit_rules") or []
    domain_prompts = profile.get("domain_prompts") or {}
    domain_hint = domain_prompts.get(domain) or domain_prompts.get("general") \
        or "Plain language, no filler."

    parts = [
        f"Role: {role}.",
        f"Style: {style}.",
        f"Domain ({domain}): {domain_hint}",
    ]
    if rules:
        parts.append("Rules: " + "; ".join(rules[:6]))
    parts.append("Output: lead with the answer or action. No filler.")
    return " ".join(parts)


# ── Main entry ──────────────────────────────────────────────────────────────
def frame_prompt(prompt: str, system_prompt: str = "",
                 domain: Optional[str] = None,
                 profile_name: Optional[str] = None,
                 agent_name: Optional[str] = None,
                 shrink_mode: Optional[str] = None
                 ) -> Tuple[str, str, str]:
    """Full pipeline: reframe → shrink → minify + build tight system prompt.

    Returns: (reframed_prompt, system_prompt, domain)
    """
    if not prompt:
        return prompt, system_prompt, "general"

    profile = load_profile(profile_name)
    agent = load_agent(profile, agent_name)
    domain = domain or classify_domain(prompt)
    mode = shrink_mode or profile.get("default_shrink_mode") or "aggressive"

    reframed = reframe_prompt(prompt)
    shrunk = shrink_prompt(reframed, mode=mode)
    minified = minify_prompt(shrunk)
    sys_prompt = build_system(profile, agent, domain)

    # Preserve caller's system_prompt if they passed one — our built one is
    # advisory and only used when caller passes empty.
    if system_prompt:
        final_system = system_prompt + "\n\n" + sys_prompt
    else:
        final_system = sys_prompt

    return minified, final_system, domain


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        tests = [
            ("What is the capital of France?", None),
            ("Investigate the security posture of this server "
             "and check for any IOCs", None),
            ("Help me with my homework please can you "
             "just basically tell me what is the answer "
             "really kind of like basically", None),
            ("go through all of our docs. Remove any of "
             "the old shit remove any of the redundancy "
             "remove anything that is going to affect our "
             "latest build. update the poll diversion "
             "stuff...", None),
        ]
        for text, agent in tests:
            refr, sysp, dom = frame_prompt(text, "", agent_name=agent)
            print(f"\n  IN:  {text[:120]!r}")
            print(f"  DOM: {dom}")
            print(f"  OUT: {refr}")
            print(f"  SYS: {sysp[:160]}...")
            print("  " + "─" * 60)
        return

    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not prompt:
        prompt = ("Help me with this. Can you basically just "
                  "tell me what is really the answer.")
    refr, sysp, dom = frame_prompt(prompt, "")
    print(f"Domain: {dom}")
    print(f"Reframed prompt:\n  {refr}")
    print(f"System prompt:\n  {sysp}")


if __name__ == "__main__":
    main()