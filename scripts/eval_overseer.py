#!/usr/bin/env python3
"""scripts/eval_overseer.py — score the overseer model on :8082.

Runs the step-2 loop's smoke scenarios against whatever model serves :8082
and scores three dimensions (spec §5):
  1. tool-call correctness — valid JSON, right tool, right args
  2. Socratic quality — surfaces assumptions + falsification, no premature tools
  3. loop convergence — finishes within max_steps with a non-empty answer

Model-agnostic: the STT session owns the model swap; this script just
measures. Prints a score table and exits 0 (a low score is data, not a
failure — the swap decision is coordinated separately).

Usage:
  python3 scripts/eval_overseer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import tiny_llm, tool_registry, react_loop  # noqa: E402

TOOL_PROMPT = "What is the current time? Use the run_command tool to check."
SOCRATIC_PROMPT = "We got a strange alert. What should we investigate?"
LOOP_PROMPT = "Run the command echo hello and report the output."


def _score_tool_calls() -> dict:
    """Valid tool_calls JSON with the right tool? 0-2 points."""
    try:
        resp = tiny_llm.query_with_tools(
            [{"role": "user", "content": TOOL_PROMPT}],
            tool_registry.list_tools(), max_tokens=512, timeout=60)
    except Exception as e:
        return {"score": 0, "detail": f"EXC {e.__class__.__name__}: {e}"}
    if not resp:
        return {"score": 0, "detail": "no response"}
    if resp.get("kind") != "tool_calls":
        return {"score": 0, "detail": f"kind={resp.get('kind')}"}
    calls = resp.get("calls", [])
    if not calls:
        return {"score": 0, "detail": "empty calls"}
    names = [c.get("name", "") for c in calls]
    if "run_command" in names:
        return {"score": 2, "detail": f"calls={names}"}
    return {"score": 1, "detail": f"calls={names} (wrong tool)"}


def _score_socratic() -> dict:
    """Surfaces assumptions/falsification without calling tools? 0-2 points."""
    try:
        resp = tiny_llm.query_with_tools(
            [{"role": "user", "content": SOCRATIC_PROMPT}],
            tool_registry.list_tools(), max_tokens=512, timeout=60)
    except Exception as e:
        return {"score": 0, "detail": f"EXC {e.__class__.__name__}: {e}"}
    if not resp:
        return {"score": 0, "detail": "no response"}
    if resp.get("kind") == "tool_calls":
        return {"score": 0, "detail": "called tools prematurely"}
    content = (resp.get("content") or "").lower()
    if any(kw in content for kw in ("assum", "falsif", "hypoth", "question")):
        return {"score": 2, "detail": "surfaces assumptions"}
    return {"score": 1, "detail": "text but no assumptions surfaced"}


def _score_convergence() -> dict:
    """Loop finishes within max_steps with non-empty output? 0-2 points."""
    try:
        result = react_loop.run_react(
            {"type": "llm", "prompt": LOOP_PROMPT, "max_steps": 4})
    except Exception as e:
        return {"score": 0, "detail": f"EXC {e.__class__.__name__}: {e}"}
    output = (result.get("output") or "").strip()
    if output:
        return {"score": 2, "detail": f"{len(output)} chars"}
    return {"score": 0, "detail": "empty output"}


def main() -> int:
    print("═" * 72)
    print("Overseer model evaluation (model on :8082)")
    print("═" * 72)
    rows = [
        ("tool-call correctness", _score_tool_calls()),
        ("socratic quality", _score_socratic()),
        ("loop convergence", _score_convergence()),
    ]
    total = 0
    for name, r in rows:
        total += r["score"]
        print(f"  {name}: {r['score']}/2 — {r['detail']}")
    print("═" * 72)
    print(f"TOTAL: {total}/6")
    print("  ≥5 strong · 3-4 usable · <3 swap candidate (coordinate with STT session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
