#!/usr/bin/env python3
"""scripts/intent_bridge.py — classify a prompt for the cortex CLI's model auto-switch.

The cortex CLI's models extension calls this before each agent turn to decide
whether the tiny (:8082) or big (:8080) model should handle the prompt.
Reuses the proven pre_flight_gate intent classifier.

  python3 scripts/intent_bridge.py "hello there"
  → {"ok": true, "intent": "conversation", "tier": "tiny"}

Tier mapping: conversation/memory/scheduling/task-management → tiny (fast);
everything else (command, file, retrieval, verification, ambiguous) → big.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TINY_INTENTS = {"conversation", "memory_operation", "scheduling", "task_management"}


def classify(prompt: str) -> dict:
    from lib.pre_flight_gate import classify_intent
    intent = classify_intent(prompt)
    tier = "tiny" if intent in _TINY_INTENTS else "big"
    return {"ok": True, "intent": intent, "tier": tier}


def _smoke() -> int:
    fails = 0
    for prompt, want in (("hello there", "tiny"), ("run echo hello", "big"),
                         ("investigate the osint case", "big")):
        r = classify(prompt)
        if r["tier"] != want:
            print(f"❌ {prompt!r}: got {r['tier']}, want {want}")
            fails += 1
        else:
            print(f"✅ {prompt!r} → {r['tier']} ({r['intent']})")
    print("intent_bridge smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] == "--smoke":
        return _smoke()
    prompt = " ".join(argv)
    print(json.dumps(classify(prompt), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
