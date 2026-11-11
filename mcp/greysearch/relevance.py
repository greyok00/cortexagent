#!/usr/bin/env python3
"""relevance.py - the two-stage relevance gate for the greysearch pipeline.

Pipeline position:

    search results -> deterministic pre-filter -> scrape & clean main content
      -> semantic relevance judge -> ACCEPTED evidence corpus only
      -> fact extraction -> guide publisher -> scrub/drift enforcement -> site

Stage 1 - prefilter(): cheap, deterministic, runs BEFORE scraping. Rejects
search/tag/category/homepage/feed/pagination pages, dictionary + affiliate +
listicle shapes, and results with poor question-token coverage. Deprioritizes
(not rejects) high-boilerplate or low-coverage results.

Stage 2 - judge_pages(): post-scrape judge, FULLY DETERMINISTIC (LLM-free).
Input is ONLY query + guide type + title + URL + headings + the cleaned body
text; never raw HTML, navigation, cookie banners, footers, or whole pages.
The cleaned body is preferred over the
excerpt because page_clean caps the excerpt at EXCERPT_MAX (2,000 chars), which
would make a larger judge window inert. Returns the structured decision:
    {decision: accept|quarantine|reject, relevance_score: 0-100,
     source_type, reason, allowed_content[], risk_flags[]}

Thresholds: accept >= 75, quarantine 55-74 (cannot feed the guide by default),
reject < 55. Deterministic scoring can also under-score canonical reference
material (docs pages read as reference, not tutorials), so a deterministic
primary-source exception upgrades a clean, non-thin page from an
official/reference source to accept; see _is_primary_reference_source and
the exception block in judge_pages. The exception is entity-guarded and never
applies to news, marketing, or listicles.

Failure policy: the deterministic judge cannot go down or fail to parse, so
there is no quarantine-on-failure path anymore. A page is never auto-accepted.

Topic-drift and noise guards (focal_tail_drift / noise_shape_warnings, both
deterministic and applied inside judge_pages): a page may share the broad
HEAD of a question ("X.509 certificate") while never using the FOCAL TAIL
("pinning") that defines the subject; that page is downgraded out of the
accepted corpus to quarantine with an off_topic flag and a recorded
quality warning instead of passing silently. Likewise a body dominated by
commit-log / cookie-banner / citation-debris lines is flagged. A missing
LEADING token (an explainer that never spells "X.509") does NOT trigger;
only a missing tail does. Every downgraded decision carries a
`quality_warnings` list so the run reporter can relay it.

Also here: rank_results() (semantic score first; snippet length is NOT a
signal) and gate_image() (semantic image gate used research-side; the site
builder re-applies the same rules deterministically, per section).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import page_clean
from image_gate import (STOCK_ALT_RE, shared_junk_reason)

# JUDGE_BATCH: pages per batch inside the deterministic judge's scoring loop
# (research_integration feeds them through as a list). Batching knob only:
# it never changes what the judge scores. Kept for API compatibility with
# callers that pass batch sizes.
JUDGE_BATCH = 1
JUDGE_EXCERPT_CHARS = 4000

ACCEPT_SCORE = 75
QUARANTINE_SCORE = 55

# Named gating constants: every value below is the value the gate has
# always applied; only the names are newer. These rules edit user-visible
# content (pages are quarantined/rejected, images and sections are dropped),
# so each decision traces to a named number here.
PREFILTER_COVERAGE_FLOOR_SHORT = 0.34
PREFILTER_FLOOR_TOKEN_COUNT = 8
PREFILTER_FLOOR_MIN = 0.06
PREFILTER_FLOOR_DIVISOR = 2.5
DEPRIORITIZE_COVERAGE = 0.60
JUDGE_BASE_SCORE = 50.0
JUDGE_TITLE_WEIGHT = 40.0
JUDGE_HEADING_WEIGHT = 8.0
JUDGE_BODY_WEIGHT = 15.0
JUDGE_SCOPE_WEIGHT = 7.0
JUDGE_CONSENSUS_BONUS = 10.0
JUDGE_CONSENSUS_COVERAGE = 0.6
JUDGE_ZERO_COVERAGE_SCORE = 30.0
JUDGE_THIN_PENALTY = 20.0
JUDGE_MARKETING_CAP = 54.0
JUDGE_LONG_QUERY_TOKENS = 20
JUDGE_LONG_QUERY_OVERRIDE_COVERAGE = 0.40
QUESTION_WINDOW_CHARS = 12000
ENTITY_EXCERPT_CHARS = 2000
ENTITY_BODY_CHARS = 6000
THIN_PAGE_CHARS = page_clean.MIN_MAIN_CHARS

PRIMARY_SOURCE_MIN_SCORE = 50
CANONICAL_SOURCE_MIN_SCORE = 0
PRIMARY_SOURCE_EXCEPTION_REASON = (
    "primary source exception: official/reference material that matches the scope")

_BAD_URL_PATH = re.compile(
    r"(?i)(^|/)(search|results|tag|tags|category|categories|author|authors|"
    r"feed|feeds|rss|atom|amp|print|login|signin|signup|register|checkout|"
    r"cart|account|wp-admin|wp-login|admin|search\.php|index\.php)"
    r"(/|$|\?|#)")
_BAD_URL_QUERY = re.compile(
    r"(?i)[?&](page|paged|offset|sort|filter|s|search|q|query)=")
_HOMEPAGE_PATH = re.compile(r"^/[a-z]{0,2}(-[a-z]{2})?/?$")

_AFFILIATE_TITLE = re.compile(
    r"(?i)\b(top\s+\d+|best\s+\d+|\d+\s+best|\d+\s+top|reviewed and compared|"
    r"we tested|our (?:top )?picks|buying guide|\d+\s+(?:best|top)\b|"
    r"affiliate|roundup|listicle)\b")
_DICTIONARY_TITLE = re.compile(
    r"(?i)\b(definition of|meaning of|what does .* mean|synonyms? for|"
    r"translate \w+ to|how to pronounce)\b")

_AFFILIATE_HOSTS = re.compile(
    r"(?i)(?:^|\.)(?:affiliate|affiliates|partners?|bestreviews|"
    r"top10|top-ten|listverse|coupons?|deals?|best-deals?|"
    r"top-\d+|casinos?|slots?|gacor|poker|betting|togel|judi|"
    r"(?!alphabet)\w*bet\b|\w*slot\d*)"
    r"\.(?:com|net|org|io|co|xyz|vip|top|icu)\b")

_SOURCE_TYPE_BY_TIER = {
    "primary": "official_docs",
    "secondary": "technical_reference",
    "unlisted": "unknown",
}
_SOURCE_TYPE_BY_DOMAIN = re.compile(
    r"(?i)(?:^|\.)(?:docs?\.|developer\.|learn\.|support\.|help\.|"
    r"aka\.ms|microsoft\.com|apple\.com|mozilla\.org|ietf\.org|nist\.gov|"
    r"cisa\.gov|fbi\.gov|sec\.gov|gov|edu|edu\.[a-z]{2}|ac\.[a-z]{2}|mitre\.org|arxiv\.org|acm\.org|"
    r"ieee\.org|w3\.org|owasp\.org|sans\.org|us-cert\.circl\.lu|"
    r"github\.com|gitlab\.com|stackoverflow\.com|en\.wikipedia\.org|"
    r"first\.org|cisa\.gov|cisa)")
_SOURCE_TYPE_NEWS = re.compile(
    r"(?i)(?:^|\.)(?:reuters|apnews|ap\.org|bbc|npr|theguardian|nytimes|"
    r"washingtonpost|bloomberg|ft\.com|wsj|arstechnica|theregister|"
    r"techcrunch|theverge|wired|bleepingcomputer|crowdstrike|sentinelone|"
    r"mandiant|unit42|recordedfuture|mandiant|eset|kaspersky|symantec|"
    r"malwarebytes|trendmicro|virustotal|abuse\.ch|cisa\.gov)")

_OFFICIAL_DOC_PREFIX = re.compile(
    r"(?i)^(?:docs?|developer|learn|support|help)\.")
_PRIMARY_SOURCE_DOMAINS = re.compile(
    r"(?i)(?:^|\.)(?:mitre\.org|attack\.mitre\.org|learn\.microsoft\.com|"
    r"docs\.microsoft\.com|man7\.org|apple\.com|developer\.apple\.com|"
    r"nist\.gov|nvd\.nist\.gov|cisa\.gov|volatilityfoundation\.org|"
    r"edu|edu\.[a-z]{2}|ac\.[a-z]{2}|britannica\.com|khanacademy\.org|"
    r"yara\.readthedocs\.io|capev2\.readthedocs\.io|readthedocs\.io|"
    r"ietf\.org|rfc-editor\.org|w3\.org|kernel\.org|docs\.kernel\.org|"
    r"gnu\.org|owasp\.org|first\.org|docs\.python\.org|"
    r"developer\.mozilla\.org)\b")

_PROCEDURAL_TITLE = re.compile(
    r"(?i)\b(how to|guide|tutorial|walkthrough|step[- ]by[- ]step|"
    r"getting started|setup|install|configure|deploy|checklist|"
    r"playbook|runbook|reference|docs?|documentation|manual|handbook|"
    r"explained|101|fundamentals|basics)\b")

_TIME_WORDS = re.compile(
    r"(?i)\b(202[4-9]|latest|recent|current|newest|today|this (?:week|month|"
    r"year)|breaking|update[sd]? (?:in|as of)|2025|2026)\b")

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "its", "may", "new", "now", "old", "see", "two", "way", "who",
    "with", "from", "that", "this", "what", "when", "your", "than", "then",
    "into", "over", "such", "use", "used", "using", "via", "per",
}

ACRONYM_EXPANSIONS = {
    "waf": "firewall web application firewall",
    "vpn": "vpn private network",
    "ngfw": "next generation firewall",
    "utm": "unified threat management",
    "siem": "security information event management",
    "edr": "endpoint detection response",
    "xdr": "extended detection response",
    "mfa": "multi factor authentication",
    "sso": "single sign on",
    "rbac": "role based access control",
    "dmz": "demilitarized zone network",
    "ids": "intrusion detection",
    "ips": "intrusion prevention",
    "ct": "certificate transparency",
    "xss": "cross site scripting",
    "csrf": "cross site request forgery",
    "iot": "internet of things",
    "llm": "large language model",
    "vm": "virtual machine",
    "os": "operating system",
    "ssrf": "server side request forgery",
    "acl": "access control list",
}

def _stem(tok: str) -> str:
    """Light plural stemming, both sides identically: 'firewalls' ==
    'firewall' (a singular/plural mismatch once zeroed title coverage).
    Deliberately simple: the two SIDES just have to agree."""
    t = tok
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t

def question_tokens(question: str) -> set:
    raw = [_stem(t) for t in re.split(r"[^a-z0-9]+",
                                      (question or "").lower())
           if len(t) > 2 and t not in _STOPWORDS]
    out = set(raw)
    for t in raw:
        exp = ACRONYM_EXPANSIONS.get(t)
        if exp:
            out |= {_stem(w) for w in exp.split()}
    return out

def _domain(url: str) -> str:
    try:
        d = urlparse(url or "").netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""

def token_coverage(text: str, tokens: set) -> float:
    """Share of question tokens present in title+url+snippet text (0-1)."""
    if not tokens:
        return 1.0
    hay = (text or "").lower()
    hay_words = {_stem(w) for w in re.findall(r"[a-z0-9]+", hay)}
    return sum(1 for t in tokens if _stem(t) in hay_words) / len(tokens)

def prefilter(url: str,
              title: str = "",
              snippet: str = "",
              domain: str = "",
              tier: str = "",
              tokens: Optional[set] = None,
              question: str = "") -> Dict[str, Any]:
    """Stage-1 deterministic gate on a SEARCH RESULT (pre-scrape).

    Returns {decision: accept|deprioritize|reject, reason, coverage,
    procedural, tier}. 'deprioritize' pages may still be scraped but rank
    below clean results; 'reject' pages never reach the scraper.
    """
    tokens = tokens if tokens is not None else question_tokens(question)
    dom = domain or _domain(url)
    path = urlparse(url or "").path or "/"
    title = title or ""
    decision, reason = "accept", ""
    coverage = token_coverage(" ".join([title, url, snippet]), tokens)

    if _AFFILIATE_HOSTS.search(dom or ""):
        return {"decision": "reject", "reason": "affiliate/coupon host",
                "coverage": coverage, "procedural": False, "tier": tier}
    if _BAD_URL_PATH.search(path) or _BAD_URL_QUERY.search(url or ""):
        return {"decision": "reject",
                "reason": "search/tag/category/feed/pagination URL",
                "coverage": coverage, "procedural": False, "tier": tier}
    if _HOMEPAGE_PATH.match(path) and not _PROCEDURAL_TITLE.search(title):
        return {"decision": "reject", "reason": "homepage (no article signal)",
                "coverage": coverage, "procedural": False, "tier": tier}
    if _DICTIONARY_TITLE.search(title):
        return {"decision": "reject", "reason": "dictionary/definition page",
                "coverage": coverage, "procedural": False, "tier": tier}
    if _AFFILIATE_TITLE.search(title) and coverage < 0.5:
        return {"decision": "reject",
                "reason": "affiliate/listicle title with weak topic coverage",
                "coverage": coverage, "procedural": False, "tier": tier}
    _n_tok = len(tokens) if tokens else 0
    _floor = (PREFILTER_COVERAGE_FLOOR_SHORT
              if _n_tok <= PREFILTER_FLOOR_TOKEN_COUNT
              else min(PREFILTER_COVERAGE_FLOOR_SHORT,
                       max(PREFILTER_FLOOR_MIN,
                           PREFILTER_FLOOR_DIVISOR / _n_tok)))
    if tokens and coverage < _floor:
        return {"decision": "reject",
                "reason": (f"low topic-token coverage ({coverage:.0%}; "
                           f"floor {_floor:.0%} for {_n_tok}-token question)"),
                "coverage": coverage, "procedural": False, "tier": tier}

    procedural = bool(_PROCEDURAL_TITLE.search(title))
    if coverage < DEPRIORITIZE_COVERAGE:
        decision, reason = "deprioritize", "partial topic coverage"
    return {"decision": decision, "reason": reason, "coverage": coverage,
            "procedural": procedural, "tier": tier}

def _debug_last_judge(text: str) -> None:
    """Ring-buffer the last judge replies in-process so a judge_parse_failed
    quarantine can be diagnosed without re-running the scrape."""
    _JUDGE_DEBUG.append(text)
    del _JUDGE_DEBUG[:-4]

_JUDGE_DEBUG: List[str] = []

def last_judge_replies() -> List[str]:
    return list(_JUDGE_DEBUG)

_FENCE_ARR_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.S)
_FENCE_OBJ_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_PAGE_OBJ_RE = re.compile(
    r"\{\s*\"page\"\s*:\s*\d+.*?\n\s*\}", re.S)
_OBJ_SHAPE_RE = re.compile(
    r"\{[^{}]*\"page\"[^{}]*\"(?:decision|relevance_score)\"[^{}]*\}", re.S)

def _normalize_decision(obj: Optional[Dict[str, Any]],
                        fallback_reason: str) -> Dict[str, Any]:
    """Coerce a parsed judge object into the required shape. Any parse/validation
    failure becomes a QUARANTINE (never an accept)."""
    base = {"decision": "quarantine", "relevance_score": 50,
            "source_type": "unknown", "reason": fallback_reason,
            "allowed_content": [], "risk_flags": []}
    if not isinstance(obj, dict):
        return base
    decision = str(obj.get("decision", "")).strip().lower()
    if decision not in ("accept", "quarantine", "reject"):
        decision = "quarantine"
    try:
        score = int(obj.get("relevance_score", 50))
    except Exception:
        score = 50
    score = max(0, min(100, score))
    if score >= ACCEPT_SCORE:
        decision = "accept"
    elif score < QUARANTINE_SCORE:
        decision = "reject"
    else:
        decision = "quarantine"
    st = str(obj.get("source_type", "unknown")).strip().lower()
    if st not in ("official_docs", "primary_source", "technical_reference",
                  "news", "commercial", "forum", "unknown"):
        st = "unknown"
    allowed = obj.get("allowed_content")
    if not isinstance(allowed, list):
        allowed = []
    allowed = [str(a) for a in allowed
               if str(a) in ("procedures", "specifications", "background",
                             "images")]
    flags = obj.get("risk_flags")
    if not isinstance(flags, list):
        flags = []
    flags = [str(f) for f in flags
             if str(f) in ("boilerplate", "off_topic", "thin_content",
                           "sales_copy", "outdated", "unsupported",
                           "commit_log")]
    return {"decision": decision, "relevance_score": score,
            "source_type": st,
            "reason": str(obj.get("reason", fallback_reason))[:300] or fallback_reason,
            "allowed_content": allowed, "risk_flags": flags}

_GENERIC_ENTITY_TERMS = frozenset({"compromise", "compromised"})

def contamination_check(page: Dict[str, Any],
                        required_entities: Sequence[Sequence[str]]) -> Dict[str, Any]:
    """Deterministic topic check. Every group must be represented by:
    a non-generic term in the title, URL, headings, or excerpt; a generic term
    in the title, URL, or headings; a non-generic term repeated at least twice
    in the body; or two distinct non-generic terms in the body. A page can
    share the topic words and still teach the wrong subject; this is the guard
    that catches MDN-style drift that the semantic judge sometimes accepts."""
    title_text = " ".join([
        page.get("title") or "",
        page.get("canonical_url") or page.get("url") or "",
        " ".join(page.get("h2s") or []),
    ]).lower()
    focused_text = title_text + " " + (page.get("excerpt") or "")[
        :ENTITY_EXCERPT_CHARS].lower()
    body_text = (page.get("body_text") or "")[:ENTITY_BODY_CHARS].lower()
    matched: List[str] = []
    for group in required_entities:
        terms = [str(term) for term in group if str(term).strip()]
        non_generic = [term for term in terms
                       if term.lower() not in _GENERIC_ENTITY_TERMS]
        hit = next((term for term in non_generic
                    if term.lower() in focused_text), None)
        if hit is None:
            hit = next((term for term in terms
                        if term.lower() in _GENERIC_ENTITY_TERMS
                        and term.lower() in title_text), None)
        if hit is None:
            hit = next((term for term in non_generic
                        if body_text.count(term.lower()) >= 2), None)
        if hit is None:
            present = [term for term in non_generic
                       if body_text.count(term.lower()) >= 1]
            if len(present) >= 2:
                hit = present[0]
        if hit is None:
            return {"clean": False, "matched": matched,
                    "reason": "missing required entity: " + "/".join(terms)}
        matched.append(hit)
    return {"clean": True, "matched": matched, "reason": "all entity groups matched"}

_NOISE_LINE_RE = re.compile(
    r"(?i)^(?:\d{4}-\d{2}-\d{2}\s*)?"
    r"(?:[0-9a-f]{7,40}\b"
    r"|merge (?:pull request|branch|remote)\b"
    r"|jump up to:"
    r"|we use cookies|accept(?: all)? cookies?|manage cookies?"
    r"|cookie (?:policy|settings|notice|preferences)"
    r"|\b(?:bump|chore|feat|fix|refactor|revert|test|build|ci|docs|perf)"
    r"(?:[:(]|\s))")
NOISE_RATIO_FLOOR = 0.40
NOISE_MIN_LINES = 8

def noise_line_ratio(text: str) -> float:
    """Share of a body's non-empty lines that are commit-log / banner /
    citation debris (0-1). Deterministic, cheap, and no network."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if _NOISE_LINE_RE.match(ln))
    return hits / len(lines)

