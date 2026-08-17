# About CortexAgent

CortexAgent is a runtime for a self-hosted coding agent. It runs two
local models on a single GPU — a 35-billion-parameter
mixture-of-experts model for reasoning, and a small orchestrator for
scheduling, memory distillation, and diffusion orchestration. All
traffic is over `127.0.0.1`.

CortexAgent is not a from-scratch agent framework. It is built on top of
two existing upstream libraries — [`cortexllm`](`<repo>/cortexllm`)
for memory, scheduling, and lifecycle primitives, and
[`slimtoken`](`<repo>/slimtoken`) for token
minimisation at the request layer. The sections below explain what each
library is, what its core features are, and what CortexAgent adds on
top to turn them into a working agent runtime.

## Components

| Component | Address | Role |
|---|---|---|
| Reasoning model | `:8080` | The agent. |
| Orchestrator | `:8082` | Scheduling, memory, diffusion. |
| Grammar proxy | `:8081` | Middleware that strips grammar, runs slimtoken, forwards to the reasoning model. |
| Webui | `:8090` | Browser interface. |
| Daemon | AF_UNIX | Owns the reasoning model and proxy. |

## Default reasoning model

| | |
|---|---|
| Model | `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` |
| Total parameters | 35 B |
| Active per token | 3 B (MoE) |
| Footprint | 13.7 GB |
| Context | 128 K |
| Capabilities | Multimodal, uncensored |

## cortexllm

[`cortexllm`](`<repo>/cortexllm`) is a memory
layer that actually remembers, plus the lifecycle helpers every agent
needs. Plain files. POSIX-atomic. No SQL, no vector store, no daemon.

The core API is `cortexllm.append(role=..., content=..., platform=...)`
which atomically appends to a hot NDJSON file. Every prompt and response
survives by default. There are no rotation caps; hot grows unbounded.
Default storage is `~/.config/cortexllm/memory/` with
`hot/<platform>.jsonl` and `cold/<category>.json`.

### Core features

- **Two memory tiers in plain NDJSON / JSON.** Hot is the active
  conversation buffer; cold is curated long-term facts keyed by
  category. All files are `cat`-able, `grep`-able, and
  `rsync`-able — no proprietary format, no inspection tooling needed.
- **POSIX atomic append.** `O_APPEND` with the 4096 B `PIPE_BUF`
  guarantee. Multiple writers (overseer + hook + daemon) cannot
  interleave within a line. Measured **90 000 writes/s** and **14.2
  MiB/s** throughput on Linux + ext4 + NVMe.
- **No caps rule.** Earlier versions had a 300-row cap that silently
  ate data. Killed in v0.4.0, locked in by tests. Hot grows unbounded
  by design.
- **DAG scheduler + workflow engine.** Tasks run in dependency order,
  batched by kind, persistent, with streaming progress events. The
  engine shell is generic; caller's executors do the real work.
- **Cron parser + persistent scheduler.** 5-field cron with
  `@hourly`/`@daily`/`@weekly`/`@monthly` aliases. Fires callbacks.
- **Task queue + numbered-step plan.** FIFO with status transitions
  (atomic tmp+rename writes), plus a numbered checklist that
  auto-advances.
- **Stats + integrity check.** Byte counts, token estimates, NDJSON
  line-validity. Detects corruption and truncation.
- **POSIX single-instance lock + `daemonize()`.** Run a daemon without
  libraries. Restart-safe.
- **12 MCP tools.** `memory_thin_append`, `memory_thin_read`,
  `memory_read`, `memory_write`, `memory_search`, `memory_clear`,
  `memory_cold_list`, `memory_stats`, `memory_integrity`,
  `cron_parse`, `workflow_run`, `workflow_status`.
- **Agent Skill bundle.** `skills/memory/SKILL.md` tells the model
  when to reach for each tool.
- **Host-CLI hook layer.** `hooks/cortexllm-hook.sh` runs in the host
  CLI on every prompt. **Force-persistence** — bypasses the model.
  Wiring available for Claude Code, Codex, and OpenCode.
- **stdlib-only core.** The MCP server is one optional dep. The
  daemon is a `fcntl.flock`. Nothing else.

### What CortexAgent adds

