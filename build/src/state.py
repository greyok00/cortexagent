"""core.state — session mode classification (thin, deterministic).

classify_mode(prompt) -> "direct" | "react":
  direct: plain prose questions with no tool signal (single model call);
  react: anything that smells like tool work (imperative verbs, paths,
  package commands, shell syntax). Loop.run uses it to route.

Created 2026-11-11: loop.py imported this module forever without a
definition anywhere; the greyagent twin's test_smoke pins the contract
("run nmap -p- 10.0.0.1" -> react, "hello there" -> direct).
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\b(?:run|exec|install|start|stop|restart|kill|chmod|chown|scp|ssh|curl|wget|pip|apt|dnf|systemctl|service)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:nmap|netstat|docker|kubectl|git|make|gcc|python3?|node|npm|gradle|adb|javac)\b",
               re.IGNORECASE),
    re.compile(r"(?:^|\s)(?:[/~][\w./-]+)"),          # unix paths
    re.compile(r"(?:^|\s)[\w.-]+\.(?:py|sh|js|ts|json|txt|md|log|deb|rpm)\b"),
    re.compile(r"[|;&`$><]"),                          # shell syntax
    re.compile(r"\b(?:file|files|search|find|grep|list|read|write|edit|browser|memory|scheduler|chart|parse|document|pdf)s?\b",
               re.IGNORECASE),
]

# Imperative-mood openers: a sentence beginning with a bare verb routes
# through the tool loop even when no tool noun appears ("say something" ->
# react: a chat turn may still emit calls; loop returns its text as output).
# Greetings/small talk ("hello there") stay direct (plain single-call).
_VERB_OPENERS = re.compile(
    r"^(?:please\s+)?(?:say|tell|write|make|give|show|open|close|summarize|"
    r"explain|check|test|build|create|generate|draft|send|update|fix|list|"
    r"read|add|remove|move|copy|compare|run|try|use|do)\b",
    re.IGNORECASE)


def classify_mode(prompt: str) -> str:
    p = (prompt or "").strip()
    if not p:
        return "direct"
    for pat in _PATTERNS:
        if pat.search(p):
            return "react"
    if _VERB_OPENERS.match(p):
        return "react"
    return "direct"