def noise_shape_warnings(page: Dict[str, Any]) -> List[str]:
    """Quality warnings for a page whose visible body is dominated by
    commit-log / cookie-banner / citation debris instead of article prose
    (real-world cases: commit-log-heavy repo mirrors and banner-glued
    scrape targets)."""
    body = (page.get("body_text") or page.get("excerpt") or "")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) < NOISE_MIN_LINES:
        return []
    ratio = noise_line_ratio(body)
    if ratio < NOISE_RATIO_FLOOR:
        return []
    return [f"commit-log noise: {ratio:.0%} of body lines are commit-log / "
            "cookie-banner / citation debris, not article prose; text "
            "quality is thin relative to its size"]

def ordered_question_tokens(question: str) -> List[str]:
    """The question's own content tokens in ORIGINAL order, deduped. Unlike
    question_tokens() this deliberately EXCLUDES acronym-expansion words: the
    tail-drift guard judges the wording the asker actually used, not its
    expansions."""
    out: List[str] = []
    for t in re.split(r"[^a-z0-9]+", (question or "").lower()):
        t = t.strip()
        if t and len(t) > 2 and t not in _STOPWORDS and t not in out:
            out.append(t)
    return out

def focal_tail_drift(question: str, page: Dict[str, Any]) -> Optional[str]:
    """Focal-tail drift guard. Trigger: the question's LAST content token (the focal
    tail: 'pinning' in "what is X.509 certificate pinning") appears NOWHERE
    in title/url/headings/body while earlier, broader head tokens DO. Such a
    page answers the head of the question and is topically adjacent, not
    on-target. Missing a LEADING token (an explainer that never spells
    "X.509") does NOT trigger, so acronym-free explainers are never punished.
    Returns the warning string, or None when the page is not head-only."""
    ordered = ordered_question_tokens(question)
    if len(ordered) < 2:
        return None
    hay = " ".join([
        page.get("title") or "",
        page.get("canonical_url") or page.get("url") or "",
        " ".join(str(h) for h in (page.get("h2s") or [])),
        (page.get("body_text") or page.get("excerpt") or "")[
            :QUESTION_WINDOW_CHARS],
    ]).lower()
    hay_words = {_stem(w) for w in re.findall(r"[a-z0-9]+", hay)}
    if _stem(ordered[-1]) in hay_words:
        return None
    covered = [t for t in ordered[:-1] if _stem(t) in hay_words]
    if not covered:
        return None
    missing = [t for t in ordered if _stem(t) not in hay_words]
    return (f"off-topic drift: the question's focal tail term(s) "
            f"{', '.join(missing)} never appear while the broader head "
            f"terms ({', '.join(covered)}) do; the page answers the head "
            "of the question, not the subject itself")