CortexAgent uses cortexllm as a downstream consumer — not as a fork.
The local changes are targeted at three needs the upstream library
does not address:

- **Daemon protocol.** `lib/daemon.py` integrates with `cortexllm.lifecycle`
  for the single-instance PID lock and the systemd `Type=forking`
  unit, but the daemon's full handshake (session lifecycle, model
  adoption, swap commands) is CortexAgent-specific. This was
  intentionally not migrated — see
  `docs/CORTEXLLM-0.4.0-DIVERGENCE.md`.
- **Two-models-only memory schema.** cortexllm uses a free-form
  `platform` key. CortexAgent pins `platform="cortexagent"` for its
  own turns and uses the in-tree `memory/mcp_server.py` MCP server to
  route accordingly. The platform normalization happens at write time
  so consumer reads are stable.
- **SessionBridge over `cortexllm.atomic`.** The CLI ↔ webui shared
  session state (`~/.cortexagent/state/webui_session.jsonl`) is
  appended atomically per turn, never clobbered. This is the
  drop-in path that `lib/memory_thin.py:_atomic_append` already
  migrated to `from cortexllm.atomic import atomic_append`.
- **Overseer scheduler.** The cron registry and the hot → cold
  distillation cadence call into `cortexllm.scheduler` and
  `cortexllm.distiller`, but the orchestration policy (idle-only
  firing, big-model unload for diffusion) is CortexAgent-specific.
- **DAG + workflow templates stay in CortexAgent.** The upstream
  `cortexllm.dag` and `cortexllm.workflow` are intentionally **not**
  adopted — the `engine/workflow.py` templates
  (`_deploy_website_tasks`, `_pentest_tasks`,
  `_malware_analysis_tasks`) carry domain knowledge that does not
  belong in the generic engine shell.

## slimtoken

[`slimtoken`](`<repo>/slimtoken`) is a token
optimisation layer that sits between an Anthropic-compatible client and
its backend — a local llama-server or a cloud API — and rewrites every
request to use **fewer tokens** before forwarding it.

It strips the waste out of every LLM round-trip: repeated tool output,
verbose old turns, bloated system prompts, lead-in filler. The fewer
tokens you send, the faster the prompt-eval, the lower the cost, the
more context headroom you keep.

### Core features

- **Async HTTP(S) proxy** that routes by URL path
  (`/v1/messages` for Anthropic, `/v1/chat/completions` for OpenAI,
  `/api/chat` and `/api/generate` for Ollama). Sits transparently
  between any client and any local or cloud backend.
- **Always-on request-side pipeline.** Tools (drop `$comment`,
  `title`, `examples`; compress description), system (collapse
  whitespace outside fences), messages (collapse blanks; pass
  tool/image blocks untouched), dedup (collapse repeated
  `tool_result` contents; latest kept verbatim), distill (truncate
  old assistant prose beyond the last 4 turns, fence-aware), budget
  (hard token cap, pair-safe prefix drop). All on by default.
- **Pair-safe pruning.** A `tool_result` is never orphaned from its
  `tool_use`. Verified across 32 unit tests including
  pair-safety-specific trials.
- **Fence-aware.** Fenced code blocks (triple-backtick, `~~~`)
  preserved byte-identical. Identity-based change detection returns
  unchanged content zero-copy.
