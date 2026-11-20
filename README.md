<div align="center">

<img src="assets/cortexagent-banner.png" alt="CortexAgent">

# CortexAgent

**A local-first agent harness for the model you already run.**

A ReAct-style loop over your own model server, one tool call at a time, with persistent memory, offline retrieval, web research and a terminal UI attached as MCP lanes rather than bolted into the core.

[![Version](https://img.shields.io/badge/version-0.11.0-2f6f5e)](pyproject.toml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Linux%20x86--64-informational)](#requirements)
[![License](https://img.shields.io/badge/license-Apache--2.0-black)](LICENSE)

[Overview](#overview) · [Screenshots](#screenshots) · [Quick start](#quick-start) · [MCP](#mcp-integrations) · [Doctor](#doctor) · [License](#license)

</div>

---

## Overview

CortexAgent runs a ReAct-style loop over a model server you own. The model
answers or calls one tool; the harness executes it and feeds the result back
until the task is done. Two model lanes are supported: a llama.cpp lane that
boots `llama-server` with your GGUF model on your own GPU, and a provider lane
that points at any OpenAI-compatible endpoint over HTTP.

Persistent memory, context compression, offline RAG and web research attach as
MCP servers rather than in-process dependencies. The repository also ships a
full terminal UI under `tui/` (a pi-based interactive coding agent with subagent
support) and a bundle of 14 superpowers skills under `skills/` that the
installer drops into `~/.agents/skills/`.

The harness itself performs no telemetry and connects nowhere. Three optional
lanes reach the network on purpose: web research, model providers you
configure, and alert senders, which stay inert unless you register a helper
script yourself.

## Screenshots

| Interactive CLI | Doctor |
| :---: | :---: |
| ![CortexAgent CLI](assets/cortexagent-cli.png) | ![Doctor output](assets/cortexagent-doctor-new.png) |

![Verification output](assets/cortexagent-verify.png)

## What ships

| Component | What it does | Where |
|---|---|---|
| Reasoning loop | ReAct-style agent: the model answers or calls one tool; the harness executes and returns the result | `engine/`, `lib/react_loop.py` |
| Daemon | Persistent control-socket daemon: sessions, prompt queue, status, schedulers | `lib/daemon.py`, `lib/control.py` |
| Overledger | Health ticker watching lanes, memory and services on the status line | `lib/overseer.py` |
| Memory | Append-only JSONL store with hot, warm and cold tiers, plus a stdio MCP server for read, write, search and stats | `memory/` |
| Doctor | Detects configuration drift and repairs it; merges managed keys only and never deletes servers it does not own | `lib/doctor.py` |
| Browser lane | Optional patchright-over-CDP browser MCP for pages that need a real render | `lib/patchright_chrome_mcp.py` |
| Research lane | Keyless web-research MCP plus a curated-site registry server | `research/`, external checkout |
| Offline RAG | Bundled kbserver MCP with confidence-banded search, verbatim/web/PDF ingest and `kb_learn_topic` | `mcp/kbserver/` |
| Terminal UI | pi-based interactive TUI with subagents, sessions, themes, message rendering and benchmarks | `tui/` |
| Skills bundle | 14 skills (brainstorming, test-driven development, systematic debugging, writing plans and more) | `skills/` |
| Fetch lane | HTTP GET with Range/206 and checksum honesty, streamed writes and per-action timeouts | `actions/` |

## Requirements

- Linux x86-64.
- Python 3.11 or newer.
- A llama.cpp build with `llama-server` for the local model lane (optional).
- `pip install pytest` to run the test suite.

## Quick start

```bash
git clone https://github.com/greyok00/cortexagent
cd cortexagent
pip install .
./install.sh
```

The install script is re-runnable and non-destructive. It renders `mcp.json`
and `settings.json` from templates, creates the memory and profile directories,
links the `cortexagent` command into `~/.local/bin`, installs the systemd user
units, and copies the bundled skills into `~/.agents/skills/` unless
`CORTEXAGENT_NO_SKILLS=1` is set. It never patches binaries and never touches
anything outside the user prefix.

The Python harness ships pure readable Python: no compiled extensions are
built, packaged or required. The `tui/` tree is readable TypeScript shipped as
source; two third-party vendor libraries are the only bundled minified files.

## Usage

```bash
cortexagent daemon start        # boot the persistent backend
cortexagent                     # interactive session
```

| Command | What it does |
|---|---|
| `cortexagent run [task]` | Run the agent non-interactively |
| `cortexagent daemon {start\|stop\|status\|run}` | Lifecycle of the persistent backend |
| `cortexagent status` | Current daemon, sessions and lane state |
| `cortexagent queue {list\|clear\|done\|drop\|context}` | Manage the prompt queue for unattended runs |
| `cortexagent doctor [--dry-run] [--fix] [--json]` | Check-only by default; `--fix` repairs |
| `cortexagent install` | OS-aware install (systemd services) |

Example:

```bash
cortexagent run "download https://example.com/report.pdf, summarize it, save the summary to notes/"
```

## MCP integrations

External capabilities attach as MCP servers through `config/mcp.json`. The
`cortexagent` memory server ships in this repository; everything else is a
separate checkout or package, auto-enabled when present and opt-out through
environment variables.

| Server | Enabled when | Opt-out |
|---|---|---|
| `cortexagent` (memory MCP) | always | n/a |
| `greysearch` (keyless web research) | checkout found at `CORTEXAGENT_GREYSEARCH_MCP` (default `~/greysearch`) | `CORTEXAGENT_GREYSEARCH=0` |
| `kbserver` (offline RAG / ingestion) | bundled, file present at `mcp/kbserver/kbserver.py` | `CORTEXAGENT_KBSERVER=0` |
| `slimtoken` (context compression) | package importable | `CORTEXAGENT_SLIMTOKEN=0` |
| `patchright` (browser control) | `CORTEXAGENT_BROWSER_MCP_ENABLED=1` | leave unset |
| `firecrawl` (scrape proxy) | `CORTEXAGENT_FIRECRAWL_ENABLED=1` | leave unset |

The research ladder needs no API keys: a local SearXNG instance on
`127.0.0.1:8888` first, then public SearXNG instances, then keyless direct
lanes. If `FIRECRAWL_API_KEY` is set, the scrape lane adds it as a fallback.
`kbserver` pairs with it: when a `kb_search` comes back empty,
`kb_learn_topic` runs a deep web-research pass and quality-gates every page
before ingest, so research results become a permanent local library.

## Doctor

```bash
cortexagent doctor --dry-run    # report only, zero writes
cortexagent doctor --fix        # repair drift; backs up before overwriting
cortexagent doctor --json       # machine-readable
```

Repairs merge managed keys into your existing `mcp.json` and never touch
servers they do not manage. Entries from the launcher or added by hand survive
every repair run.

## Configuration

Environment variables or `~/.cortexagent/cortexagent.conf`. The common ones:

| Variable | Default | Controls |
|---|---|---|
| `CORTEXAGENT_MODEL` | conf `model_path` | Path to the local GGUF model |
| `CORTEXAGENT_LLAMA_DIR` | `~/llama.cpp/build` | Where `llama-server` lives |
| `CORTEXAGENT_LOCAL_PORT` | `11599` | Port the local model server binds on `127.0.0.1` |
| `CORTEXAGENT_CTX` | auto-negotiated | Context window, stepped down until the model boots clean |
| `CORTEXAGENT_MCP_CONFIG` | `~/.cortexagent-config/mcp.json` | Which MCP servers are attached |
| `CORTEXAGENT_STATE_DIR` | `~/.cortexagent` | Daemon state, workflow state, memory |
| `CORTEXAGENT_GREYSEARCH` | `1` | Set `0` to keep the greysearch server unregistered |
| `CORTEXAGENT_KBSERVER` | `1` | Set `0` to keep the bundled kbserver unregistered |
| `CORTEXAGENT_NO_SKILLS` | unset | Set `1` to skip the skills install step |
| `CORTEXAGENT_SKILLS_HOME` | `~/.agents/skills` | Where the skills bundle is installed |
| `CORTEXAGENT_SLIMTOKEN` | `1` | Set `0` to keep the slimtoken server unregistered |

### Local model or cloud (Ollama)

The model slot is one URL. The slimtoken lane stays the default either way;
only the base URL and the served model name change, and an explicit
`CORTEXAGENT_LOCAL_BASE` set before launch wins over the auto-probe.

```bash
# Default: slimtoken lane in front of the local model
export CORTEXAGENT_LOCAL_BASE="http://127.0.0.1:11598/v1"

# Ollama instead (local :11434 or an Ollama cloud host)
export CORTEXAGENT_LOCAL_BASE="http://127.0.0.1:11600/v1"
export CORTEXAGENT_MODEL_NAME="glm-5.3-flash:cloud"
```

Provider prompt caching engages automatically on the cache-safe lane: only
tool-schema minification, append-only dedup and the loop guard touch the served
body, so the prefix the provider caches never changes.

## Development

```bash
python3 -m pytest tests/ -q          # unit and regression suite
python3 tests/run_smoke.py           # full smoke: every module, loop and memory
```

The smoke suite imports every shipped module, exercises the reasoning loop and
memory lanes against isolated test directories, and scans the tree for personal
paths.

## Credits

- [pi](https://github.com/badlogic/pi-mono) by Mario Zechner (pi.dev) forms the
  basis of parts of this codebase. Its MIT notice lives in [LICENSE](LICENSE).
- The bundled skills under `skills/` are adapted from the
  [superpowers](https://github.com/obra/superpowers) skill collection (MIT).

## License

Apache-2.0. See [LICENSE](LICENSE). The pi attribution notice lives at the end
of [LICENSE](LICENSE).