def classify_source_type(domain: str, tier: str, title: str = "") -> str:
    """Deterministic source-type hint used when the judge is unavailable and
    to sanity-check the judge's classification."""
    if tier == "primary" or tier == "official":
        return "official_docs"
    if _SOURCE_TYPE_BY_DOMAIN.search(domain or ""):
        return "technical_reference"
    if _SOURCE_TYPE_NEWS.search(domain or ""):
        return "news"
    if tier == "secondary":
        return "technical_reference"
    return "unknown"

def _deterministic_official_domain(page: Dict[str, Any]) -> bool:
    """Domain/tier signals that corroborate an official/primary source.

    Deliberately does NOT trust the judge's source_type on its own: a judge
    mislabel must not promote an arbitrary blog. A docs./developer./learn.
    prefix or one of the explicit official hosts counts, as does a
    primary/official search tier."""
    dom = _domain(page.get("canonical_url") or page.get("url") or "")
    if _PRIMARY_SOURCE_DOMAINS.search(dom):
        return True
    if _OFFICIAL_DOC_PREFIX.search(dom):
        return True
    hint = classify_source_type(dom, str(page.get("tier") or ""),
                                page.get("title") or "")
    return hint in ("official_docs", "primary_source")

def _is_primary_reference_source(page: Dict[str, Any],
                                 source_type: str = "") -> bool:
    """True when the page is official documentation, a standard, or another
    primary source. News/commercial/forum classifications veto; otherwise the
    deterministic domain/tier signals must corroborate the judge."""
    st = (source_type or "").strip().lower()
    if st in ("news", "commercial", "forum"):
        return False
    return _deterministic_official_domain(page)