- **Response-side filter.** Strips lead-in filler ("Sure!", "Here is
  the code:", "Let me know if you need anything else.") from the
  streamed response head. On by default. Plus optional
  `SLIMTOKEN_MAX_TOKENS` cap and `SLIMTOKEN_STOP` sequences.
- **`grammar` field stripped.** Removes the `grammar` field from
  request bodies, fixing 400s from llama-server when the grammar
  repetition threshold is exceeded.
- **Backends.** Anthropic, OpenAI, Ollama. OpenAI and Ollama bodies
  are normalised to canonical, minified, then converted back — a
  thin adapter layer; no optimisation logic is duplicated.
- **MCP server** over stdio (`slimtoken-mcp`). 8 tools:
  `optimize_messages`, `estimate_tokens`, `prune_context`,
  `minify_tool_result`, `inspect_budget`, `get_config`,
  `list_model_presets`, `high_context_presets`. Every tool imports
  and calls an existing core function — nothing reimplemented.
- **Agent Skill bundle.** `skills/slimtoken-optimizer/` packaged as
  a static-files skill that any host agent runtime reads from disk on
  activation. Model-agnostic.
- **High-context VRAM presets.** Dense and MoE presets for 4 / 8 /
  16 GB tiers. The 16 GB MoE row at 128 K context is the proven-stable
  value on a 16 GB card.
- **Config optimizer.** Inspects GPU VRAM and model size, recommends
  `llama-server` args, prints ready-to-paste commands plus
  `CORTEXAGENT_*` env exports. Recommend-only; changes nothing.
- **Ships with orjson, xxhash, and tiktoken** for fast JSON, hashing,
  and real token counting.
- **MIT licensed, async (uvloop optional), proxy latency ≈ 12 ms per
  request.**

### What CortexAgent adds

CortexAgent uses slimtoken as a **hard runtime dependency**. The
grammar proxy on `:8081` imports `slimtoken.pipeline` directly. This
turns slimtoken's standalone tool into a chokepoint:

- **The proxy is the integration, not the CLI.** Standalone, slimtoken
  is a tool an agent might reach for when a prompt is too big. In
  CortexAgent it runs on **every request** through the grammar proxy,
  so minification is guaranteed — not left to the model's discretion.
- **Bound to a configuration gate.** The proxy is configured with
  `SLIMTOKEN_*` env knobs. One always-on config (the old "aggressive"
  preset, minus the name). All stages are wired by default; per-stage
  disable via `SLIMTOKEN_MINIFY_<STAGE>=0`.
- **`grammar` field removal lives in the same proxy.** The proxy on
  `:8081` does two things in one pass: strip `grammar` and minify.
  llama-server's chunked transport rejects requests with the `grammar`
  field past a repetition threshold; the proxy fix lives next to the
  slimtoken call so both pieces of the chokepoint stay in sync.
- **Backward-compatible fallback chain.** If slimtoken is missing or
  the user opts out (`SLIMTOKEN_MINIFY=0`), the proxy passes the
  request through unchanged. The fallback path is exercised by the
  smoke gate's grammar-proxy area.
- **Output filter wired to the CLI ruleset.** `SLIMTOKEN_FILLER=1` is
  the default; `R4` in the CLI rules (`Output-side minify`) uses it.

## CortexAgent-specific features

These are the features that exist because of CortexAgent's design
choices, not because they are inherited from upstream.

- **Two-models-only stack.** Reasoning model on `:8080` (13.7 GB
  multimodal, uncensored) + orchestrator on `:8082` (≤2 GB MoE).
  Nothing else. Fallback is explicitly forbidden and gate-enforced
  in `tests/run_smoke.py`.
- **Grammar proxy as chokepoint** on `:8081`, owned by the daemon.
- **Always-on systemd services.** Two user units (`cortexagent.service`,
  `cortexagent-overseer.service`) that start on login and persist
  after the terminal closes.
- **3D webui** on `:8090`. 3D chat surface, shared session with the
  CLI via SessionBridge, live overseer widgets.
- **System-tray popout** (`lib/tray.py` + `lib/tray_dashboard.py`).
  Linked to the overseer via systemd `Wants=` + `PartOf=`.
- **In-process diffusion.** SDXL / SD 1.5 / LTX-Video on the same
  GPU. The orchestrator unloads the reasoning model to free VRAM,
  runs diffusers, then reloads — ~30 s swap latency.
- **3D control panel** (system-tray popout) showing memory bars,
  cron status, and reasoning-model step counter.
- **CLI rules R1–R7.** Plain CLI by default, code hidden unless
  requested, response minify on the output side, visual output always
  on.
- **`cortexagent doctor`** repairs settings drift idempotently
  without overwriting anything.
- **Smoke gate.** 30 tests, 31 modules covered. Must pass before
  commit.

## Quick start

```bash
git clone `<repo>/cortexagent` ~/cortexagent
cd ~/cortexagent
bash install.sh
cortexagent
```

The webui is at `http://127.0.0.1:8090/`.

Full documentation in [README.md](README.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

**Maintainer:** GreyOK00 ·
**License:** MIT ·
**Repository:** `<repo>/cortexagent`