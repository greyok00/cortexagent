#!/usr/bin/env python3
"""lib/prompt_schema.py — structured extraction from prompts (no-loss).

A deterministic, pure-CPU schema extractor over a natural-language prompt. It
pulls a stable set of typed fields out of the rambling text, then ALWAYS keeps
the ``original`` alongside — the schema is additive, so nothing the user said
is ever dropped. This is the "full schema with no-loss guard" the user chose.

Primitives come from the canonical slim reframing engine via
``lib/prompt_framing`` (the pure-slim shim). All extraction is local regex /
heuristics — no LLM roundtrip, matching the pure-slim decision.

Schema keys:
  original         the untouched source (the no-loss guard)
  reframed         slim's cleaned, deduped version (not shrunk — keeps meaning)
  domain           business | professional | osint | cybersecurity | code | general
  intent           the primary goal — the cleanest imperative sentence
  actions          imperative verb phrases (what the user wants done)
  constraints      clauses with limiters (only/must/never/unless/...)
  entities         proper nouns, file paths, URLs, hostnames, tool names
  inputs           quoted values / explicit numbers / named parameters
  outputs        requested result format (table/code/report/json/...)
  references       files, URLs, #issue/branch refs the prompt points at
  memory_hint      yes|no|maybe — does it need prior context? (text heuristic)

Usage:
    from lib.prompt_schema import schema_prompt
    s = schema_prompt("can you basically... audit the server, only touch prod, table")
    print(s["intent"], s["constraints"])
"""
from __future__ import annotations

import re
from typing import Dict, List

from lib.prompt_framing import classify_domain, reframe_prompt

# ── Constraint markers ──────────────────────────────────────────────────────
_CONSTRAINT_RE = re.compile(
    r"\b(only|must|mustn't|must not|never|do not|don't|without|unless|"
    r"avoid|limit|max(?:imum)?|min(?:imum)?|at least|at most|keep|ensure|"
    r"require|require(s|d)?|exactly|specifically|preserve|no more than|"
    r"under|within|excluding|except)\b",
    re.IGNORECASE)

# ── Action verbs (imperative heads) ─────────────────────────────────────────
_ACTION_VERBS = {
    "audit", "analyze", "build", "write", "create", "make", "fix", "debug",
    "refactor", "review", "check", "scan", "test", "install", "configure",
    "investigate", "search", "find", "compare", "summarize", "explain",
    "remove", "delete", "update", "change", "convert", "translate", "list",
    "generate", "add", "show", "report", "implement", "deploy", "optimize",
}

# ── Entity / reference patterns ─────────────────────────────────────────────
_ENT_FILE = re.compile(r"(?<![\w/])(?:/[A-Za-z0-9._-]+){1,}|(?<![A-Za-z])[A-Za-z]:[/\\][\w.\-/\\]+")
_ENT_URL = re.compile(r"https?://[^\s\"'<>()]+")
_ENT_CAP = re.compile(r"\b[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,2}\b")
_REF_ISSUE = re.compile(r"(?<!\w)#[0-9]+|\b(?:fix|feat|feature|refactor|bug|hotfix)/[\w-]+")

_OUTPUT_WORDS = {"table", "list", "code", "script", "report", "summary",
                 "json", "markdown", "diagram", "chart", "graph", "csv",
                 "steps", "checklist", "outline", "one-liner"}
_OUTPUT_HINT = re.compile(
    r"\b(?:as|as a|in|using|format as|give me|output as)?\s*"
    r"(table|list|code|script|report|summary|json|markdown|diagram|chart|"
    r"graph|csv|steps|checklist|outline|one-liner)\b",
    re.IGNORECASE)

_QUOTED = re.compile(r"[\"']([^\"']{2,80})[\"']")
_NUMBER = re.compile(r"\b\d{2,}\b(?:%|[KMB]?)?")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOST = re.compile(r"\b[\w-]+\.(?:com|net|org|io|dev|app|local|internal)(?:\.[a-z]{2})?")


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in parts if s.strip()]


_FILLER_PREFIX = re.compile(
    r"^(?:please|can you|could you|i need you to|i need|i'd like|i want|"
    r"i would like|you should|you can|help me|would you|do you think|"
    r"basically|so|ok[ay,]?\s+)?\s*", re.IGNORECASE)
_CLAUSE_LEAD = re.compile(r"^(?:only|just|also|then|and|to|if)\s+",
                          re.IGNORECASE)


def _strip_filler(s: str) -> str:
    """Repeatedly strip leading conversational filler so stacked fillers like
    'can you basically' fully collapse to the verb."""
    prev = None
    while prev != s:
        prev = s
        s = _FILLER_PREFIX.sub("", s).lstrip("(, ")
    return s