def _canonical_source_floor(page: Dict[str, Any], source_type: str = "") -> int:
    """Score floor for the primary-source exception. Deterministically
    canonical sources get CANONICAL_SOURCE_MIN_SCORE; any other page needs the
    general PRIMARY_SOURCE_MIN_SCORE."""
    if _deterministic_official_domain(page):
        return CANONICAL_SOURCE_MIN_SCORE
    return PRIMARY_SOURCE_MIN_SCORE

def _page_is_thin(page: Dict[str, Any]) -> bool:
    """Thin = less than ~800 chars of real substance (the judge prompt's own
    thin_content threshold). A thin primary source is not worth promoting."""
    body = (page.get("body_text") or page.get("excerpt") or "").strip()
    return len(body) < THIN_PAGE_CHARS

def _is_marketing_or_listicle(page: Dict[str, Any], source_type: str = "",
                              risk_flags: Optional[Sequence[str]] = None) -> bool:
    """Block marketing/news/listicle shapes from the primary-source exception."""
    st = (source_type or "").strip().lower()
    if st in ("news", "commercial"):
        return True
    if "sales_copy" in {str(f) for f in (risk_flags or [])}:
        return True
    title = page.get("title") or ""
    if _AFFILIATE_TITLE.search(title) or _DICTIONARY_TITLE.search(title):
        return True
    dom = _domain(page.get("canonical_url") or page.get("url") or "")
    return classify_source_type(dom, str(page.get("tier") or ""), title) == "news"

