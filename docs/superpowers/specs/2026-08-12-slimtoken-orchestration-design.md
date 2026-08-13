# CortexAgent — SlimToken Orchestration Layer Design

**Owner:** grey · **Date:** 2026-08-12 · **Status:** 🟡 draft for review

The master build prompt describes SlimToken as a full orchestration layer:
prompt normalization, ReAct/Socratic routing, RAG tool calls, multimodal
adapters, and domain knowledge bases. This spec reconciles that vision with
what the codebase already is, and designs the build in 5 ordered steps.

---

## 1. Context — what already exists

The master prompt is the *original vision*. The codebase has already diverged
in pragmatic ways. Gap analysis (verified against the codebase, 2026-08-12):

| Master prompt asks | Status | Where |
|---|---|---|
| SlimToken compression | ✅ DONE | `lib/grammar_proxy.py` — slimtoken is the primary minify backend (request + response, R4) |
| Prompt normalization / self-refine | ⚠️ DROPPED by design | Ruled out Aug 10. What exists: `lib/pre_flight_gate.py` rule-based intent + ambiguity→clarify (R6) |
| ReAct + Socratic routing | ⚠️ PARTIAL | No standalone loop. Claude Code is the agent today. `pre_flight_gate` classifies intent only |
| RAG tool calls | ⚠️ PARTIAL | CortexLLM has BM25/vector/graph search, but no `rag_query(domain, query)` tool exposed |
| web_search tool | ⚠️ PARTIAL | `lib/firecrawl_proxy.py`, `lib/fast_extract.py` (brave_fetch) exist |
| describe_image adapter | ✅ N/A | Big model is multimodal natively — adapters dropped |
| transcribe_audio (Whisper) | ⏳ DESIGNED, NOT BUILT | STT design approved 2026-08-12; 0 lines of `lib/stt.py` exist |
| parse_document | ⚠️ PARTIAL | `lib/pdf_knowledge.py`, `lib/fast_extract.py` exist |
| android_accessibility | ⚠️ ANALOG | `lib/browser_control.py` (page-level CDP :9222) is the browser analog; Android is Phase 2 |
| Output sanity check | ⚠️ PARTIAL | `lib/post_response_verifier.py`, `lib/anti_hallucination.py`, `minify_response()` exist |

### Architecture decisions (user-confirmed 2026-08-12)

1. **Overseer model drives everything.** The tiny LFM2.5-1.2B (:8082) is the
   orchestration brain. CPU + scripts do the heavy lifting (adapters,
   ingestion, RAG). The big model (:8080) stays untouched.
2. **Overseer stays stateless.** It stores no data itself. CortexLLM memory
   is the persistence layer.
3. **Queue schedules, loop executes, registry acts.** The existing task queue
   stays as the scheduler. A queued reasoning task spawns a ReAct session.
   The ReAct loop calls tools via the registry.
4. **Two-memory split.** CortexLLM = conversation history + commands + overseer
   state (small, hot). Domain DBs = domain-specific knowledge (SQLite + vector,
   bulk, fast). `rag_query` is a composite tool that searches both.

---

## 2. Architecture

```
User / CLI / webui
   │
   ▼
Task queue (scheduler) ──► ReAct/Socratic loop (overseer model :8082)
   │                              │
   │                              ▼
   │                    Tool registry (execute_tool)
   │                              │
   │        ┌──────────┬──────────┼──────────┬─────────────┐
   │        ▼          ▼          ▼          ▼             ▼
   │   run_command  query_llm  web_search  rag_query   adapters*
   │        │          │          │          │             │
   │        │          │          │    ┌─────┴─────┐       │
   │        │          │          │    ▼           ▼       │
   │        │          │          │  CortexLLM   Domain DBs │
   │        │          │          │  (memory)   (SQLite+vec)│
   │        │          │          │                        │
   └────────┴──────────┴──────────┴────────────────────────┘
                          │
                          ▼
              post_response_verifier → user
```

- **Queue** = what to do (existing `lib/overseer.py` queue/schedule, unchanged)
- **Loop** = how to think (new, step 2)
- **Registry** = how to act (new, step 1)
- **CortexLLM** = persistence + conversation memory (existing, unchanged)
- **Domain DBs** = knowledge layer (new, step 3)

---

## 3. Roadmap — 5 ordered steps

| Step | Build | Reuses | Why this order |
|---|---|---|---|
| 1 | **Tool registry** + `rag_query` (CortexLLM half) | Task queue, state, cortexllm | Foundation. Refactor of existing dispatch. `rag_query` real from day one |
| 2 | **ReAct/Socratic loop** | Tiny LLM driver, `task_steps` publishing | Proves orchestration shape with real tools |
| 3 | **Domain DBs + ingestion** — SQLite FTS5 + sqlite-vec per domain | Scheduler (cron) | Data foundation; ingestion runs in background |
| 4 | **Adapters** — Moondream/Florence, Whisper, Docling → text | Tool registry | Self-contained CPU tools |
| 5 | **Domain-DB search in `rag_query` + ingestion jobs** | Domain DBs + registry | Capstone — needs step 3's data |

