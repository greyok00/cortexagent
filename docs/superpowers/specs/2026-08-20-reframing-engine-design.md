# Reframing Engine — Frame Any Prompt as Ongoing Work (Design)

**Date:** 2026-08-20
**Status:** ✅ APPROVED (user sign-off) · ⏳ NOT YET BUILT
**Canonical anchor:** `cortexagent/lib/reframing_engine.py` (canonical engine) + `~/reframing-engine/` (standalone)
**Scope:** Two SEPARATE processes. **Process B** (reframing engine) is the build. **Process A** (STT fix) is a separate workstream — **DO NOT MERGE THEM.**

---

## 0. The two processes (HARD separation)

| | Process B — Reframing Engine | Process A — STT Fix |
|---|---|---|
| **Purpose** | Frame ANY prompt input so the LLM understands it as ongoing work, not a one-shot | Fix garbled STT output + hallucinations |
| **Input** | Any prompt (typed / pasted / STT output / anything) | Raw audio clips |
| **Output** | Framed prompt + system prompt + domain + context | Clean transcript |
| **Location** | `cortexagent/lib/reframing_engine.py` + `~/reframing-engine/` | STT pipeline (`lib/stt.py`, `lib/stt_daemon.py`) |
| **Relationship** | Independent. STT output may *feed into* it, but the engine is not part of the STT pipeline | Independent. Fixes the STT pipeline itself |

**The user's directive (verbatim):** "THIS DOMAIN REFRAMING HAS NOTHING TO DO WITH STT. DO NOT MERGE THEM. IT IS A SEPARATE PROCESS FOR ALL PROMPT INPUTS TO FRAME IT FOR LLM MODELS TO UNDERSTAND INSTEAD OF THEM THINKING ITS A ONE SHOT."

---

## 1. What Process B is

A context-framing engine that takes any prompt and frames it so the LLM
treats it as part of ongoing work — attaching session state, relevant
memory, and project context — instead of a fresh one-shot query.

Builds on the existing canonical reframing base: `slimtoken.prompt_reframe`
(pure CPU, deterministic: `classify_domain` → `reframe_prompt` →
`shrink_prompt` → `minify_prompt` → `build_system`). The engine reuses that
base for cleaning + domain classification, then adds a **context-framing
layer** on top.

## 2. Architecture

```
any prompt input
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 1. CLEAN  (slimtoken reframe_prompt)                │
│    strip filler · dedupe · shrink                    │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 2. CLASSIFY  (slimtoken classify_domain)            │
│    business / code / osint / cybersecurity / …      │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 3. GATHER CONTEXT  (three sources, each optional)   │
│    · Session state  → recent turns, active task     │
│    · cortexllm     → hot + cold relevant memory     │
│    · Project       → CLAUDE.md/README, active branch│
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ 4. FRAME  (compose the "not a one-shot" prompt)     │
│    "Ongoing work: <session>. Known: <memory>.        │
│     Project: <project>. User request: <cleaned>"    │
│    + build_system(domain, role, style)               │
└──────────────────────────────────────────────────────┘
    │
    ▼
framed prompt + system prompt + domain + {sources used}
```

### 2.1 Key properties

- **Composable** — each context source is optional. Works with zero sources
  (domain framing only) up to all three.
- **Deterministic base** — slimtoken does cleaning/classifying; the engine
  adds context. No LLM call in the base path.
- **Diagnostic output** — returns which sources were attached, so the framing
  is inspectable.
- **Source-agnostic** — takes any prompt input, not tied to STT.

## 3. Context sources

| Source | What it provides | How it's read |
|--------|-------------------|---------------|
| **Session state** | Recent turns, active task, current project | CortexAgent session state (SessionBridge shared-file backbone) |
| **cortexllm memory** | Hot + cold relevant items | cortexllm memory read (hot NDJSON + cold curated facts) |
| **Project context** | CLAUDE.md/README, active branch | Project directory scan |

Each source is optional and independently disableable. If a source is
unavailable (no session, no memory server, no project), the engine degrades
gracefully to the remaining sources.

## 4. Public surface

```python
# cortexagent/lib/reframing_engine.py
def reframe(
    prompt: str,
    *,
    session: Optional[SessionState] = None,
    memory: Optional[MemoryReader] = None,
    project: Optional[ProjectContext] = None,
    role: str = "generalist",
    style: str = "terse",
) -> ReframeResult:
    """Frame a prompt as ongoing work. Returns ReframeResult."""

class ReframeResult:
    framed: str          # the composed "not a one-shot" prompt
    system: str          # build_system(domain, role, style)
    domain: str          # classify_domain result
    sources: list[str]   # which context sources were attached
    cleaned: str         # the cleaned prompt (pre-framing)
```

## 5. Standalone `~/reframing-engine/`

| Component | What |
|-----------|------|
| `reframe` CLI | `echo "prompt" \| reframe` → framed output; `--no-context` for domain-only |
| MCP server | Exposes `reframe`, `classify`, `frame` tools (mirrors slimtoken's `prompt_reframe_server`) |
| `demo.py` | Runs a real prompt through, shows before/after framing |
| `research/` | STT fix research + reframing design notes |
| `tests/` | Unit tests for the engine |

The standalone imports the canonical engine from cortexagent (with a
slimtoken fallback, mirroring how `lib/prompt_framing.py` resolves its
engine). No logic duplication.

## 6. Process A — STT fix (separate workstream)

**Problem:** STT produces garbled output (word-level mishears: "toor"→"tool",
"reef"→"reframing engine") and hallucinations ("Thank you for watching!~"
when the user isn't watching anything).

**Hard constraints (user directive):**
- STT must **stay in VRAM** (GPU), never silently fall back to CPU.
- **Never evict the overseer** (LFM2.5-1.2B, ~0.95 GB on :8082).
- **Never evict the big model** (Qwen3.6-35B, ~13.7 GB on :8080).
- Work within whatever VRAM is free (~500 MiB steady-state).

**Scope:**
- Research: fix the current faster-whisper setup (model choice, beam,
  temperature fallback, VAD tuning, vocabulary biasing) within the VRAM
  envelope.
- Fix the "thank you for watching" hallucination that slips past the current
  denylist.
- Deliverable: research notes in `~/reframing-engine/research/` + concrete
  config/code fixes to the STT pipeline.

**NOT merged with Process B.** The reframing engine does not live in the STT
pipeline; the STT fix does not touch the reframing engine.

## 7. Constraints (both processes)

- **No new models.** LLM reconstruction (if any) reuses the resident big
  model or overseer — zero new VRAM.
- **Reuse slimtoken** as the deterministic base — no duplicated reframing
  logic.
- **Localhost-only bindings** (127.0.0.1, never 0.0.0.0) for any server.
- **No PII leaks.** Use `Path.home()` / env vars, never hardcoded paths.

## 8. Definition of done

- [ ] `cortexagent/lib/reframing_engine.py` implements the 4-stage pipeline
- [ ] All three context sources work and are independently disableable
- [ ] `~/reframing-engine/` has CLI + MCP server + demo + research notes + tests
- [ ] STT research notes written (fix current setup, VRAM-constrained)
- [ ] "Thank you for watching" hallucination fixed in the STT pipeline
- [ ] Tests pass; engine works standalone and via cortexagent