def _deterministic_judge_obj(question: str,
                             page: Dict[str, Any],
                             guide_type: str = "research guide",
                             scope: str = "",
                             expected_source_types: Optional[Sequence[str]] = None
                             ) -> Dict[str, Any]:
    """LLM-free relevance decision. Transparent inputs, no model calls:

    base 50 + title coverage x40 + heading coverage x8 + body coverage x15 +
    scope coverage x7 (capped at 100), then penalties. Thresholds unchanged:
    accept >= 75, quarantine 55-74, reject < 55."""
    title = (page.get("title") or "").lower()
    body = ((page.get("body_text") or page.get("excerpt") or "") or "").lower()
    head = " ".join(h or "" for h in (page.get("h2s") or [])).lower()
    dom = _domain(page.get("url") or "")
    st = classify_source_type(dom, str(page.get("tier") or ""),
                              page.get("title") or "")

    toks = question_tokens(question)
    _ord = ordered_question_tokens(question)
    if len(_ord) > JUDGE_LONG_QUERY_TOKENS:
        toks = set(_ord[:JUDGE_LONG_QUERY_TOKENS])
    scope_tok = question_tokens(scope) if (scope or "").strip() else set()
    window = body[:QUESTION_WINDOW_CHARS]
    cov_t = token_coverage(title, toks) if toks else 0.0
    cov_h = token_coverage(head, toks) if toks else 0.0
    cov_b = token_coverage(window, toks) if toks else 0.0
    cov_s = token_coverage(window, scope_tok) if scope_tok else 0.0

    score = (JUDGE_BASE_SCORE + JUDGE_TITLE_WEIGHT * cov_t
             + JUDGE_HEADING_WEIGHT * cov_h + JUDGE_BODY_WEIGHT * cov_b
             + JUDGE_SCOPE_WEIGHT * cov_s)
    if cov_b >= JUDGE_CONSENSUS_COVERAGE:
        score += JUDGE_CONSENSUS_BONUS
    score = min(100.0, score)
    reasons = [f"title coverage {cov_t:.2f}", f"body coverage {cov_b:.2f}",
               f"headings coverage {cov_h:.2f}"]

    if not toks:
        reasons.append("no extractable question tokens: quarantine band")
    elif cov_t == 0.0 and cov_b == 0.0 and cov_h == 0.0:
        score = JUDGE_ZERO_COVERAGE_SCORE
        reasons.append("zero coverage of question tokens: clear topic mismatch")

    if _page_is_thin(page):
        score -= JUDGE_THIN_PENALTY
        reasons.append("thin page penalty")
    risks: List[str] = []
    if _is_marketing_or_listicle(page, st, risks):
        score = min(score, JUDGE_MARKETING_CAP)
        reasons.append("marketing/listicle signal capped to quarantine band")

    score = int(max(0.0, min(100.0, score)))
    if (len(_ord) > JUDGE_LONG_QUERY_TOKENS
            and cov_b >= JUDGE_LONG_QUERY_OVERRIDE_COVERAGE):
        score = max(score, ACCEPT_SCORE + 2)
        reasons.append(f"long-query body-coverage override ({cov_b:.2f})")
    if score >= ACCEPT_SCORE:
        decision = "accept"
    elif score >= QUARANTINE_SCORE:
        decision = "quarantine"
    else:
        decision = "reject"
    return {
        "decision": decision,
        "relevance_score": score,
        "source_type": st,
        "reason": "; ".join(reasons)
                  + f" [deterministic judge - {guide_type}]",
    }

