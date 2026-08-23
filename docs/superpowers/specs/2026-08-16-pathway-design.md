# Pathway — Full Request-Chain Visualization (Design)

**Date:** 2026-08-16
**Status:** Approved (design) → pending implementation plan
**Scope:** Capture + feed only. The visual strip renders on the expanded overseer dashboard (delegated to a separate session).

## Overview

The **pathway** is the entire CortexAgent request chain — every stage a prompt passes through
from input to final output — captured as a per-run, grouped event stream that a viewer (the
expanded overseer dashboard) renders as a clickable node strip. It makes the "entire thinking
process" visible at a broad scale: ~6 groups → ~12 fine nodes, never every micro-step.

The chain being traced:

```
prompt → frame-of-reference → minify (slimtoken) → domain-db check → overseer routing
       → big-model generation → beautify → output
```

## Deliverable split

| Session | Responsibility |
|---------|----------------|
| **This session (cortexagent)** | `lib/pathway.py` capture layer (NDJSON store, `PathwayRun`, `recent_prompts()`), instrument **frame / domain / beautify** stages, always-run domain-db check |
| **Overseer-dashboard session** | render the 10–12-node strip; emit **minify / route / generate** stages to the same stream from `overseer.py` + `grammar_proxy.py` |
| **CortexLLM** | hot-memory buffer is the read source for the "load last prompt" dropdown |

Constraints honored:
- **Do not touch** `lib/overseer.py`, `lib/tray_dashboard.py`, `lib/overseer_dashboard/*`, or the dashboard-redesign session's active files.
- Localhost-only; no PII in committed files; NDJSON idiom matches `memory_thin` / `scheduler/store.py`.

## Stage taxonomy — 6 groups → 12 nodes

| Group | Nodes | Records |
|-------|-------|---------|
| `frame` | classify · optimize · frame | domain, optimized prompt, system framing added |
| `minify` | request · budget | slimtoken tokens_in/out, budget, savings % |
| `domain` | search · memory | FTS5+vec0 hits, CortexLLM hot/cold hits |
| `route` | react · tool | mode classification, tool dispatched |
| `generate` | build · stream | big-model prompt build, tokens streamed |
| `beautify` | minify · beautify | response minify + beautify applied |

Each node is clickable/holdable, showing **entered → transformed → exited** (+ duration, tokens).

## Event schema

One JSON line per stage, appended to `~/.cortexagent/pathway/<run_id>.jsonl`.

```json
{"run_id":"20260816-140512-8f3a2c91","seq":3,"group":"domain","stage":"search",
 "status":"ok","entered":{"query":"...","domain":"osint"},
 "transformed":{"hits":3,"top_source":"case1.txt"},"exited":{"context_len":412},
 "dur_ms":18.4,"tokens_in":0,"tokens_out":0,"ts":"2026-08-16T14:05:12.031Z"}
```

Fields:
- `run_id` — `YYYYMMDD-HHMMSS-<prompt_hash8>`; all stages of one request share it.
- `seq` — zero-based stage order within the run.
- `group` / `stage` — from the taxonomy above.
- `status` — `ok` | `error` | `skipped`.
- `entered` — what the stage received (may include `prompt`, `query`, `domain`, `system_len`).
- `transformed` — what the stage computed/changed (hits, tokens, savings).
- `exited` — what it produced (context_len, output preview length).
- `dur_ms` — stage wall time.
- `tokens_in` / `tokens_out` — token deltas when known (0 if not).
- `ts` — ISO timestamp.

## `lib/pathway.py` API

- `PathwayRun(prompt)` — context manager. Generates `run_id`; `.emit(group, stage, **fields)` appends one event line.
- `list_runs(n=20)` — recent run_ids + first-prompt previews (for a picker).
- `read_run(run_id)` — the run's ordered stage list; **tolerates malformed/partial lines** (a crashed run never blocks reading).
- `recent_prompts(n=20)` — **dropdown source**: `memory_thin.read_last(n)` filtered to `role=="user"`; returns `[{prompt, ts, run_id}]`.
- `check_domain(domain, query)` — the **always-run domain-db check**: runs `domain_db.search()` + CortexLLM hot/cold, emits `domain.*` events, returns the hit-payload for context.

## Always-run domain-db check

`check_domain(domain, query)` runs on **every** request at the frame→minify boundary, so the
domain stage is always present in the pathway. It queries the matching domain DB (FTS5 + vec0
hybrid via `lib/domain_db.search`) plus CortexLLM hot/cold memory, records hits as `domain.*`
events, and returns the hit-payload the pipeline can merge into context. Actual injection into
the big-model prompt is the overseer's merge step (coordinated with the other session).

Failure is non-fatal: if `domain_db` or memory is unavailable, the stage emits `status:"skipped"` and the request proceeds.

## Storage & rotation

- Path: `~/.cortexagent/pathway/<run_id>.jsonl` (auto-created).
- Rotation: cap the directory at **200 files**, deleting oldest on write.
- Idiom: atomic O_APPEND, same as `memory_thin`.

## Error handling

- Every `emit` is wrapped so a pathway failure **never breaks a request** (try/except + no-op).
- Missing dir auto-created; partial/corrupt run files skipped on read.
- `run_id` collisions avoided via timestamp + prompt hash.

## Verification

`lib/pathway.py --smoke` asserts:
1. A synthetic run emits exactly 12 stage events across 6 groups.
2. Rotation: >200 files → oldest deleted.
3. `recent_prompts()` returns only `role=="user"` hot-memory entries.
4. Malformed JSONL lines are tolerated (reader skips them).
5. `emit` failure is non-fatal (a raised stage does not propagate).
6. `domain_db.search` hits flow into `domain.search` events via `check_domain`.

## Files

| File | Change |
|------|--------|
| `lib/pathway.py` | **new** — capture layer, `PathwayRun`, `check_domain`, `recent_prompts`, rotation |
| `lib/prompt_framing.py` | emit `frame.*` events |
| `lib/beautify.py` | emit `beautify.*` events |
| `lib/domain_db.py` / `lib/tool_registry.py` | emit `domain.*` events from the rag/search path |
| `docs/superpowers/specs/2026-08-16-pathway-design.md` | this spec |

The **minify / route / generate** stages and the **dashboard rendering** are the other session's scope (see relay prompt). This session does not touch those files.
