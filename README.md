# CortexAgent

CortexAgent is a runtime for a self-hosted coding agent. It pairs a
35-billion-parameter mixture-of-experts model for inference with a
small always-on model for orchestration, threads every request through
a middleware proxy, and persists conversation state to plain NDJSON
files via [cortexllm](https://github.com/greyok00/cortexllm). Diffusion
runs in-process on the same GPU.

## Overview

CortexAgent runs two models on a single GPU and serves them through a
local middleware stack.

| Component | Address | Role |
|---|---|---|
| Reasoning model | `:8080` | The agent. Handles code reasoning, vision, and long-form generation. |
| Orchestrator | `:8082` | Drives scheduling, memory distillation, and diffusion orchestration. |
| Grammar proxy | `:8081` | Strips tool-call grammar that `llama-server` rejects and minifies the prompt with `slimtoken` before forwarding. |
| Daemon | AF_UNIX `~/.cortexagent/control.sock` | Owns the reasoning model and proxy. Manages session lifecycle. |
| Webui | `http://127.0.0.1:8090/` | Browser interface. Shares the session with the CLI. |
| Diffusion | in-process | SDXL / SD 1.5 / LTX-Video on the same GPU. |

The reasoning model is the only model on `:8080`. The orchestrator is
the only model on `:8082`. There is no fallback model and no third
model slot.

![workflow](assets/workflow.svg)

## Installation

```bash
git clone https://github.com/greyok00/cortexagent ~/cortexagent
cd ~/cortexagent
bash install.sh
```

The installer registers two systemd user services
(`cortexagent.service`, `cortexagent-overseer.service`) that start on
login and persist after the terminal closes.

Requirements:

- A `llama-server` binary (a `llama.cpp` build).
- The reasoning model weights. The default is
  `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` (≈13.7 GB), multimodal and
  uncensored. Override with `CORTEXAGENT_MODEL` or `big_model` in
  `~/.cortexagent/cortexagent.conf [backend]`.
- The orchestrator model weights, ≤2 GB. Override with
  `CORTEXAGENT_OVERSEER_MODEL` or `overseer_model` in the same file.
- An NVIDIA GPU with enough VRAM for both models (defaults tuned for
  16 GB).

## Usage

```bash
cortexagent                       # interactive CLI
cortexagent -p "fix this bug"     # one-shot
cortexagent --restart             # restart both services
cortexagent doctor                # repair config drift
cortexagent status                # inspect runtime state
```

The webui is at `http://127.0.0.1:8090/`. The CLI and webui share one
session.

Diffusion is invoked through the CLI or the agent itself:

```bash
python3 lib/diffusion_backend.py gen-image "a cat in a hat" --output cat.png
python3 lib/diffusion_backend.py gen-video "a dog running"    --output dog.mp4
```

## The reasoning model

| | |
|---|---|
| Default | `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` |
| Quantisation | IQ3_S |
| Total parameters | 35 B |
| Active per token | 3 B (mixture-of-experts) |
| Footprint | 13.7 GB |
| Context | 128 K |
| KV cache (q4_0) | ≈ 640 MB |
| Capabilities | Multimodal, uncensored |

The reasoning model is the only model on `:8080`. If it cannot load,
the daemon exits and the systemd unit shows failed status. There is no
fallback swap path.

## The orchestrator

The orchestrator is an MoE on `:8082` with a maximum footprint of 2 GB.
It does not answer user prompts. Its responsibilities are:

- **Scheduling.** Cron-style tasks fire even when no CLI session is open.
- **Memory distillation.** Every 30 s, when the system is idle, the
  orchestrator summarises warm memory into cold facts.
- **Diffusion orchestration.** When the agent or the user requests
  image or video generation, the orchestrator unloads the reasoning
  model to free VRAM, runs `diffusers` in-process, then reloads the
  reasoning model.
- **Keepalive.** A periodic ping keeps the orchestrator model warm so
  it is responsive when its turn comes.

The orchestrator is not a fallback reasoning model. It is a separate
role with a different cost profile.

## The grammar proxy

Every chat request flows through `:8081` before it reaches the
reasoning model. The proxy:

1. Strips `grammar` fields that `llama-server` rejects on the chunked
   transport.
2. Calls `slimtoken.optimize_messages()` to minify the conversation
   pair-safely (system prompts and tool definitions are not touched).
3. Attaches a `<cold_memory>` block drawn from the cold memory tier.
4. Forwards the minified request to `:8080` and streams the response
   back as SSE.

The proxy is the single place where prompt shape is governed. Removing
this layer is not supported.

## Memory

CortexAgent stores conversation state in three tiers, backed by
plain NDJSON files via [cortexllm](https://github.com/greyok00/cortexllm).
No SQL, no vector store, no daemon.

| Tier | Capacity | Purpose |
|---|---|---|
| Hot | 300 most recent exchanges | Inlined into every prompt. |
| Warm | 2,000 entries (70% recent + 30% curated) | Deduped and pruned on each write. |
| Cold | Unbounded | Facts extracted from warm entries by the orchestrator. |

There is no rotation cap on hot or warm. The cold tier is the long-term
knowledge store that survives across sessions.

## Configuration

| Key (`[backend]`) | Env | Default | Notes |
|---|---|---|---|
| `big_model` | `CORTEXAGENT_MODEL` | `~/models/qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf` | Reasoning model. |
| `big_model_port` | `CORTEXAGENT_PORT` | `8080` | |
| `big_ctx` | `CORTEXAGENT_CTX` | `131072` | 128 K. KV cache q4_0 ≈ 640 MB. |
| `big_alias` | `CORTEXAGENT_ALIAS` | `cortexagent` | OpenAI `model` field. |
| `overseer_model` | `CORTEXAGENT_OVERSEER_MODEL` | `~/models/<orchestrator>/<file>.gguf` | ≤2 GB MoE. |
| `overseer_model_port` | `CORTEXAGENT_OVERSEER_PORT` | `8082` | Isolate in tests. |

| Key (`[daemon]`) | Default | Meaning |
|---|---|---|
| `idle_unload_sec` | `0` | 0 = keep the reasoning model loaded at all times. >0 = unload after N seconds of idle. |

Optional diffusion env: `CORTEXAGENT_VIDEO_MODEL`,
`CORTEXAGENT_UPSCALER` (`lanczos` | `realesrgan`),
`CORTEXAGENT_DIFFUSION_CUDNN` (default `0` — see
`lib/diffusion_backend.py`).

## MCP servers (optional — off by default)

CortexAgent ships a full MCP client (`lib/mcp_client.py`) that can register
any MCP server's tools as `mcp_<server>_<tool>` in the overseer's tool
registry. **It is a core feature, but it is disabled by default**: this
install runs fully offline / air-gapped, and MCP servers are network
services that don't work without connectivity.

| Env | Default | Meaning |
|---|---|---|
| `CORTEXAGENT_MCP_SERVERS` | *(unset)* | Comma-separated allowlist of server names to load. Unset = **no MCP tools load at all**. |
| `CORTEXAGENT_MAX_TOOLS` | `16` | Cap on the tool surface the tiny overseer sees. Raise to fit MCP tools. |
| `CORTEXAGENT_TOOL_STUBS` | `1` | Stub-mode minification (below). `0` disables. |
| `CORTEXAGENT_HARNESS_TOOLS` | `1` | `0` disables the whole harness surface (browser/skills/MCP). |

Servers are configured in `~/.mcp.json` (standard `mcpServers` format) and
`~/.cortexagent/config/lazy_mcp_servers.json`. The config stays in place as
the option — flip `CORTEXAGENT_MCP_SERVERS` on and the tools load.

**Stub-mode minification.** The full tool schemas of every MCP server total
~30,000 tokens — far beyond the tiny overseer's 2,048-token context. Stub
mode (`CORTEXAGENT_TOOL_STUBS=1`, the default) shrinks the surface: the
model sees only each tool's **name + one-line description** (~35 tokens vs
~180 full), and `execute_tool` resolves the full schema on the backend —
missing required arguments come back as a `missing required args: <params>`
error the model retries against. The whole 168-tool MCP surface drops from
~30,000 to ~6,000 tokens (80% smaller); the default 16-tool surface from
~1,000 to ~380 (64% smaller). The registry is the indexed database; the
stub is the variable name.

## CLI output rules

The CLI runs in plain mode by default. The dashboard is the webui.

| | |
|---|---|
| R1 | Plain CLI; the dashboard is the webui at `:8090`. |
| R2 | Code is hidden by default. Prefix the prompt with `show code` or `with code` to reveal. |
| R3 | After every response: a `_` divider and a `▎ thinking:` line. |
| R4 | Output-side minify via `lib/grammar_proxy.minify_response()`. |
| R5 | Visual output is always on — tables box-drawn, numeric `█` bars, lists `▎`. |
| R6 | Ambiguous prompts trigger a clarifying question instead of being routed. |
| R7 | The reasoning model stays loaded (`idle_unload_sec=0`) and is multimodal. |

## Upstream libraries

CortexAgent consumes two libraries as packages rather than vendoring
them. Both are MIT-licensed and installable from PyPI.

### cortexllm

[`cortexllm`](https://github.com/greyok00/cortexllm) is the local
memory and atomic-write library. It is a stdlib-only Python package
that provides nine modules and five MCP tools.

| Module | Role | Use in CortexAgent |
|---|---|---|
| `cortexllm.atomic` | Atomic JSONL write (O_APPEND + flock + fsync) | Used by the session bridge for every turn append. |
| `cortexllm.stats` | Memory and token counters | Read by the tray popout and webui to render live memory state. |
| `cortexllm.plan` | Task DAG with conflict detection | Used by the orchestrator scheduler. |
| `cortexllm.drain` | Backpressure-aware queue drain | Used by the prompt queue. |
| `cortexllm.scheduler` | Cron and interval scheduler | Used by the orchestrator. |
| `cortexllm.integrity` | WAL + checksum chain | Used by the session bridge on read. |
| `cortexllm.lifecycle` | Session lifecycle hooks | Template-local. |
| `cortexllm.dag` | DAG executor | Template-local. |
| `cortexllm.workflow` | Workflow template renderer | Template-local. |

CortexAgent consumes the published package and falls back to an
in-tree adapter if a local pin is older than v0.4.0. Local changes are
side-ported back upstream.

### slimtoken

[`slimtoken`](https://github.com/greyok00/slimtoken) is a token
minimisation library. It is a hard runtime dependency: the grammar
proxy imports it directly.

| Capability | Standalone | In CortexAgent |
|---|---|---|
| Pair-safe pruning | Available | Applied to every chat request on `:8081`. |
| Fence-aware compression | Available | Same. |
| Token budget | Configurable | Set to `big_ctx * 0.85` per request. |
| Tool-result compression | Available | Runs after every tool turn. |
| Format support | Anthropic, OpenAI, Ollama | Proxy uses OpenAI format. |
| Async proxy | `slimtoken-proxy` standalone | Built into `:8081`. |
| MCP server | 8 tools | Removed from `~/.mcp.json` — redundant, slimtoken is built in. |
| CLI | `python3 -m slimtoken` | Available. The proxy path is preferred. |

## Project layout

```
cortexagent/
├── bin/cortexagent               # CLI launcher
├── engine/cli.py                 # argparse → daemon control socket
├── lib/
│   ├── daemon.py                 # owns :8080/:8081 + AF_UNIX sock
│   ├── overseer.py               # scheduler + orchestrator
│   ├── grammar_proxy.py          # :8081 chokepoint
│   ├── model_backend.py          # llama-server wrapper
│   ├── diffusion_backend.py      # in-process SDXL / SD 1.5 / LTX
│   ├── tiny_llm.py               # orchestrator client
│   ├── prompt_queue.py           # decompose / conflict / supersede
│   ├── webui.py                  # :8090 server
│   ├── tray_dashboard.py         # tray popout
│   ├── statusline.py             # brand bar
│   └── ...
├── assets/workflow.svg           # architecture diagram
├── assets/cortexagent.jpg        # brand reference
├── config/templates/*.service    # systemd unit templates
├── install.sh
└── tests/run_smoke.py            # 30-test gate before commit
```

## Dependencies

- **Required:** `llama-server` (a `llama.cpp` build), the reasoning model
  GGUF, the orchestrator model GGUF, and an NVIDIA GPU with enough
  VRAM for both.
- **Optional:** the `claude` CLI (for interactive mode), Brave or Chrome
  for browser tools, `diffusers` + `torch` for image and video.
- **Python packages:** `cortexllm>=0.4.0`, `slimtoken>=0.3.3`, `orjson`,
  `xxhash`.

## See also

- [ABOUT.md](ABOUT.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/CORTEXLLM-0.4.0-DIVERGENCE.md](docs/CORTEXLLM-0.4.0-DIVERGENCE.md)
- [docs/SEPARATION.md](docs/SEPARATION.md)
- [docs/AUDIT-2026-08-11.md](docs/AUDIT-2026-08-11.md)

## License

MIT — see [LICENSE](LICENSE). Maintained by GreyOK00.