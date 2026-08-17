# CortexAgent — Overview

**A local-first AI runtime with persistent memory, model orchestration, and a controllable surface.**
Version 0.5.3 · last updated 2026-08-16

---

## What this is, in one paragraph

CortexAgent is a single Python application that runs large language models on your own hardware, holds an evolving memory of your work, and exposes that capability through three surfaces — a terminal app, a system tray, and a desktop dashboard. It is not a chat product. It is the substrate that holds your local models, your context, and your tooling together so the working session is durable, observable, and yours.

---

## Why it exists

The market has converged on three patterns for AI assistance, and each has a structural problem that this project addresses:

| Pattern | What it does well | The structural problem |
|---|---|---|
| **Hosted chat** (ChatGPT, Claude.ai, Gemini) | Strongest models, low friction | Your context lives on someone else's server, months of work evaporate when a provider changes policy or pricing |
| **Local models** (llama.cpp, Ollama standalone) | Your hardware, your data | You're stuck re-explaining everything each session; no memory, no orchestration, no observability |
| **AI IDEs** (Cursor, Copilot) | Embedded in editor | Tied to a single workflow; no control over which model runs, no record of what was tried |

CortexAgent occupies the fourth quadrant: local-first, durable, observable, and not locked to a single workflow. The premise is that **the work matters more than the model** — the conversation history, the project state, the prompt patterns that work for you, the local files you've dragged in. All of that should outlive any particular model swap or vendor change.

---

## Who it's for

The user profile that drives every design decision in this codebase:

- **Senior individual contributor** — engineer, researcher, analyst, writer — who runs long-lived projects where the artifact isn't a single answer but a body of accumulated work
- **Privacy-conscious** — work product stays on the workstation; nothing leaves the machine unless the user explicitly toggles an external provider
- **Wants control** — current model, fallback model, context budget, memory depth, what gets logged — all exposed, none hidden
- **Comfortable in a terminal** — but not required to live there; the tray and dashboard cover the rest

This is not positioned for casual users, and it is not production SaaS. The intended deployment is "a single workstation, owned and operated by one person, for as long as that person is using it."

---

## What problem it actually solves

### 1. Context loss between sessions

Every LLM tool eventually asks the same question: *where did I leave off?* Hosted products answer this with cloud sync. Local models answer it with nothing.

CortexAgent answers it with a three-tier memory under the user's `~/.cortexagent/` and `~/.config/cortexllm/` directories:

```
┌───────────────────────────────────────────────────────────────────────┐
│  HOT MEMORY                                                            │
│  Append-only NDJSON. One line per request/response. Last 200 lines     │
│  read on boot. Volatile, fast, cheap.                                  │
│  → "what did I just ask?"                                              │
├───────────────────────────────────────────────────────────────────────┤
│  COLD MEMORY                                                           │
│  Tagged, indexed, on-disk. Categorized (system, project, user,        │
│  feedback, reference). Persists indefinitely.                          │
│  → "what did I conclude about X two months ago?"                       │
├───────────────────────────────────────────────────────────────────────┤
│  DOMAIN DATABASE (per-project)                                         │
│  SQLite + embeddings. Project-scoped retrieval.                        │
│  → "what's in *this* project's knowledge base?"                        │
└───────────────────────────────────────────────────────────────────────┘
```

The user never deletes anything — entries are tagged, archived, and forgotten slowly rather than wiped.

### 2. Model brittleness

A 35B model can vanish from a model zoo overnight. A 13B model can OOM on a CUDA upgrade. A local inference server can crash mid-response. CortexAgent treats the model as a swappable component:

```
                    ┌─────────────────────────────────────┐
                    │         REQUEST                     │
                    └──────────────┬──────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │        PROXY (slimtoken)            │
                    │  - context compression               │
                    │  - tool-call routing                 │
                    │  - token budget enforcement          │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
        ┌────────────────────┐         ┌────────────────────┐
        │  PRIMARY MODEL     │         │  FALLBACK MODEL    │
        │  Qwen3.6-35B-A3B   │         │  LFM2.5-8B-A1B     │
        │  ~13.7 GB VRAM     │         │  ~6.7 GB VRAM      │
        │  128k context      │         │  128k context      │
        │  :8080             │         │  (auto-swap)       │
        └────────────────────┘         └────────────────────┘
```

When the primary model is hot, it answers. When GPU pressure rises above a threshold, the daemon transparently unloads the primary and brings up the lighter fallback. The user sees a 200ms stall, not a broken session.

### 3. Invisible behavior

Most LLM tools show you the answer and hide the process. CortexAgent instruments every step:

