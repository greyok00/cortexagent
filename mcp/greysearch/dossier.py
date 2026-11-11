"""dossier.py: token-lean compression of gathered research for the audit.

The research phase is LLM-free and gathers full pages. The OPTIONAL audit
stage must not pay for full pages in tokens, so everything the model needs
passes through here first: per-page it keeps domain/title/tier/score and the
top sentences ranked by relevance-signal overlap (query + scope words, then
earliest position), deduped across pages, hard-capped by a total character
budget (default 3200 chars ≈ 800 tokens). Deterministic, no model calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

DEFAULT_BUDGET_CHARS = 3200
_PER_PAGE_SENTENCES = 3
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_DOSSIER_SKIP = re.compile(
    r"(?i)(fotolia|getty images|istockphoto|shutterstock|alamy|dreamstime|"
    r"depositphotos|adobe stock|123rf|bigstock|credit[s]?:)"
    r"|skip to (?:search|footer|content|navigation)"
    r"|(?:features?|deals?|trials?)\s+(?:vpn|why|all)\b.*(deals|watch|buy)")

def _clean_dossier_text(text: str) -> str:
    lines = (text or "").split("\n")
    seen: set = set()
    keep: List[str] = []
    for ln in lines:
        if _DOSSIER_SKIP.search(ln):
            continue
        key = ln.strip().lower()[:80]
        if key and key in seen:
            continue
        seen.add(key)
        keep.append(ln)
    return "\n".join(keep)
_WORD = re.compile(r"[a-z0-9][a-z0-9+'-]*")

_STOP = {
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "that",
    "this", "are", "is", "of", "to", "in", "on", "at", "by", "as", "it",
    "be", "how", "what", "which", "when", "why", "does", "do", "can",
    "not", "no", "into", "about", "their", "they", "was", "were",
}

def question_tokens(text: str) -> List[str]:
    return [w for w in _WORD.findall((text or "").lower())
            if len(w) > 1 and w not in _STOP]

def _sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 240:
        return [text] if text else []
    return [s.strip() for s in _SENT_SPLIT.split(text)
            if 40 <= len(s.strip()) <= 420]

def rank_sentences(sents: List[str], key_tokens: List[str]) -> List[str]:
    kset = set(key_tokens)

    def score(i: int) -> Tuple[float, float, float]:
        sent = sents[i]
        words = set(_WORD.findall(sent.lower()))
        cover = len(words & kset) / (len(kset) or 1)
        specificity = min(len(words), 60) / 60.0
        return (cover, specificity, -float(i))

    order = sorted(range(len(sents)), key=score, reverse=True)
    return [sents[i] for i in order]

def build_dossier(result: Dict[str, Any], question: str,
                  budget_chars: int = DEFAULT_BUDGET_CHARS) -> str:
    """Compress an accepted research corpus into a model-ready dossier."""
    key_tokens = question_tokens(question)
    pages = result.get("pages_fetched") if isinstance(
        result.get("pages_fetched"), list) else []
    lines: List[str] = [f"QUESTION: {question.strip()[:200]}"]

    seen_snips: set = set()
    used = len(lines[0]) + 12
    items = pages if isinstance(pages, list) else []
    for idx, p in enumerate(items):
        rel = p.get("relevance") or {}
        clean = p.get("clean") or p
        title = (clean.get("title") or p.get("title") or "").strip()[:120]
        url = (p.get("url") or clean.get("canonical_url") or "")[:100]
        dom = re.sub(r"^www\.", "", (p.get("domain") or url.split("/")[2]
                     if "://" in url.split(" ")[0] else url.split("/")[2])
                     ) if False else (p.get("domain") or _dom(url))
        score = rel.get("relevance_score")
        decision = rel.get("decision", "?")
        body = _clean_dossier_text(clean.get("body_text") or clean.get("text")
                                   or p.get("text") or "")
        sents = _sentences(body)
        top, seen_local = [], set()
        for sent in rank_sentences(sents, key_tokens):
            k = sent[:80]
            if k in seen_local:
                continue
            seen_local.add(k)
            top.append(sent)
            if len(top) >= _PER_PAGE_SENTENCES:
                break
        snip = " ".join(top).strip()[:240]
        if snip and snip[:60] in seen_snips:
            continue
        seen_snips.add(snip[:60] if snip else "")
        line = (f"[{idx}] {dom} | {title} | {decision}"
                f" {'' if score is None else score} | {snip}")
        if used + len(line) + 1 > budget_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)

def _dom(url: str) -> str:
    try:
        host = re.sub(r"^[a-z]+://", "", (url or ""))
        host = host.split("/")[0]
        return re.sub(r"^www\.", "", host)
    except Exception:
        return ""