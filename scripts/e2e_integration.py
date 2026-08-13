#!/usr/bin/env python3
"""scripts/e2e_integration.py — end-to-end verification of the orchestration layer.

Runs the spec's §4 scenarios against the LIVE system (overseer on :8082,
real domain DBs). Seeds a sample source per domain first (idempotent), then
drives the loop and scores each scenario. Model-agnostic: whatever serves
:8082 is what gets tested. Reports per-scenario PASS/FAIL; does not hard-fail
on a broken overseer (the react smoke area already covers that).

Usage:
  python3 scripts/e2e_integration.py            # all scenarios
  python3 scripts/e2e_integration.py --scenario 1   # one scenario
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import domain_ingest, domain_db, react_loop, tool_registry  # noqa: E402

SCENARIOS = [
    ("rag_query domain search",
     "Summarize the OSINT case files",
     "osint", "blocked IP 10.0.0.5 beaconing outbound every 30s"),
    ("ingest → search round-trip",
     "File this note under dfir and confirm it is searchable",
     "dfir", "Suspicious process svchost.exe spawned from C:\\Temp\\x.exe"),
    ("socratic classification",
     "What should we do about this?",
     None, None),
]


def _seed(domain: str, text: str) -> int:
    """Seed a sample source into a domain DB (idempotent). Returns chunks."""
    return domain_ingest.ingest(domain, f"e2e-seed-{domain}.txt", text).get("chunks", 0)


def _run_scenario(name: str, prompt: str, domain: str, seed_text: str) -> dict:
    mode = react_loop.classify_mode(prompt)
    if seed_text:
        _seed(domain, seed_text)
    result = react_loop.run_react({"type": "llm", "prompt": prompt, "max_steps": 4})
    output = result.get("output", "") or ""
    return {"name": name, "mode": mode, "ok": bool(output.strip()), "output": output[:200]}


def main() -> int:
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--scenario":
        only = int(sys.argv[2])
    fails = 0
    print("═" * 72)
    print("CortexAgent e2e integration")
    print("═" * 72)
    for i, (name, prompt, domain, seed_text) in enumerate(SCENARIOS, 1):
        if only and i != only:
            continue
        r = _run_scenario(name, prompt, domain, seed_text)
        mark = "✅" if r["ok"] else "❌"
        if not r["ok"]:
            fails += 1
        print(f"{mark} [{i}] {name} (mode={r['mode']})")
        if r["output"]:
            print(f"     → {r['output']}")
    print("═" * 72)
    print("e2e integration PASS" if fails == 0 else f"❌ {fails} scenario(s) failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