```
   prompt entered
        │
        ▼
   ┌────────────────────────────────┐
   │  COLLECT       typed blocks    │  ← what categories of context are loaded
   │  COMPOSE       policy frame    │  ← what protection rules apply
   │  SLIMTOKEN     minify pass     │  ← how many tokens were saved
   │  FINALIZE      validation      │  ← does the request fit the budget
   │  PREFILL       prefill tok/s   │  ← how fast did the model ingest
   │  DECODE        decode tok/s    │  ← how fast is the model writing
   │  DELIVER       delivery status │  ← did the response reach the user
   └────────────────────────────────┘
        │
        ▼
   answer rendered
```

The Overseer dashboard is the human-readable face of this pipeline. Every node is clickable, every metric is real (never fabricated), and the bottom strip shows the *prompt pathway* — the complete causal chain from keystroke to rendered response.

### 4. Tool sprawl

Modern LLM work needs tools: file access, web search, browser automation, scheduler, code execution. Most toolkits bolt these on ad hoc. CortexAgent ships a registry:

| Tool category | Examples | Routing |
|---|---|---|
| Local read | file glob, grep, file open | Always safe |
| Local write | file edit, sed, archive | User-gated per session |
| Network | web search, web scrape | Provider opt-in |
| Browser | Playwright/CDP-driven | User-gated per session |
| Scheduler | cron tasks, recovery | Always-on daemon |
| Memory | append hot, tag cold, retrieve | Always safe |

Tools are registered in `lib/tool_registry.py` and routed by the Overseer. The user can see what was called, when, and with what arguments.

---

## How the user experiences it

### Three surfaces, one session

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   CORTEX CLI              TRAY APP              OVERSEER DASHBOARD       │
│   (terminal)              (system tray)         (desktop window)        │
│                                                                         │
│   ┌──────────────┐       ┌──────────────┐       ┌──────────────────────┐│
│   │ > ask ...    │       │  ◈ tray      │       │ ◈ CORTEXAGENT        ││
│   │              │       │  / menu      │       │   / OVERSEER         ││
│   │  answer...   │       │  / chat      │       │                      ││
│   │              │       │              │       │  [pipeline strip]    ││
│   │  ▮           │       │  ──── ●      │       │  [settings panel]    ││
│   │  streaming   │       │  running     │       │  [test harness]      ││
│   └──────────────┘       └──────────────┘       └──────────────────────┘│
│         │                       │                       │              │
│         └───────────────────────┴───────────────────────┘              │
│                                 │                                      │
│                                 ▼                                      │
│                    ┌────────────────────────┐                          │
│                    │   SHARED SESSION        │                          │
│                    │   (atomic NDJSON log)   │                          │
│                    └────────────────────────┘                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

A prompt typed in the terminal appers in the dashboard's pathway strip. A test-prompt run from the dashboard shows up in the tray's recent-activity list. One session, one log, three vantage points.

### A typical session

```
20:14:03  user types prompt in CLI
20:14:03  hot memory: appended "user" entry
20:14:04  overseer: routes to big model (Qwen3.6-35B)
20:14:04  slimtoken: compressed 142k → 38k tokens (27% saved)
20:14:04  ✓ gateway connection open
20:14:05  prefill: 1,420 tok/s
20:14:06  decode:  38.4 tok/s
20:14:11  cold memory: tagged entry "project:homepage-redesign"
20:14:11  response streamed to user
```

The user sees the answer. The dashboard sees the pathway. The tray sees the activity. The session log sees everything.

---

## Architecture, in one diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          USER SURFACES                                   │
│                                                                          │
│    ┌───────────────┐    ┌───────────────┐    ┌────────────────────┐     │
│    │  CLI / REPL   │    │   TRAY APP    │    │  OVERSEER DASHBOARD│     │
│    │  lib/cortex.py│    │  tray/        │    │  lib/overseer_*/   │     │
│    └───────┬───────┘    └───────┬───────┘    └──────────┬─────────┘     │
│            │                    │                       │               │
└────────────┼────────────────────┼───────────────────────┼───────────────┘
             │                    │                       │
             ▼                    ▼                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       SESSION BRIDGE (shared NDJSON)                     │
