# About CortexAgent

**Local-first coding agent. No cloud. No API key. No telemetry.**

CortexAgent runs a 35B-parameter model on your own GPU and gives you a CLI, a
3D webui, and a system tray that all share the same session. The big model is
the agent — there is no fallback swap path. If it can't load, the port goes
down. This is a feature, not a limitation: you should know, with certainty,
what's answering your prompts.

> Maintained by [GreyOK00](https://github.com/greyok00).

## Why it exists

Most "AI coding assistants" today are SaaS wrappers. CortexAgent is the
opposite:

- **Your code never leaves the box.** Repo state, conversation history,
  embeddings, and memory all live under `~/.cortexagent/`. Airgap-friendly.
- **No API bills.** The 35B MoE fits in 16 GB at IQ3_S. Prompt as fast as you
  can think.
- **Two systemd services survive logout.** Close the CLI, the daemon and the
  overseer keep running. Memory distills. Cron tasks fire.
- **Memory with no caps.** Every prompt appends forever. The COLD tier is
  unlimited.
- **The grammar proxy is a chokepoint.** Every chat request flows through
  `:8081`, where `slimtoken` minifies the prompt before it reaches the model.
  You save VRAM, you save latency, you don't break tool calls.
- **In-process diffusion.** SDXL, SD1.5, and LTX-Video on the same GPU. No
  second port, no second process.

## What you get

| | |
|---|---|
| **One big model** | Qwen3.6-35B-A3B on `:8080`, 128K context, ~13.6 GB VRAM |
| **One tiny model** | LFM2.5-1.2B on `:8082`, overseer-only minifier |
| **Grammar proxy** | `:8081`, slimtoken chokepoint + tool-call routing |
| **Daemon** | Owns `:8080` / `:8081`, session lifecycle, idle-unload |
| **Overseer** | Always-on systemd, scheduler, warm→cold distillation |
| **CLI** | Plain by default, box-drawn visuals, R1–R7 rules |
| **Webui** | 3D chat on `:8090`, shared session with CLI |
| **Tray** | Wolf-head system-tray icon + popout dashboard |
| **Diffusion** | In-process SDXL / SD1.5 / LTX-Video, 4K output |
| **Memory** | HOT (300) + WARM (2000) + COLD (unlimited), stdlib SQLite |

![workflow](../cortexagent/assets/workflow.svg)

## How it differs from a hosted assistant

| | Hosted (Claude / GPT) | CortexAgent |
|---|---|---|
| Where the model runs | Their cluster | Your GPU |
| Where the code goes | Their logs | `~/.cortexagent/` |
| Rate limits | Yes | No |
| API key | Yes | No |
| Privacy | Their terms | Yours |
| Token cost | Per million | Free (electricity) |
| Fallback to other model | Often | **No. By design.** |
| Session persists across logout | Depends | Yes (overseer) |
| Can run offline | No | Yes |
| Can be packaged | No | Yes (systemd unit, deb/rpm later) |

## How it relates to cortexllm and slimtoken

CortexAgent **consumes** two upstream packages rather than forking them:

- **[cortexllm](https://github.com/greyok00/cortexllm)** — atomic JSONL
  writes, memory tier helpers, token counters, task DAG with conflict
  detection, scheduler, integrity chain. Nine modules, five MCP tools, MIT
  licensed. CortexAgent uses three drop-ins today (`atomic`, `stats`, `plan`)
  via an adapter in `lib/cortexllm_adapter.py`. Local-only changes side-port
  back to the package.
- **[slimtoken](https://github.com/greyok00/slimtoken)** — pair-safe, fence-
  aware token minifier. MCP server, async proxy, Agent Skill, CLI. MIT
  licensed. CortexAgent imports it directly as a hard runtime dep — the
  grammar proxy on `:8081` is a slimtoken-aware async proxy that runs on
  every chat request.

Both are real packages on PyPI. CortexAgent is one of their consumers. We
ship drop-in patches back upstream; we don't fork and fragment.

## Is this for you?

| You'll like it if… | You'll hate it if… |
|---|---|
| You have an NVIDIA GPU with 16+ GB VRAM | You wanted a hosted SaaS |
| You want your code to stay on disk | You want zero setup |
| You're tired of API bills | You can't compile llama.cpp |
| You need scheduled background tasks | You need a fallback swap path |
| You want a CLI + tray + webui that share state | You only want a single UI surface |
| You're OK with the big model being the only model | You want a multi-model ensemble |

## Quick start

```bash
git clone https://github.com/greyok00/cortexagent ~/cortexagent
cd ~/cortexagent
bash install.sh
cortexagent                     # interactive CLI
```

Open `http://127.0.0.1:8090/` for the 3D webui.

Full docs in [README.md](../cortexagent/README.md) and
[docs/ARCHITECTURE.md](../cortexagent/docs/ARCHITECTURE.md).

---

**Maintainer:** GreyOK00 · **License:** MIT · **Repo:**
[github.com/greyok00/cortexagent](https://github.com/greyok00/cortexagent)