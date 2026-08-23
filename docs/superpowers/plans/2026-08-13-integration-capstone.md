# Step 5: Integration Capstone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the SlimToken orchestration layer works as a system: real per-domain ingestion jobs, an end-to-end integration harness, an overseer-model evaluation script, and data-driven tuning.

**Architecture:** No new subsystems — steps 1–4 built the pieces (tool registry, ReAct/Socratic loop, domain DBs + ingestion, adapters). Step 5 adds the job library (`scripts/ingest_*.py` over a shared helper), an e2e harness (`scripts/e2e_integration.py`), an overseer eval (`scripts/eval_overseer.py`), and tuning knobs — then proves it all with the smoke gate.

**Tech Stack:** Python 3 stdlib, SQLite (FTS5 + sqlite-vec), onnxruntime (all-MiniLM-L6-v2), llama.cpp on :8082 (overseer), existing `lib/` modules.

## Global Constraints

- **Coordination (HARD):** STT session owns `lib/stt.py`, `lib/stt_daemon.py`, `[stt]` in `lib/config.py` — READ/IMPORT ONLY, never edit. Shared files are APPEND-ONLY: `tests/run_smoke.py`, `docs/superpowers/specs/2026-08-10-daily-changelog.md`, `lib/webui.py`, `lib/tray.py`, `bin/cortexagent`. NEVER run `git checkout`/`git stash`/`git reset`/`git clean`/`git add -A`. Commit with explicit file lists only.
- **VRAM budget (HARD):** 512MB locked buffer (`vram_buffer_mb=512`). Big model + overseer + faster-whisper are required residents — never evicted. Adapters/RAG embedding use remaining free VRAM via `lib/vram.can_fit()`, else CPU.
- **Two-models-only rule:** big Qwen3.6-35B on :8080 + overseer ≤2GB on :8082. Nothing else in the 2–12GB range.
- **Overseer swap awareness:** the STT session is swapping the :8082 overseer (currently R1-Distill, known-broken tool calls). The eval script (Task 3) is model-agnostic — it talks to :8082 regardless of which model serves it. Do NOT touch the model swap itself; coordinate with the STT session.
- **Domain DBs:** `ALLOWED_DOMAINS = ("business", "dfir", "law", "osint", "programming")`. Chunk 200/50 (fits embedder's 256-token context). RRF k=60.
- **Smoke gate:** every task ends with its module `--smoke` green; the full `tests/run_smoke.py` gate must not regress (5 known pre-existing failures: static, pii, proxy, promptqueue + react-from-R1-Distill — do not "fix" those).

---

### Task 1: Ingestion job library — shared helper + 4 domain scripts

**Files:**
- Create: `scripts/ingest_common.py`
- Create: `scripts/ingest_dfir.py`, `scripts/ingest_business.py`, `scripts/ingest_law.py`, `scripts/ingest_programming.py`
- Modify: `scripts/ingest_osint.py` (refactor to use the shared helper — behavior unchanged)
- Modify: `tests/run_smoke.py` (append `ingest` area — APPEND-ONLY, add new test function + TESTS entry)

**Interfaces:**
- Consumes: `lib.domain_ingest.ingest(domain, source, text) -> {"ok", "chunks", "error"}` (content-hash dedup, idempotent); `lib.config.CFG.state_dir` (Path).
- Produces: `scripts.ingest_common.ingest_dir(domain, src_dir) -> int` (chunks stored); `scripts.ingest_common.source_dir(domain) -> Path`; each `scripts/ingest_<domain>.py` runs `ingest_dir(domain, source_dir(domain))` and exits 0.

- [ ] **Step 1: Create `scripts/ingest_common.py`**

```python
#!/usr/bin/env python3
"""scripts/ingest_common.py — shared helper for the per-domain ingestion jobs.

Each per-domain script (ingest_osint, ingest_dfir, ...) is a thin wrapper that
calls ingest_dir() on its source directory. Idempotent: domain_ingest dedups
by content hash, so re-runs are safe. Source files are read with
errors="replace" so a binary file never kills the job.

Usage:
  python3 scripts/ingest_common.py --smoke
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import domain_ingest, domain_db  # noqa: E402
from lib.config import CFG  # noqa: E402


def source_dir(domain: str) -> Path:
    """Per-domain source directory (~/.cortexagent/domains/sources/<domain>/)."""
    return CFG.state_dir / "domains" / "sources" / domain


def ingest_dir(domain: str, src_dir: Path) -> int:
    """Ingest every file under src_dir into `domain`. Returns chunks stored."""
    src_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in sorted(src_dir.iterdir()):
        if not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
            r = domain_ingest.ingest(domain, str(f), text)
            total += r.get("chunks", 0)
            print(f"  {f.name}: {r.get('chunks', 0)} chunks")
        except Exception as e:
            print(f"  {f.name}: ERROR {e}", file=sys.stderr)
    print(f"{domain} ingest done — {total} chunks stored")
    return total


def _smoke() -> int:
    fails = 0
    tmp = Path(tempfile.mkdtemp())
    old = domain_db.DOMAINS_DIR
    domain_db.DOMAINS_DIR = tmp
    try:
        src = tmp / "sources" / "dfir"
        src.mkdir(parents=True, exist_ok=True)
        (src / "report1.txt").write_text("IOC: attacker used IP 10.0.0.5. " * 30)
        n = ingest_dir("dfir", src)
        if n < 1:
            print(f"❌ ingest_dir stored {n} chunks")
            fails += 1
        hits = domain_db.search("dfir", "attacker IP")
        if not hits:
            print("❌ search after ingest_dir empty")
            fails += 1
        # Idempotent re-run: dedup means 0 new chunks.
        n2 = ingest_dir("dfir", src)
        if n2 != 0:
            print(f"❌ re-ingest not idempotent: {n2} chunks")
            fails += 1
        # Unknown domain must not crash the job.
        bad = tmp / "sources" / "nope"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "x.txt").write_text("text")
        ingest_dir("nope", bad)  # prints error, returns 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        domain_db.DOMAINS_DIR = old
    print("ingest_common smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 scripts/ingest_common.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the smoke to verify it passes**

Run: `python3 scripts/ingest_common.py --smoke`
Expected: `ingest_common smoke PASS`

- [ ] **Step 3: Create the 4 domain scripts** (identical shape, different domain)

`scripts/ingest_dfir.py`:
```python
#!/usr/bin/env python3
"""scripts/ingest_dfir.py — ingest DFIR source files into the dfir domain DB."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ingest_common import ingest_dir, source_dir  # noqa: E402


def main() -> int:
    ingest_dir("dfir", source_dir("dfir"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/ingest_business.py` — same, with `"business"` in both places.
`scripts/ingest_law.py` — same, with `"law"` in both places.
`scripts/ingest_programming.py` — same, with `"programming"` in both places.

- [ ] **Step 4: Refactor `scripts/ingest_osint.py` to use the shared helper**

Replace the whole file body (keep the docstring's first line) with:
```python
#!/usr/bin/env python3
"""scripts/ingest_osint.py — ingest OSINT source files into the osint domain DB."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ingest_common import ingest_dir, source_dir  # noqa: E402


def main() -> int:
    ingest_dir("osint", source_dir("osint"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Verify all 5 scripts run (empty source dirs are fine)**

Run: `for d in osint dfir business law programming; do python3 scripts/ingest_$d.py; done`
Expected: each prints `<domain> ingest done — 0 chunks stored` (or N if sources exist) and exits 0.

- [ ] **Step 6: Append the `ingest` area to `tests/run_smoke.py`** (APPEND-ONLY — add a new test function before the `# Registry` section, and add the TESTS entry)

```python
# AREA: ingest (step-5 ingestion job library)
# ═══════════════════════════════════════════════════════════════════════════
def test_ingest_job_library() -> R:
    """Ingestion jobs: shared helper ingests a dir, dedups, survives bad domains."""
    from scripts import ingest_common
    import tempfile, shutil
    from pathlib import Path
    from lib import domain_db
    tmp = Path(tempfile.mkdtemp())
    old = domain_db.DOMAINS_DIR
    domain_db.DOMAINS_DIR = tmp
    try:
        src = tmp / "sources" / "law"
        src.mkdir(parents=True, exist_ok=True)
        (src / "memo.txt").write_text("Statute 18 USC 1030: unauthorized access. " * 20)
        n = ingest_common.ingest_dir("law", src)
        if n < 1:
            return R("ingest job", "ingest", False, f"stored {n} chunks")
        hits = domain_db.search("law", "unauthorized access")
        if not hits:
            return R("ingest job search", "ingest", False, "no hits")
        n2 = ingest_common.ingest_dir("law", src)
        if n2 != 0:
            return R("ingest job dedup", "ingest", False, f"{n2} chunks on re-run")
        return R("ingest job library", "ingest", True, f"{n} chunks, {len(hits)} hits")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        domain_db.DOMAINS_DIR = old
```

Add to the `TESTS` dict: `"ingest": [test_ingest_job_library],`

- [ ] **Step 7: Run the new area**

Run: `python3 tests/run_smoke.py --area ingest`
Expected: `✅ [ingest] ingest job library — N chunks, M hits` and `✅ ALL PASS — 1 ran`

- [ ] **Step 8: Commit**

```bash
git add scripts/ingest_common.py scripts/ingest_dfir.py scripts/ingest_business.py scripts/ingest_law.py scripts/ingest_programming.py scripts/ingest_osint.py tests/run_smoke.py
git commit -m "feat(step5): ingestion job library — shared helper + 4 domain scripts

scripts/ingest_common.py: ingest_dir()/source_dir() over domain_ingest
(idempotent, content-hash dedup, errors=replace). ingest_osint refactored
to use it; dfir/business/law/programming added. Smoke + run_smoke 'ingest'
area green."
```

---

### Task 2: End-to-end integration harness

**Files:**
- Create: `scripts/e2e_integration.py`
- Modify: `tests/run_smoke.py` (append `integration` area — offline-testable parts only)

**Interfaces:**
- Consumes: `lib.react_loop.run_react(task, state) -> Dict` (task = `{"type": "llm", "prompt": str, "max_steps": int}`); `lib.react_loop.classify_mode(prompt) -> "direct"|"react"|"socratic"`; `lib.tool_registry.execute_tool(name, args)`; `lib.domain_ingest.ingest`; `lib.domain_db.search`.
- Produces: `scripts/e2e_integration.py` — live full-pipeline verification, prints a per-scenario PASS/FAIL table, exits 0 if all pass, 1 otherwise. The smoke `integration` area tests the offline parts (rag_query with seeded DB, ingest→search, socratic classification) without the live overseer.

- [ ] **Step 1: Create `scripts/e2e_integration.py`**

```python
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
```

- [ ] **Step 2: Verify the script runs (may report ❌ if the overseer is broken — that is expected and acceptable)**

Run: `python3 scripts/e2e_integration.py`
Expected: prints the scenario table. If the R1-Distill overseer is still broken, scenarios report ❌ with empty output — that is the harness working correctly, not a harness bug.

- [ ] **Step 3: Append the `integration` area to `tests/run_smoke.py`** (offline parts only — no live overseer)

```python
# AREA: integration (step-5 e2e — offline-testable parts)
# ═══════════════════════════════════════════════════════════════════════════
def test_integration_offline() -> R:
    """E2E offline parts: rag_query with seeded DB, ingest→search, socratic mode."""
    from lib import domain_ingest, domain_db, react_loop, tool_registry
    import tempfile, shutil
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    old = domain_db.DOMAINS_DIR
    domain_db.DOMAINS_DIR = tmp
    try:
        r = domain_ingest.ingest("osint", "e2e.txt", "blocked IP 10.0.0.5 beaconing " * 20)
        if not r.get("ok") or r.get("chunks", 0) < 1:
            return R("e2e seed", "integration", False, str(r))
        q = tool_registry.execute_tool("rag_query", {"domain": "osint", "query": "blocked IP"})
        if not q.get("ok") or "10.0.0.5" not in q.get("output", ""):
            return R("e2e rag_query", "integration", False, q.get("error", "no output"))
        ing = tool_registry.execute_tool("ingest_domain",
                                         {"domain": "dfir", "source": "n.txt",
                                          "text": "svchost.exe from C:\\Temp " * 20})
        if not ing.get("ok"):
            return R("e2e ingest_domain", "integration", False, str(ing))
        hits = domain_db.search("dfir", "svchost")
        if not hits:
            return R("e2e ingest→search", "integration", False, "no hits")
        if react_loop.classify_mode("What should we do about this?") != "socratic":
            return R("e2e socratic mode", "integration", False, "not socratic")
        return R("e2e integration offline", "integration", True, "rag+ingest+socratic")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        domain_db.DOMAINS_DIR = old
```

Add to the `TESTS` dict: `"integration": [test_integration_offline],`

- [ ] **Step 4: Run the new area**

Run: `python3 tests/run_smoke.py --area integration`
Expected: `✅ [integration] e2e integration offline — rag+ingest+socratic` and `✅ ALL PASS — 1 ran`

- [ ] **Step 5: Commit**

```bash
git add scripts/e2e_integration.py tests/run_smoke.py
git commit -m "feat(step5): e2e integration harness + offline smoke area

scripts/e2e_integration.py: live full-pipeline verification (seed → loop →
score) for the spec's §4 scenarios; model-agnostic, reports per-scenario
PASS/FAIL. run_smoke 'integration' area covers the offline parts (rag_query
with seeded DB, ingest→search round-trip, socratic classification)."
```

---

### Task 3: Overseer model evaluation script

**Files:**
- Create: `scripts/eval_overseer.py`

**Interfaces:**
- Consumes: `lib.tiny_llm.query_with_tools(messages, tools, max_tokens=512, timeout=60) -> {"kind": "tool_calls", "calls": [...]} | {"kind": "text", "content": str} | None`; `lib.tool_registry.list_tools()`; `lib.react_loop.run_react`.
- Produces: `scripts/eval_overseer.py` — scores whatever model serves :8082 on tool-call correctness, Socratic quality, and loop convergence; prints a score table; exits 0.

- [ ] **Step 1: Create `scripts/eval_overseer.py`**

```python
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
LOOP_PROMPT = "Summarize the OSINT case files."


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
```

- [ ] **Step 2: Run the eval**

Run: `python3 scripts/eval_overseer.py`
Expected: prints the score table. With the current broken R1-Distill overseer, expect a low score (0-1/6) — that is the eval working, and it feeds the coordinated swap decision.

- [ ] **Step 3: Commit**

```bash
git add scripts/eval_overseer.py
git commit -m "feat(step5): overseer model evaluation script

scripts/eval_overseer.py: scores the :8082 model on tool-call correctness,
socratic quality, and loop convergence (0-2 each, /6 total). Model-agnostic
— the STT session owns the swap; this measures whatever serves :8082."
```

---

### Task 4: Tuning — socratic keywords + regression checks

**Files:**
- Modify: `lib/react_loop.py` (extend `SOCRATIC_KEYWORDS` — append-only to the tuple)
- Modify: `tests/run_smoke.py` (append a tuning-regression check to the `react` area — APPEND-ONLY)

**Interfaces:**
- Consumes: `lib.react_loop.SOCRATIC_KEYWORDS` (tuple of substrings matched against the lowercased prompt in `classify_mode`).
- Produces: an extended keyword list covering real investigative terms; a regression check asserting the spec's tuning defaults (RRF k=60, max_steps=8, rag_query limit=10) hold.

- [ ] **Step 1: Extend `SOCRATIC_KEYWORDS` in `lib/react_loop.py`**

Find the tuple (currently ends with `"forensic", "dfir", "threat", "malware", "incident",`) and append these real investigative terms (keep the existing entries; add after the last one):

```python
    "intrusion", "exfiltration", "lateral movement", "phishing", "ransomware",
    "indicator of compromise", "ioc", "breach", "anomaly", "suspicious",
    "correlation", "timeline", "attribution", "false positive", "false negative",
```

- [ ] **Step 2: Verify classify_mode picks socratic for the new terms**

Run: `python3 -c "from lib.react_loop import classify_mode; print(classify_mode('check for lateral movement in the logs'))"`
Expected: `socratic`

- [ ] **Step 3: Append a tuning-regression check to the `react` area in `tests/run_smoke.py`**

```python
def test_tuning_defaults() -> R:
    """Tuning defaults hold: RRF k=60, max_steps=8, rag_query limit=10."""
    from lib import domain_db, react_loop, tool_registry
    if domain_db.RRF_K != 60:
        return R("tuning RRF k", "react", False, f"k={domain_db.RRF_K}")
    if react_loop.MAX_STEPS != 8:
        return R("tuning max_steps", "react", False, f"{react_loop.MAX_STEPS}")
    import inspect
    src = inspect.getsource(tool_registry._rag_query)
    if "limit: int = 10" not in src:
        return R("tuning rag_query limit", "react", False, "limit != 10")
    return R("tuning defaults", "react", True, "k=60, steps=8, limit=10")
```

Add `test_tuning_defaults` to the `"react"` list in the `TESTS` dict.

- [ ] **Step 4: Run the react area**

Run: `python3 tests/run_smoke.py --area react`
Expected: `✅ [react] tuning defaults — k=60, steps=8, limit=10`. The pre-existing `test_react_loop` failure (R1-Distill) may still fail — that is known and not this task's concern.

- [ ] **Step 5: Commit**

```bash
git add lib/react_loop.py tests/run_smoke.py
git commit -m "feat(step5): tuning — extended socratic keywords + defaults regression

SOCRATIC_KEYWORDS extended with real investigative terms (intrusion,
exfiltration, lateral movement, ioc, breach, anomaly, attribution, false
positive/negative). run_smoke react area asserts tuning defaults (RRF k=60,
max_steps=8, rag_query limit=10) hold."
```

---

### Task 5: Changelog + full smoke gate

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-daily-changelog.md` (APPEND-ONLY — add row 34 to the DONE table)
- Modify: `docs/superpowers/plans/2026-08-13-integration-capstone.md` (this file — mark tasks complete)

**Interfaces:**
- Consumes: the changelog's DONE table format (`| N | Aug 12 | **Title** — description | files | spec/user |`).

- [ ] **Step 1: Append changelog row 34**

Add to the top of the DONE table (after the header row, before row 32):

```markdown
| 34 | Aug 13 | **Step 5: integration capstone** — ingestion job library (`scripts/ingest_common.py` shared helper + `ingest_{dfir,business,law,programming}.py`, osint refactored), e2e harness (`scripts/e2e_integration.py`, live per-scenario scoring), overseer eval (`scripts/eval_overseer.py`, tool-call/socratic/convergence /6), tuning (socratic keywords extended, defaults regression) | `scripts/ingest_common.py`, `scripts/ingest_{dfir,business,law,programming}.py`, `scripts/ingest_osint.py`, `scripts/e2e_integration.py`, `scripts/eval_overseer.py`, `lib/react_loop.py`, `tests/run_smoke.py` | Spec: `2026-08-12-integration-capstone-design.md` |
```

- [ ] **Step 2: Run the full smoke gate**

Run: `python3 tests/run_smoke.py`
Expected: the 5 known pre-existing failures (static, pii, proxy, promptqueue, react-from-R1-Distill) plus any new failures from this plan's areas. The `ingest`, `integration`, and `tuning` checks must PASS. If a NEW failure appears in an area this plan touched, fix it before proceeding.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-08-10-daily-changelog.md
git commit -m "docs(step5): changelog row 34 — integration capstone"
```

- [ ] **Step 4: Mark this plan's tasks complete in the ledger** (`.superpowers/sdd/2026-08-13-integration-capstone/progress.md` — create it with the plan path as its first line, then append `Task N: complete` per task).

---

## Self-review notes

- **Spec coverage:** §3 (ingestion jobs) → Task 1; §4 (e2e) → Task 2; §5 (overseer eval) → Task 3; §6 (tuning) → Task 4; §8 (testing) → Tasks 1-5 smoke checks; changelog → Task 5. §7 (error handling) is already implemented in steps 1-4 (idempotent re-run, `_check_db_integrity`, max_steps partial answer, rollback via config, lazy-singleton unload).
- **Coordination:** no STT files touched; shared files only appended; explicit-file-list commits only.
- **Known risk:** Task 2's live e2e and Task 3's eval will score low while the R1-Distill overseer is broken — that is the harness working, and it feeds the STT session's coordinated swap decision. Do not "fix" the model; coordinate.
