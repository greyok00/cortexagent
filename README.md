<div align="center">
  <img src="assets/cortexagent-banner.png" alt="CortexAgent"/>
</div>

# CortexAgent

<div align="center">

![Status](https://img.shields.io/badge/status-active-2ea44f)
![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)
![Platform](https://img.shields.io/badge/platform-Linux-x86_64-informational)
![License](https://img.shields.io/badge/license-Apache--2.0-black)
![Tests](https://img.shields.io/badge/tests-pytest%20%2B%20smoke-2ea44f)

</div>

<br/>

CortexAgent is a local-first agent harness. It runs a ReAct-style loop over a model server you own, executes one tool call at a time, and feeds results back until the task is done. Two model lanes are supported: a llama.cpp lane that boots `llama-server` with your GGUF model on your own GPU, and a provider lane that points at any OpenAI-compatible endpoint over HTTP. Persistent memory, context compression, and web research attach as MCP servers rather than in-process dependencies.

The harness itself performs no telemetry and connects nowhere. Three optional lanes reach the network on purpose: web research (keyless search plus page scraping), model providers you configure, and the alert senders, which stay inert unless you register a helper script yourself.

## What ships

| Component | What it does | Where |
|---|---|---|
| Reasoning loop | ReAct-style agent: the model answers or calls one tool, the harness executes and returns the result | `engine/`, `lib/react_loop.py` |
| Daemon | Persistent control-socket daemon: sessions, prompt queue, status, schedulers | `lib/daemon.py`, `lib/control.py` |
| Overledger | Health ticker that watches lanes, memory, and services and reports on the status line | `lib/overseer.py` |
| Memory | Append-only JSONL store with hot, warm, and cold tiers plus a stdio MCP server for read, write, search, and stats | `memory/` |
| Doctor | Detects configuration drift and repairs it; merges managed keys only, never deletes servers it does not own | `lib/doctor.py` |
| Browser lane | Optional patchright-over-CDP browser MCP for pages that need a real render | `lib/patchright_chrome_mcp.py` |
| Research lane | Keyless web-research MCP (greysearch) plus a curated-site registry server | `research/`, external `greysearch` checkout |
| Fetch lane | HTTP GET with Range/206 and checksum honesty, streamed writes, and a per-action timeout map | `actions/` |

## Requirements

- Linux x86-64
- Python 3.11 or newer
- A llama.cpp build with `llama-server` for the local model lane (optional)
- `pip install pytest` to run the test suite

## Install

```bash
git clone https://github.com/greyok00/cortexagent
cd cortexagent
pip install .
./install.sh
```

The install script is re-runnable and non-destructive: it renders `mcp.json` and `settings.json` from the templates, creates the memory and profile directories, links the `cortexagent` command into `~/.local/bin`, and installs the systemd user units. It never patches binaries and never touches anything outside the user prefix.

The repository ships pure readable Python. No compiled extensions are built, packaged, or required.

## Use

```bash
cortexagent daemon start        # boot the persistent backend (model, memory, control socket)
cortexagent                     # interactive session
```

<table>
<tr><th>Command</th><th>What it does</th></tr>
<tr><td><code>cortexagent run [task]</code></td><td>run the agent non-interactively</td></tr>
<tr><td><code>cortexagent daemon {start&#124;stop&#124;status&#124;run}</code></td><td>lifecycle of the persistent backend</td></tr>
<tr><td><code>cortexagent status</code></td><td>current daemon, sessions, and lane state</td></tr>
<tr><td><code>cortexagent queue {list&#124;clear&#124;done&#124;drop&#124;context}</code></td><td>manage the prompt queue for unattended runs</td></tr>
<tr><td><code>cortexagent doctor [--dry-run] [--fix] [--json]</code></td><td>check-only by default; <code>--fix</code> repairs</td></tr>
<tr><td><code>cortexagent install</code></td><td>OS-aware install (systemd services)</td></tr>
</table>

Example:

```bash
cortexagent run "download https://example.com/report.pdf, summarize it, save the summary to notes/"
```

## MCP integrations

External capabilities attach as MCP servers through `config/mcp.json`. The `cortexagent` memory server ships in this repository; everything else is a separate checkout or package, auto-enabled when present and opt-out through environment variables.

| Server | Enabled when | Opt-out |
|---|---|---|
| `cortexagent` (memory MCP) | always | n/a |
| `greysearch` (keyless web research) | checkout found at `CORTEXAGENT_GREYSEARCH_MCP` (default `~/greysearch`) | `CORTEXAGENT_GREYSEARCH=0` |
| `slimtoken` (context compression) | package importable | `CORTEXAGENT_SLIMTOKEN=0` |
| `patchright` (browser control) | `CORTEXAGENT_BROWSER_MCP_ENABLED=1` | leave unset |
| `firecrawl` (scrape proxy) | `CORTEXAGENT_FIRECRAWL_ENABLED=1` | leave unset |

The greysearch ladder needs no API keys: a local SearXNG instance on `127.0.0.1:8888` first, then public SearXNG instances, then keyless direct lanes. If `FIRECRAWL_API_KEY` is set, the scrape lane adds it as a fallback. `doctor` reports missing targets without deleting anything.

## Doctor

```bash
cortexagent doctor --dry-run    # report only, zero writes
cortexagent doctor --fix        # repair drift (backs up before overwriting, idempotent)
cortexagent doctor --json       # machine-readable
```

Repairs merge managed keys into your existing `mcp.json` and never touch servers they do not manage. Entries from the launcher or added by hand survive every repair run.

## Configure

Environment variables or `~/.cortexagent/cortexagent.conf`. The common ones:

| Variable | Default | Controls |
|---|---|---|
| `CORTEXAGENT_MODEL` | conf `model_path` | Path to the local GGUF model file |
| `CORTEXAGENT_LLAMA_DIR` | `~/llama.cpp/build` | Where `llama-server` lives |
| `CORTEXAGENT_LOCAL_PORT` | `11599` | Port the local model server binds on 127.0.0.1 |
| `CORTEXAGENT_CTX` | auto-negotiated | Context window, stepped down until the model boots clean |
| `CORTEXAGENT_MCP_CONFIG` | `~/.cortexagent-config/mcp.json` | Which MCP servers are attached |
| `CORTEXAGENT_STATE_DIR` | `~/.cortexagent` | Daemon state, workflow state, memory |
| `CORTEXAGENT_GREYSEARCH` | `1` | Set `0` to keep the greysearch server unregistered |
| `CORTEXAGENT_SLIMTOKEN` | `1` | Set `0` to keep the slimtoken server unregistered |

Sampling and VRAM knobs (`CORTEXAGENT_NGL`, `CORTEXAGENT_NP`, `CORTEXAGENT_FA`, `CORTEXAGENT_CTK`, `CORTEXAGENT_CTV`, temperature and top-p variables) have working defaults and only matter for specific hardware.

## Test

```bash
python3 -m pytest tests/ -q          # unit and regression suite
python3 tests/run_smoke.py           # full smoke: imports every module, exercises the loop and memory
```

The smoke suite imports every shipped module, exercises the reasoning loop and memory lanes against isolated test directories, and scans the tree for personal paths.

## Credits

- [pi](https://github.com/badlogic/pi-mono) by Mario Zechner (pi.dev) forms the basis of parts of this codebase. Its MIT notice lives in [LICENSE](LICENSE).
- [slimtoken](https://github.com/greyok00/slimtoken) provides optional context compression as an external MCP server.
- The research lane builds on the external [greysearch](https://github.com/greyok00/greysearch) checkout.

## License

Apache-2.0. See [LICENSE](LICENSE). The [pi](https://github.com/badlogic/pi-mono) attribution notice lives at the end of [LICENSE](LICENSE).
