# About CortexAgent

CortexAgent is a runtime for a self-hosted coding agent. It runs two
local models on a single GPU: a 35-billion-parameter mixture-of-experts
model for reasoning, and a small orchestrator for scheduling, memory
distillation, and diffusion orchestration. Conversation state is
persisted to a local SQLite database. All traffic is over `127.0.0.1`.

## Components

| Component | Address | Role |
|---|---|---|
| Reasoning model | `:8080` | The agent. |
| Orchestrator | `:8082` | Scheduling, memory, diffusion. |
| Grammar proxy | `:8081` | Middleware. |
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

## Upstream libraries

- [`cortexllm`](https://github.com/greyok00/cortexllm) — atomic writes,
  memory tiers, task DAG, scheduler, integrity chain. MIT.
- [`slimtoken`](https://github.com/greyok00/slimtoken) — pair-safe,
  fence-aware token minimisation. MIT.

Both publish to PyPI. CortexAgent is a downstream consumer.

## Quick start

```bash
git clone https://github.com/greyok00/cortexagent ~/cortexagent
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
**Repository:** [github.com/greyok00/cortexagent](https://github.com/greyok00/cortexagent)