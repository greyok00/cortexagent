#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

def classify(prompt: str) -> dict:
    from lib.pre_flight_gate import classify_intent
    intent = classify_intent(prompt)
    return {"ok": True, "intent": intent, "tier": "big"}


def _smoke() -> int:
    fails = 0
    for prompt, want in (("hello there", "big"), ("run echo hello", "big"),
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