def judge_pages(question: str,
                pages: Sequence[Dict[str, Any]],
                guide_type: str = "research guide",
                *,
                scope: str = "",
                required_entities: Optional[Sequence[Sequence[str]]] = None,
                expected_source_types: Optional[Sequence[str]] = None
                ) -> List[Dict[str, Any]]:
    """Stage-2 judge (deterministic, LLM-free). `pages` are cleaned page
    dicts (from page_clean.clean_page); they MUST carry title/url/h2s/body.
    Returns one decision dict per page, same order. `intern_call` is accepted
    for API compatibility and IGNORED; nothing here calls any model.

    Topic awareness: `scope` and `expected_source_types` steer the
    deterministic scorer. `required_entities` is enforced after normalization
    (an accepted page that fails the entity check is downgraded to quarantine
    and carries a `contamination` record).
    """
    decisions: List[Dict[str, Any]] = []
    pages = list(pages)
    if required_entities:
        required_entities = [list(g) for g in required_entities]
    if expected_source_types:
        expected_source_types = list(expected_source_types)
    _ord_all = ordered_question_tokens(question)
    _drift_short_only = len(_ord_all) <= 8
    for p in pages:
        obj = _deterministic_judge_obj(question, p, guide_type)
        d = _normalize_decision(obj, "deterministic judge")
        if d["source_type"] == "unknown":
            d["source_type"] = classify_source_type(
                _domain(p.get("url") or ""), str(p.get("tier") or ""),
                p.get("title") or "")

        if (d.get("decision") in ("quarantine", "reject")
                and _is_primary_reference_source(p, d.get("source_type"))
                and int(d.get("relevance_score", 0)) >= (
                    _canonical_source_floor(p, d.get("source_type")))):
            cont = (contamination_check(p, required_entities)
                    if required_entities
                    else {"clean": True, "matched": [],
                          "reason": "no required entities supplied"})
            if required_entities:
                d["contamination"] = cont
            if (cont["clean"]
                    and not _page_is_thin(p)
                    and not _is_marketing_or_listicle(
                        p, d.get("source_type"), d.get("risk_flags"))):
                d["judge_score"] = int(d.get("relevance_score", 0))
                d["relevance_score"] = max(
                    int(d.get("relevance_score", 0)), ACCEPT_SCORE)
                d["decision"] = "accept"
                d["primary_source_exception"] = True
                d["reason"] = PRIMARY_SOURCE_EXCEPTION_REASON
        drift = focal_tail_drift(question, p) if _drift_short_only else None
        noise = noise_shape_warnings(p)
        if drift:
            d["focal_tail_drift"] = drift
        if drift or noise:
            warnings = ([drift] if drift else []) + list(noise)
            d["quality_warnings"] = warnings
            if d.get("decision") == "accept":
                d["decision"] = "quarantine"
                d["relevance_score"] = min(
                    int(d.get("relevance_score", 50)), QUARANTINE_SCORE - 1)
                d.pop("primary_source_exception", None)
                flags = list(d.get("risk_flags") or [])
                for f in ((["off_topic"] if drift else [])
                          + (["commit_log"] if noise else [])):
                    if f not in flags:
                        flags.append(f)
                d["risk_flags"] = flags
                d["reason"] = (warnings[0] + " | " + str(d.get("reason") or ""))[:300]
        if d.get("decision") == "accept" and required_entities:
            cont = d.get("contamination") or contamination_check(
                p, required_entities)
            d["contamination"] = cont
            if not cont["clean"]:
                d["decision"] = "quarantine"
                d["relevance_score"] = min(
                    int(d.get("relevance_score", 50)), 54)
                d["reason"] = cont["reason"]
                d.pop("primary_source_exception", None)
        decisions.append(d)
    return decisions

