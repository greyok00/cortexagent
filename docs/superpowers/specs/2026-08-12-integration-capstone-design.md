# CortexAgent — Step 5: Integration Capstone Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

Part of the SlimToken orchestration layer (see
`2026-08-12-slimtoken-orchestration-design.md`). This spec designs **step 5**,
the capstone: real ingestion jobs, end-to-end integration, and the overseer
model question. Steps 1–4 built the pieces; step 5 proves they work together
and hardens them.

---

## 1. Goal

After steps 1–4, the pieces exist but haven't been proven as a system. Step 5:

1. **Ingestion job library** — real per-domain scripts that pull actual
   sources into the domain DBs (the "scripts to handle all of that processing
   of data from the domains").
2. **End-to-end integration** — the full pipeline verified: user prompt →
   ReAct loop → tools (adapters, rag_query, web_search) → answer, with domain
   knowledge retrieved and cited.
3. **Overseer model evaluation** — is LFM2.5-1.2B strong enough to drive
   ReAct + Socratic reasoning? Evaluate candidates and swap if needed.
4. **Tuning** — RRF weights, chunk sizes, tool schemas, loop parameters.

---

## 2. What's already built (steps 1–4 recap)

| Step | Built | Status |
|---|---|---|
| 1 | Tool registry + `rag_query` (CortexLLM half) | spec `2026-08-12-slimtoken-orchestration-design.md` |
| 2 | ReAct/Socratic loop | spec `2026-08-12-react-loop-design.md` |
| 3 | Domain DBs (FTS5 + vec0) + ingestion | spec `2026-08-12-domain-db-design.md` |
| 4 | Adapters (Moondream, faster-whisper, Docling/pdftotext) | spec `2026-08-12-adapters-design.md` |

Step 5 adds no new subsystems — it integrates, hardens, and tunes.

---

## 3. Ingestion job library

Real per-domain ingestion scripts in `scripts/`, wired to the existing cron
scheduler (task type `ingest`, from step 3):

| Script | Domain | Source type | Cadence (suggested) |
|---|---|---|---|
| `ingest_osint.py` | osint | OSINT portal exports, case files, saved reports | daily |
| `ingest_dfir.py` | dfir | forensic notes, IOC lists, incident reports | daily |
| `ingest_business.py` | business | contracts, meeting notes, financial docs | weekly |
| `ingest_law.py` | law | case law notes, statutes, legal memos | weekly |
| `ingest_programming.py` | programming | code docs, API references, project notes | on-change |

Each script: pull source → `domain_ingest.ingest(domain, source, text)` →
chunk → embed → store. Idempotent (content-hash dedup from step 3) so
re-runs are safe.

**Source discovery:** scripts read a per-domain manifest
(`~/.cortexagent/domains/<domain>.sources.json`) listing file paths / URLs /
export locations. The overseer model can also add sources at runtime via the
`ingest_domain` tool (step 3).

---

## 4. End-to-end integration

The full pipeline, verified as one flow:

```
user prompt → queue → run_react (step 2)
   → classify intent → mode (react | socratic)
   → loop: query_with_tools → execute_tool
        ├── rag_query(domain, q)      → CortexLLM + domain DB (steps 1+3)
        ├── web_search(q)             → firecrawl/brave
        ├── describe_image(img)       → Moondream (step 4)
        ├── transcribe_audio(file)    → faster-whisper (step 4)
        ├── parse_document(file)      → Docling/pdftotext (step 4)
        └── ingest_domain(...)        → store knowledge (step 3)
   → final answer → post_response_verifier → user
```

**Integration test scenarios:**

| Scenario | Proves |
|---|---|
| "Summarize the OSINT case files" | rag_query domain-DB search + loop synthesis |
| "What did we decide about X in business?" | rag_query CortexLLM memory + domain DB merge |
| "Transcribe this interview and file it under osint" | transcribe_audio → ingest_domain → search finds it |
| "Parse this contract and extract the key terms" | parse_document → rag_query business |
| Ambiguous prompt → Socratic clarification | mode selection + no premature tool calls |

---

## 5. Overseer model evaluation

**The risk:** LFM2.5-1.2B driving ReAct + Socratic reasoning is the weakest
link. The changelog already lists candidates (research pending):

| Candidate | Size | Why |
|---|---|---|
| LFM2.5-1.2B (current) | 728 MB | Baseline — tool-call native, works |
| Qwen2.5-1.5B-Instruct | ~1.5 GB | Better instruction following |
| Qwen2.5-Coder-1.5B | ~1.5 GB | Coding-tuned (loop writes code) |
| llama-3.2-3B-Instruct | ~2 GB | Strong tool use |
| Hermes-3-2B / Functionary-small | ~2 GB | Tool-call specialists |

**Evaluation method (step 5):** run the step-2 loop's smoke scenarios against
each candidate on :8082, score on: tool-call correctness (valid JSON, right
tool), Socratic quality (does it surface assumptions + falsification), and
loop convergence (finishes within max_steps). Swap the winner into
`cortexagent.conf` (`overseer_model`).

**Constraint:** stays ≤2 GB (two-models-only rule). The swap is a config
change + model file, not a code change — the loop talks to :8082 regardless
of which model serves it.

---

## 6. Tuning

| Knob | Where | Tune |
|---|---|---|
| RRF `k` | `lib/domain_db.py` | 60 default; tune on real queries |
| Chunk size / overlap | `lib/domain_ingest.py` | 500/50 default; tune per domain |
| `max_steps` | `lib/react_loop.py` | 8 default; raise for investigative tasks |
| Tool schema descriptions | `lib/tool_registry.py` | Sharpen so the model picks the right tool |
| Socratic keyword list | `lib/react_loop.py` | Extend with real investigative terms |
| `rag_query` result limit | `lib/tool_registry.py` | 10 default; tune per domain |

Tuning is data-driven: log loop traces (prompt, mode, tool calls, steps,
outcome) to CortexLLM and review.

---

## 7. Error handling

| Failure | Behavior |
|---|---|
| Ingestion script fails mid-pull | Idempotent re-run (dedup); log + alert via health events |
| Domain DB corrupt | `_check_db_integrity` (existing) flags it; rebuild from sources |
| Loop doesn't converge | max_steps partial answer + note (step 2) |
| Overseer model swap breaks tool calls | Roll back to previous model in config; smoke gate catches it |
| Adapter OOM | Lazy singleton unloads; next call retries (step 4) |

---

## 8. Testing

| Test | What it proves |
|---|---|
| Ingestion job library | Each `scripts/ingest_*.py` pulls a sample source → DB populated |
| End-to-end scenarios (§4) | Full pipeline works with real tools + domain knowledge |
| Overseer model eval | Candidates scored; winner swapped; smoke gate green |
| Tuning regression | RRF/chunk/step changes don't break existing smoke |
| Full smoke gate | `cortexagent doctor` + `tests/run_smoke.py` — all steps' checks green |

---

## 9. Files

| File | Change |
|---|---|
| `scripts/ingest_{osint,dfir,business,law,programming}.py` | NEW — ingestion job library |
| `~/.cortexagent/domains/<domain>.sources.json` | NEW — per-domain source manifests |
| `lib/react_loop.py` | TUNE — max_steps, socratic keywords |
| `lib/domain_db.py` / `lib/domain_ingest.py` | TUNE — RRF k, chunk size |
| `lib/tool_registry.py` | TUNE — tool descriptions, rag_query limit |
| `cortexagent.conf` | MAYBE — `overseer_model` swap |
| `tests/run_smoke.py` | ADD end-to-end + eval checks |
| `docs/superpowers/specs/2026-08-10-daily-changelog.md` | ADD row |

---

## 10. Out of scope (Phase 2)

- Android accessibility (accessibility-tree agents, ADB).
- Phone overseer (dense 2–3B on S24 FE).
- Model distillation (train a custom overseer from logged trajectories).
- Florence-2 structured grounding.
- Docling full install (optional upgrade, not required).

---

## 11. Tracking

- This file = `docs/superpowers/specs/2026-08-12-integration-capstone-design.md`
- Master spec = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
