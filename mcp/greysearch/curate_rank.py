#!/usr/bin/env python3
"""curate_rank: the thinking layer for the greysearch curation pane.

Heuristic first (always available, zero GPU): every paragraph of every
candidate page is scored against the run's question with term coverage,
phrase, density and position signals. The top slice is flagged as the
suggested keep-set, sized by the run's report length.

Optional second opinion: the browser can run a small LLM with WebLLM
(client-side, WebGPU with CPU/wasm fallback - the server's GPU is never
used). The API here just serves the ranked shortlist the model will
re-judge; the model's verdict is merged client-side and is advisory:
heuristic scores stay visible either way.
"""

from __future__ import annotations

import json
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9']+")
_STOP = set("""a an the and or but if then than that this these those of in
on at to for from by with about into over after before between during is
are was were be been being it its their there here what which who whom how
why when where can could should would will may might must do does did done
not no nor so such very more most much many few own same too also just
have has had you your we our us they them he she his her as up down out
off again further once all any both each other some only
""".split())

_KEEP_TARGET = {"brief": 8, "standard": 14, "deep": 20, "report": 28}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower())
            if len(w) > 1 and w not in _STOP]


def _stem(w: str) -> str:
    for suf in ("ing", "ies", "ers", "er", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _query_terms(q: str) -> tuple[list[str], list[str]]:
    toks = _tokens(q)
    stems = [_stem(t) for t in toks]
    phrases = []
    ql = " " + (q or "").lower() + " "
    for n in (3, 2):
        words = _WORD.findall(ql)
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if any(w in _STOP for w in g):
                continue
            phrases.append(" ".join(g))
    return stems, phrases


def score_paragraph(text: str, qstems: list[str], phrases: list[str],
                    early: bool) -> tuple[float, str]:
    """Return (score 0..4ish, why). Purely lexical - no model call."""
    body = (text or "").strip()
    if len(body) < 80:
        return 0.0, "too short to judge"
    toks = _tokens(body)
    if not toks:
        return 0.0, "no usable words"
    tf = Counter(_stem(t) for t in toks)
    n = len(toks)
    hits = [s for s in qstems if s in tf]
    if not hits:
        return 0.0, "no question terms"
    coverage = len(hits) / max(1, len(set(qstems)))
    freq = sum(tf[s] for s in hits)
    density = freq * 100 / n                      # hits per 100 words
    low = " ".join(toks[: min(n, 24)])
    joined = " ".join(toks)
    phrases_hit = sum(1 for p in phrases
                      if p in joined or p in low)
    score = coverage * 2.2 + min(density, 6.0) * 0.22 \
        + min(phrases_hit, 3) * 0.5 + (0.4 if early else 0.0)
    if len(body) < 140:
        score *= 0.7
    hits_sorted = sorted(hits, key=lambda s: -tf[s])[:4]
    why = "matches: " + ", ".join(hits_sorted)
    if phrases_hit:
        why += f" +{phrases_hit} phrase"
    return round(score, 3), why


def rank_record(payload: dict, question: str, length: str = "standard") -> dict:
    """Rank every page/paragraph of a curation sidecar payload.
    Returns a lite structure for the pane + the model shortlist."""
    qstems, phrases = _query_terms(question)
    target = _KEEP_TARGET.get(length, _KEEP_TARGET["standard"])
    pages_out = []
    ranked: list[tuple[float, str, str]] = []   # (score, pid, why)
    for page in payload.get("pages") or []:
        paras = page.get("paragraphs") or []
        pout = []
        page_best = 0.0
        for i, para in enumerate(paras):
            pid = f"{page.get('id', 'pg')}#p{i}"
            text = para.get("t") or para.get("text") or ""
            raw = para if isinstance(para, str) else (para.get("raw") or "")
            s, why = score_paragraph(text or raw[:4000], qstems, phrases,
                                     i < 3)
            body = (text or raw[:4000])
            shown = " ".join(body.split())[:700]
            pout.append({"pid": pid, "score": s, "why": why, "text": shown})
            page_best = max(page_best, s)
            if s > 0:
                ranked.append((s, pid, why))
        paras_kept = sum(1 for p in pout if p["score"] >= 0.6)
        pages_out.append({"id": page.get("id", ""),
                          "url": (page.get("url") or "")[:200],
                          "title": (page.get("title") or "")[:120],
                          "tier": page.get("tier") or "",
                          "score": round(page_best, 3),
                          "n": len(paras),
                          "keeps": paras_kept,
                          "paras": pout})
    ranked.sort(reverse=True)
    # suggested keep-set: top target, at most 4 per page, floor 0.6
    suggested, per_page = [], Counter()
    for s, pid, _ in ranked:
        if s < 0.6:
            break
        grp = pid.split("#", 1)[0]
        if per_page[grp] >= 4:
            continue
        suggested.append(pid)
        per_page[grp] += 1
        if len(suggested) >= target:
            break
    # model shortlist: the competitive slice the local LLM may re-judge
    shortlist = [{"pid": p, "score": s, "why": w}
                 for s, p, w in ranked[:32]]
    return {"engine": "heuristic", "question": question,
            "pages": pages_out, "suggested": suggested,
            "keep_target": target, "model_shortlist": shortlist}