def judge_available() -> bool:
    """Always True: the deterministic judge needs no endpoint."""
    return True

_TIER_ORDER = {"primary": 0, "official": 0, "secondary": 1, "unlisted": 2,
               "excluded": 3}
_OFFICIAL_TYPES = {"official_docs", "primary_source"}

def rank_results(question: str,
                 results: Sequence[Dict[str, Any]],
                 judged: Optional[Dict[str, Dict[str, Any]]] = None,
                 freshness_matters: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Rank search/scrape candidates. Order of signals:
    1. semantic relevance score (judge); falls back to prefilter coverage
    2. source quality/tier
    3. official/primary source status
    4. procedural/task match (how-to/guide/tutorial/docs titles)
    5. freshness: ONLY when the question carries time words
    6. duplicate/domain diversity penalty (applied by the caller via caps;
       here: same-domain results sort after the first)

    Snippet length is deliberately NOT a signal (long dictionary/nav
    snippets used to outrank on-topic pages).
    """
    judged = judged or {}
    if freshness_matters is None:
        freshness_matters = bool(_TIME_WORDS.search(question or ""))
    domain_seen: Dict[str, int] = {}

    def key(r: Dict[str, Any]) -> tuple:
        url = r.get("url") or ""
        dom = _domain(url)
        j = judged.get(url) or judged.get(r.get("canonical_url") or "") or {}
        score = j.get("relevance_score")
        if score is None:
            score = int(round(float(r.get("coverage", 0.5)) * 100))
        tier = str(r.get("tier") or "unlisted")
        stype = str(j.get("source_type") or r.get("source_type") or "")
        procedural = bool(r.get("procedural")
                          or _PROCEDURAL_TITLE.search(r.get("title") or ""))
        official = 1 if (tier in ("primary", "official")
                         or stype in _OFFICIAL_TYPES) else 0
        fresh = 1 if (freshness_matters and _TIME_WORDS.search(
            " ".join([r.get("title") or "", r.get("snippet") or ""])) ) else 0
        dup_penalty = domain_seen.get(dom, 0)
        domain_seen[dom] = dup_penalty + 1
        return (-score, _TIER_ORDER.get(tier, 2), -official, -procedural,
                -fresh, dup_penalty)

    return sorted(list(results), key=key)

_JUNK_IMG_WORDS = re.compile(
    r"(?i)(logo|icon|avatar|badge|banner|button|sprite|favicon|placeholder|"
    r"spacer|pixel|tracking|advertisement|\bad\b|adsense|hero image|"
    r"stock photo|stock image|decorative|divider|separator|arrow|bullet|"
    r"social|share|follow|comment|placeholder|loading|spinner|thumbnail|"
    r"profile photo|author photo|team member|generic|unsplash|pexels|"
    r"shutterstock|getty|freepik|lorem|sample|default|cover image|"
    r"background image|illustration)")
_DIAGRAM_WORDS = re.compile(
    r"(?i)(diagram|flowchart|flow chart|architecture|schematic|wiring|"
    r"circuit|blueprint|wireframe|mockup|screenshot|screen shot|figure|"
    r"fig\.?\s*\d|chart|graph|plot|timeline|infographic|setup|install|"
    r"dashboard|control panel|terminal|cli|ui|interface|step \d|"
    r"process|workflow|pipeline|data flow|network map|topology|"
    r"anatomy|breakdown|comparison|matrix|table|screenshot)")
_STOCK_ALT = STOCK_ALT_RE  # shared definition (image_gate)
_JUNK_IMG_URL = re.compile(
    r"(?i)(/icons?/|/img/icons/|_1px\.|favicon|sprite|placeholder|/buttons?/|"
    r"/banners?/|loading|spinner|tracking|pixel\.|1x1|/logos?/|/avatars?/|"
    r"default[_-]?(image|img|avatar|profile|user|thumb)|gravatar|"
    r"wp-content/uploads/\d{4}/\d{2}/(?:logo|icon|badge|button))")

def gate_image(image: Dict[str, Any],
               section_text: str = "",
               section_heading: str = "",
               page_accepted: bool = True) -> Dict[str, Any]:
    """Semantic image gate. An image is kept only when ALL of:
    - its page was accepted by the relevance judge (page_accepted)
    - it is not logo/avatar/stock decoration/ad/social/hero (junk patterns)
    - its alt has at least 3 words unless it is diagram-shaped (matching
      site_render._image_is_junk, so research and build agree)
    - its alt/caption/context has meaningful overlap with the section
      objective (question/section tokens), OR it is diagram-shaped
      (diagram/screenshot/figure/step/wiring/flowchart...)
    Returns {keep: bool, reason}.
    """
    if not page_accepted:
        return {"keep": False, "reason": "page not accepted"}
    src = (image.get("src") or "")
    alt = (image.get("alt") or "").strip()
    caption = (image.get("caption") or "").strip()
    context = (image.get("context") or "").strip()
    _ij = shared_junk_reason(src, alt, _DIAGRAM_WORDS)
    if _ij:
        return {"keep": False, "reason": _ij}
    if _JUNK_IMG_URL.search(src):
        return {"keep": False, "reason": "chrome/asset URL pattern"}
    if _JUNK_IMG_WORDS.search(alt) or _JUNK_IMG_WORDS.search(caption):
        if not _DIAGRAM_WORDS.search(alt + " " + caption):
            return {"keep": False, "reason": "junk alt/caption (logo/stock/ad)"}
    if _STOCK_ALT.match(alt) and not caption and not _DIAGRAM_WORDS.search(src):
        return {"keep": False, "reason": "generic stock alt, no context"}

    objective = " ".join([section_heading or "", section_text or ""]).lower()
    tokens = question_tokens(objective) if objective.strip() else set()
    probe = " ".join([alt, caption, context]).lower()
    if _DIAGRAM_WORDS.search(probe) or _DIAGRAM_WORDS.search(src.lower()):
        return {"keep": True, "reason": "diagram/screenshot supports an action"}
    if tokens:
        probe_tokens = question_tokens(probe)
        overlap = len(tokens & probe_tokens)
        if overlap >= 2 or (overlap >= 1 and len(probe_tokens) <= 3):
            return {"keep": True,
                    "reason": f"alt/context overlaps section ({overlap} tokens)"}
        if _JUNK_IMG_WORDS.search(probe):
            return {"keep": False,
                    "reason": "no section overlap + chrome-ish context"}
        return {"keep": False,
                    "reason": "alt/context does not overlap the section"}
    return {"keep": bool(_DIAGRAM_WORDS.search(probe)),
            "reason": "no section context; diagram-only"}

if __name__ == "__main__":
    q = "ransomware negotiation playbook double extortion"
    toks = question_tokens(q)
    print("tokens:", sorted(toks))
    for url, title in [
        ("https://example.com/tag/ransomware", "Ransomware - Tags"),
        ("https://docs.example.com/negotiate-playbook", "Negotiation playbook guide"),
        ("https://dict.example.com/ransomware", "Definition of ransomware"),
        ("https://spam.example.com/best-10-vpn-top-5", "Top 10 best VPN deals 2026"),
    ]:
        print(url, "->", prefilter(url, title, "", question=q, tokens=toks))
    img = {"src": "https://example.com/fig2-timeline.png", "alt": "Figure 2: attack timeline",
           "caption": "", "context": "ransomware negotiation timeline steps"}
    print("image:", gate_image(img, section_heading="Ransomware negotiation",
                               section_text="negotiation playbook double extortion"))