Each step is its own spec → plan → implementation cycle. This spec covers
**step 1** in detail; later steps get their own specs.

---

## 4. Step 1 — Tool Registry

### 4.1 New module `lib/tool_registry.py`

Declarative registry, stdlib-only, matching the codebase style. Each tool is
an OpenAI-compatible function schema (what the tiny model's chat template
renders) + a handler function.

```python
TOOLS = {
    "run_command": {
        "description": "Run a shell command, return stdout/stderr",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}},
                       "required": ["command"]},
        "handler": _run_command,
    },
    # ... see 4.2 for the full v1 set
}

def list_tools() -> list:
    """OpenAI function-schema list — what the model sees for tool_calls."""

def execute_tool(name: str, args: dict) -> dict:
    """Dispatch to handler. Returns {"ok": bool, "output": str, "error": str}."""

def register_tool(name: str, schema: dict, handler) -> None:
    """Add a tool at runtime — later steps (adapters, RAG) register here."""
```

### 4.2 v1 tool set

| Tool | Source | Real in step 1? |
|---|---|---|
| `run_command` | task type `command` | ✅ real |
| `query_llm` | task type `llm` | ✅ real (wraps `_query_tiny_llm`) |
| `spawn_subagent` | task type `subagent` | ✅ real (wraps `_spawn_subagent`) |
| `generate_image` | task type `image` | ✅ real (diffusers) |
| `generate_video` | task type `video` | ✅ real (diffusers) |
| `generate_media` | task type `media` | ✅ real (auto-detect) |
| `web_search` | firecrawl_proxy / fast_extract | ✅ real |
| `rag_query` | CortexLLM search | ✅ real (CortexLLM half; domain-DB half in step 3) |
| `describe_image` | — | ⏳ stub → step 4 |
| `transcribe_audio` | — | ⏳ stub → step 4 |
| `parse_document` | — | ⏳ stub → step 4 |
| `ingest_domain` | — | ⏳ stub → step 3 |

Stubs are registered with a real schema but return
`{"ok": False, "error": "not implemented yet"}`. This gives the ReAct loop
(step 2) its complete tool surface immediately; each later step fills in a
real handler via `register_tool`.

### 4.3 Refactor `lib/overseer.py`

`_execute_task(task)` becomes a thin wrapper over the registry:

```
task type "command"  → execute_tool("run_command", {"command": ...})
task type "llm"      → execute_tool("query_llm", {...})
task type "subagent" → execute_tool("spawn_subagent", {...})
task type "image"    → execute_tool("generate_image", {...})
task type "video"    → execute_tool("generate_video", {...})
task type "media"    → execute_tool("generate_media", {...})
```

The queue, scheduler, and state machinery stay **untouched** — pure dispatch
refactor. `_execute_task` returns `result["ok"]` so the queue's
completed/failed bookkeeping is unchanged.

### 4.4 Testing

- `lib/tool_registry.py --smoke` — registers all tools, executes
  `run_command` + `query_llm`, validates the OpenAI schema shape, verifies
  stubs return the not-implemented error.
- Extend `tests/run_smoke.py` with registry checks.
- `cortexagent doctor` + full smoke must pass.

---

## 5. Step 1 — `rag_query` (CortexLLM half)

Composite tool, real from step 1:

```
rag_query(domain, query, limit=10)
   ├── CortexLLM memory search   ← REAL in step 1
   │     · engine.search(query, tier="hot")   BM25 keyword scan
   │     · engine.search(query, tier="warm")  BM25 keyword scan
   │     · cold_get(domain) → filter by query  domain cold category
   │     · cortexllm_vector (semantic)         if available
   └── Domain DB search           ← lands with step 3
         · SQLite FTS5 + sqlite-vec for that domain
         · returns empty gracefully until the DB exists
```

The overseer already imports `cortexllm` directly (stats, atomic, plan), so
`rag_query` imports `cortexllm.engine.search` + `cortexllm_vector` the same
way. Results are formatted as plain text (ranked, truncated) for the model.

**Why CortexLLM half first:** the search infrastructure exists today. The
tool is useful immediately (searches conversation history + cold domain
facts), and step 3 adds the fast domain-DB backend to the same tool.

---

## 6. Out of scope (later steps — own specs)

- **Step 2** — ReAct/Socratic loop: tiny model generates `tool_calls` via
  :8082, loop executes via registry, observes, repeats. Socratic branch for
  ambiguous/investigative prompts (triggered by `pre_flight_gate` ambiguity).
- **Step 3** — Domain DBs: SQLite FTS5 + sqlite-vec per domain
  (business, dfir, law, osint, programming); ingestion via cron jobs.
- **Step 4** — Adapters: Moondream/Florence (image), faster-whisper (audio),
  Docling (documents) → plain text, CPU.
- **Step 5** — Domain-DB search in `rag_query` + ingestion jobs.
- **Phase 2** — Android accessibility, phone overseer, model distillation.

---

## 7. Tracking

- This file = `docs/superpowers/specs/2026-08-12-slimtoken-orchestration-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
- Every commit appends a ✅ row to the changelog DONE table.