def _imperative_actions(prompt: str) -> List[str]:
    """Split into sentences AND comma clauses, then strip conversational filler
    and keep clauses whose head is an action verb."""
    out = []
    parts = re.split(r"(?<=[.!?])\s+|\n+|,\s+", prompt)
    for p in parts:
        c = _strip_filler(p)
        c = _CLAUSE_LEAD.sub("", c)
        head = c.lower()
        if not head:
            continue
        for v in sorted(_ACTION_VERBS, key=len, reverse=True):
            if head == v or head.startswith(v + " ") \
               or head.startswith(v + " the") or head.startswith(v + " a "):
                if c not in out:
                    out.append(c)
                break
    return out[:8]


def _extract_entities(prompt: str) -> List[str]:
    found = set()
    for m in _ENT_URL.finditer(prompt):
        found.add(m.group(0))
    for m in _IP.finditer(prompt):
        found.add(m.group(0))
    for m in _ENT_FILE.finditer(prompt):
        found.add(m.group(0))
    for m in _HOST.finditer(prompt):
        found.add(m.group(0))
    # proper-noun runs that aren't sentence-initial filler or bare verbs
    for m in _ENT_CAP.finditer(prompt):
        g = m.group(0).strip()
        words = g.split()
        if len(words) > 3 or g.lower() in _STOP_CAPS:
            continue
        if len(words) == 1 and words[0].lower() in _ACTION_VERBS:
            continue
        found.add(g)
    return sorted(found, key=len, reverse=True)[:8]


_STOP_CAPS = {
    "The", "This", "These", "Those", "It", "You", "I", "We", "They",
    "Please", "Also", "Then", "First", "Next", "Finally", "However",
    "There", "Here", "Because", "But", "For", "If", "As", "In", "On",
}


def extract(prompt: str) -> Dict[str, object]:
    """Extract the structured schema dict from a prompt. Always includes
    ``original`` (the no-loss guard) and ``reframed``."""
    prompt = prompt.strip()
    if not prompt:
        return {
            "original": "", "reframed": "", "domain": "general",
            "intent": "", "actions": [], "constraints": [],
            "entities": [], "inputs": [], "outputs": [], "references": [],
            "memory_hint": "no",
        }

    domain = classify_domain(prompt)
    reframed = reframe_prompt(prompt)

    # intent = the first clean sentence that carries an action
    sents = _sentences(reframed)
    intent = sents[0] if sents else reframed

    actions = _imperative_actions(prompt)

    constraints = [s for s in sents if _CONSTRAINT_RE.search(s)][:4]

    entities = _extract_entities(prompt)

    inputs = []
    for q in _QUOTED.finditer(prompt):
        inputs.append(q.group(1))
    inputs += [m.group(0) for m in _NUMBER.finditer(prompt) if m.group(0).isdigit()][:6]

    outputs = []
    for m in _OUTPUT_HINT.finditer(prompt):
        w = m.group(0).lower()
        for o in _OUTPUT_WORDS:
            if o in w:
                outputs.append(o)
    outputs = list(dict.fromkeys(outputs))[:4]

    references = []
    refs = []
    refs += [m.group(0) for m in _ENT_FILE.finditer(prompt)]
    refs += [m.group(0) for m in _ENT_URL.finditer(prompt)]
    refs += [m.group(0) for m in _REF_ISSUE.finditer(prompt)]
    for r in refs:
        if r not in references:
            references.append(r)
    references = references[:6]

    memory_hint = _memory_hint(prompt)

    return {
        "original": prompt,
        "reframed": reframed,
        "domain": domain,
        "intent": intent,
        "actions": actions,
        "constraints": constraints,
        "entities": entities,
        "inputs": inputs,
        "outputs": outputs,
        "references": references,
        "memory_hint": memory_hint,
    }


def _memory_hint(prompt: str) -> str:
    low = prompt.lower()
    cont = ("as we discussed", "we discussed", "as i said", "continue",
            "previous", "earlier", "from before", "you told me",
            "you just said", "earlier you")
    if any(k in low for k in cont):
        return "yes"
    if any(k in low for k in ("maybe", "context", "recall", "remember")):
        return "maybe"
    return "no"


def schema_prompt(prompt: str) -> Dict[str, object]:
    """Full wrapper: extract the schema AND keep the no-loss original. This is
    the intended entry point for wiring into the pipeline."""
    return extract(prompt)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> int:
    import sys, json
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not prompt:
        prompt = ("can you basically audit the server and check for iocs, "
                  "only keep the last 30 days of logs, give me a table")
    print(json.dumps(extract(prompt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