│                       atomic, append-only, flocked                       │
└────────────┬─────────────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          DAEMON (always-on)                              │
│                                                                          │
│    ┌────────────────┐    ┌────────────────┐    ┌──────────────────┐     │
│    │  PROXY         │    │  SCHEDULER     │    │  WORKER POOL     │     │
│    │  slimtoken     │◀──▶│  NDJSON store  │◀──▶│  crash recovery  │     │
│    │  tool routing  │    │  recovery      │    │  heartbeat       │     │
│    └────────┬───────┘    └────────────────┘    └──────────────────┘     │
│             │                                                             │
└─────────────┼─────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       MODEL LAYER (servers)                              │
│                                                                          │
│    ┌──────────────────────────┐    ┌──────────────────────────┐         │
│    │  BIG: Qwen3.6-35B-A3B    │    │  FALLBACK: LFM2.5-8B-A1B │         │
│    │  llama.cpp :8080         │    │  llama.cpp (auto-swap)   │         │
│    │  13.7 GB VRAM            │    │  6.7 GB VRAM             │         │
│    └──────────────────────────┘    └──────────────────────────┘         │
│                                                                          │
│    ┌──────────────────────────┐    ┌──────────────────────────┐         │
│    │  OVERSEER: 1.6B MoE      │    │  (optional) OpenAI /     │         │
│    │  llama.cpp :8082         │    │  Anthropic opt-in        │         │
│    │  tool calls + routing    │    │  via conf [provider]     │         │
│    └──────────────────────────┘    └──────────────────────────┘         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       MEMORY LAYER                                       │
│                                                                          │
│    HOT (JSONL)          COLD (LMDB)          DOMAIN (SQLite/embeddings)   │
│    ~/.config/cortexllm  ~/.cortexagent/      per-project                 │
│    last 200 requests    tagged, indexed      vector + BM25               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

Each layer is a small, replaceable component. The daemon is the only required long-running process; everything else can be brought up or down independently.

---

## Design constraints

These are the rules that govern every change to the codebase. They are not aspirations — they are load-bearing.

### Local-first

- **Nothing leaves the machine unless the user explicitly opts in.** External providers (OpenAI, Anthropic) are configured per-session via `conf [provider]` keys, never by default.
- **All state is on disk under `~/.cortexagent/` or `~/.config/cortexllm/`.** No cloud sync, no telemetry, no remote config.
- **Bind to `127.0.0.1` only.** No `0.0.0.0`. The dashboard, the tray, the daemon — all localhost.

### Observability over opacity

- **Never fabricate a metric.** If a number is not instrumented, the UI shows `—` or "Unavailable". This is a hard rule; the cost of a placeholder zero is misplaced trust.
- **Every pipeline stage emits a typed event.** The dashboard consumes them; nothing is inferred from raw logs.
- **Every state change is visible.** When the model swaps, when the scheduler unloads, when cold memory is appended — the user can see it.

### Durability over convenience

- **Hot memory is append-only.** No truncation, no compaction. The file grows; the bounding rule is per-session read-window.
- **Cold memory is tagged, never deleted.** A feedback rule from a year ago is still retrievable.
- **Domain embeddings are versioned.** When the embedding model changes, old vectors are migrated, not invalidated.

### Composability over monolith

- **Each layer is replaceable.** Swap the proxy, swap the inference server, swap the memory backend — the rest of the system keeps working.
- **No cross-layer coupling.** The CLI doesn't know about the dashboard; the daemon doesn't know about the tray. The session bridge is the contract.

### Privacy by default

- **No third-party analytics.** No error reporting service. No update check.
- **No LLM calls except to servers the user has configured.** The overseer model is *local* unless explicitly overridden.
- **No accidental exfiltration.** `httpx` and `requests` are wrapped to refuse connections outside `127.0.0.1` unless the user runs a session with `--provider=external` flag.

---

## What is deliberately out of scope

The project is small. The boundary is drawn tightly:

- **No multi-user.** Single workstation, one operator. Collaboration is solved by `git`, not by adding tenants.
- **No hosted offering.** No SaaS, no API, no team plan. The artifact is the codebase, not a service.
- **No fine-tuning.** Models are used as-is. Fine-tuning is a research project, not a runtime feature.
- **No agent framework.** There is no "swarm" or "team of agents" abstraction. The Overseer routes a single request to a single capability.
- **No mobile / web client.** The desktop surfaces are the surface. The web UI is local-only.
- **No model training or evaluation pipeline.** That's a separate project.
- **No finished commercial product.** This is working software for one user, made available to others who want the same.

---

## What's currently shipping

The codebase is organized by responsibility, not by feature flag. Each subsystem has its own bounded surface:

| Subsystem | Purpose | Entrypoint |
|---|---|---|
| **Daemon** | Always-on orchestrator; model lifecycle, scheduler, proxy | `lib/daemon.py` |
| **Overseer** | Local model for routing + tool calls | `lib/overseer.py` |
| **SlimToken** | Context compression proxy with deterministic transforms | `lib/slimtoken_proxy.py` |
| **CLI** | Terminal interface with streaming + typed output | `cortex` / `bin/cortexagent` |
| **Tray** | System tray menu + chat micro-UI | `lib/tray_dashboard.py` |
| **Dashboard** | Full desktop pipeline + settings + test harness | `python3 -m lib.overseer_dashboard` |
| **Memory** | Three-tier: hot (JSONL), cold (LMDB), domain (SQLite) | `lib/cortexllm/` |
| **Scheduler** | NDJSON event store + crash recovery | `lib/scheduler/` |
| **Worker pool** | Concurrent task execution with heartbeats | `lib/worker_pool.py` |
| **Tool registry** | Capability routing, side-effect gating | `lib/tool_registry.py` |
| **Browser** | Playwright/CDP-driven automation | `lib/browser_control.py` |
| **Diffusion** | Image/video via diffusers (in-process) | `lib/diffusion_backend.py` |
| **STT** | Voice input via Whisper | `lib/stt.py` |

Each is intentionally small. The largest file is `lib/overseer.py` (~800 lines). The total codebase is roughly 18k lines of Python across ~80 modules — a number chosen for navigability, not minimalism.

---

## Operational reality

A single RTX A4500 workstation (16GB VRAM) runs the full stack:

```
  VRAM budget (16 GB total)
  ┌────────────────────────────────────────────────────┐
  │  ████████████████████████████████░░░░░░░░░░░░░░░░  │  Big model: 13.7 GB
  │  ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  Overseer: 0.6 GB
  │  ███░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │  Reserved: 1.7 GB
  └────────────────────────────────────────────────────┘
```

When VRAM pressure forces an unload, the daemon hot-swaps to the smaller fallback; the user sees a brief pause, not a session break. The dashboard surfaces this transition explicitly.

Power draw on this configuration is ~120W sustained under inference. The whole stack is designed to run on a single workstation, not a server rack.

---

## Why this is publishable

For a researcher evaluating the approach, the interesting research questions are:

1. **Does a deterministic, rule-based context compressor match or beat learned compressors on long-context tasks?** This is the SlimToken hypothesis. The implementation is small enough to audit and the tests are open; a careful comparison is feasible.
2. **Does the "tools + memory + local model" stack provide a useful durable substrate for individual knowledge work?** The user has been running it for >6 months; the open question is whether the abstractions generalize beyond a single workflow.
3. **Is the autoswap between two MoE models on a single GPU fast enough to be transparent?** The VRAM-aware fallback is a small experiment; the answer is "yes for ~200ms pauses, no for chat-streaming beats."

The hope is that the codebase is small enough that someone can read the whole thing, run it, and disagree with any of the design choices.

---

## How to read the specs

This document is the overview. The detailed design docs are in `docs/superpowers/specs/`:

| Spec | Covers |
|---|---|
| `2026-08-12-slimtoken-orchestration-design.md` | The context compression proxy, including the protection policy and the dry-run model |
| `2026-08-12-adapters-design.md` | Provider adapters (llama.cpp, OpenAI, Anthropic) and the route-alias system |
| `2026-08-12-domain-db-design.md` | Per-project vector + BM25 retrieval with versioning |
| `2026-08-12-react-loop-design.md` | The Overseer decision loop: when to call tools, when to ask, when to defer |
| `2026-08-12-soc-analyst-overseer-design.md` | A worked example using the Overseer for security-analysis workflows |
| `2026-08-12-stt-integration-design.md` | Voice input pipeline and VAD behavior |
| `2026-08-13-full-harness-design.md` | The harness + skills + browser-control tool layer |
| `2026-08-16-pathway-design.md` | The new visible prompt-pathway strip in the dashboard |

Start with the spec that matches the question you have. The overview above is the only document that tries to be self-contained.

---

## Glossary

| Term | Meaning |
|---|---|
| **Overseer** | The local small model that routes requests, decides tool calls, and manages the request loop. Not the answer-generator. |
| **Big model** | The primary text-generation model. Currently Qwen3.6-35B-A3B. |
| **Fallback** | The lighter model swapped in when VRAM is tight. Currently LFM2.5-8B-A1B. |
| **SlimToken** | The deterministic context compressor that runs before the request hits the model. |
| **Pathway** | The visible chain of stages a single prompt travels through, from intake to delivery. |
| **Hot memory** | Append-only JSONL of recent requests/responses. Volatile. |
| **Cold memory** | Tagged, indexed, durably stored knowledge. |
| **Domain database** | Per-project embedding index. |
| **Daemon** | The always-on orchestrator that owns model lifecycle, scheduler, and proxy. |
| **Session bridge** | The shared NDJSON file that connects the CLI, tray, and dashboard to one log. |
| **VAD** | Voice activity detection. Used by the STT subsystem. |

---

## Closing

This is a working system, not a roadmap. The features described exist and run on the workstation where this file is being written. The specs are accurate as of 2026-08-16. Drift is expected; the daily changelog at `docs/superpowers/specs/2026-08-10-daily-changelog.md` is the running record.

The premise of the project — that the work outlives the model — is a hypothesis, not a verdict. The codebase is the experiment.
