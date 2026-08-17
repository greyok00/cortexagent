# CortexAgent

**A local coding-agent runtime with a small, complete toolchain — two llama.cpp models,
a token-saving proxy, an always-on overseer, and three UIs. No cloud, no API key, no telemetry.**

```
╭─ RUNTIME ────────────╮ ╭─ SLIMTOKEN ─────────╮ ╭─ MEMORY ─────────────╮
│ ctx 2.0% · 3.1k/156k │ │ saved 18% · 2.7k    │ │ 30 groups · 29 active │
│ in —/s · out 47.6/s  │ │ last 15k → 12k      │ │ workflow · error fix  │
│ ● model ready        │ │ balanced            │ │ press m for details   │
╰──────────────────────╯ ╰─────────────────────╯ ╰───────────────────────╯
```

The strip above is the live 3-panel status bar that sits under the chat input in the TUI.
It shows context usage, token savings, memory state, and the current work phase —
always-on, width-adaptive, and color-paired so nothing relies on color alone.

---

## What it is

CortexAgent runs a **single large model + a single small model**, both served locally by
`llama-server`. The big model answers your prompts. The small model is the **overseer**:
an always-on sidecar that classifies intents, schedules tasks, watches memory, and
catches failures. Between you and the big model sits **slimtoken** — a token-minifying
chokepoint proxy that strips grammar fields, dedupes messages, and compresses tool
schemas before the request ever reaches the model.

| Layer | What it does | File |
|---|---|---|
| **Daemon** | Owns big model + proxy lifecycle, exposes control socket | `lib/daemon.py` |
| **Overseer** | Owns tiny model, queue, scheduler, memory writes | `lib/overseer.py` |
| **Proxy** | Minifies tokens, tracks `/metrics`, swaps big↔fallback | `lib/grammar_proxy.py` |
| **WebUI** | 3D dashboard + chat at `http://127.0.0.1:8090` | `lib/webui.py` |
| **TUI** | Terminal chat at `python3 lib/tui.py` | `lib/tui.py` |
| **Tray** | System tray icon + popout overseer dashboard | `lib/tray.py` + `lib/overseer_dashboard/` |

Everything binds to `127.0.0.1`. Nothing leaves your machine.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/greyok00/cortexagent ~/cortexagent
cd ~/cortexagent

# 2. Configure (one-time)
cp config/settings.toml.example ~/.cortexagent/cortexagent.conf
# edit to point at your GGUF files; see "Configuration" below

# 3. Start the runtime
python3 lib/daemon.py start      # loads big model + starts proxy
python3 lib/overseer.py start    # starts tiny + overseer

# 4. Pick a UI
python3 lib/tui.py               # terminal chat (recommended)
# — or —
python3 lib/webui.py start       # then open http://127.0.0.1:8090
# — or —
python3 lib/tray.py start        # system tray icon

# 5. Chat
python3 lib/tui.py
> write a python function that returns the fibonacci sequence

# 6. Inspect
python3 lib/overseer.py status   # live state
python3 lib/chain_diagnostic.py  # full chain dump (routing → framing → LLM → output)
```

Stop:

```bash
python3 lib/overseer.py stop
python3 lib/daemon.py stop
```

---

## Configuration

State lives under `~/.cortexagent/`. Config is `~/.cortexagent/cortexagent.conf`
(TOML), overridable by environment variables:

| Env var | Purpose | Default |
|---|---|---|
| `CORTEXAGENT_STATE_DIR` | State directory | `~/.cortexagent` |
| `CORTEXAGENT_BIG_MODEL` | Big GGUF path (overrides conf) | unset |
| `CORTEXAGENT_TINY_MODEL` | Tiny GGUF path | unset |
| `CORTEXAGENT_FALLBACK_MODEL` | Fallback GGUF (VRAM-aware) | unset |
| `CORTEXAGENT_MINIFY` | Enable slimtoken proxy | `1` |
| `CORTEXAGENT_MAX_TOOLS` | Tiny model tool surface budget | `16` |
| `CORTEXAGENT_AUTHOR` | Branding tag for prompts | the maintainer |

State files (all written atomically):

```
~/.cortexagent/
├── overseer_state.json          # live state
├── overseer_queue.json          # task queue
├── overseer_schedule.json       # cron entries
├── token_tracker.json           # per-request token counts
├── minify_stats.json            # slimtoken savings
├── observability/<trace_id>/    # one dir per trace
└── stt_daemon.log               # STT sidecar (optional)
```

---

## Pair it with

CortexAgent is the runtime; the engine it leans on lives in two sibling repos.
They are independent — drop-in replaceable — but designed to work together.

| Component | Role | Repo |
|---|---|---|
| **slimtoken** | The token-minification proxy (`lib/grammar_proxy.py` is a thin adapter) | `<repo>/slimtoken` |
| **cortexllm** | The memory layer + scheduler the overseer writes to | `<repo>/cortexllm` |

If you only want CortexAgent without the proxy, set `CORTEXAGENT_MINIFY=0`. If you
don't need the memory layer, the overseer will simply not write to it.

---

## Architecture in 30 seconds

```
                         ┌───────────────────────────────┐
                         │  TUI · WebUI · Tray (any one) │
                         └──────────────┬────────────────┘
                                        │
                            ┌───────────▼───────────┐
                            │   grammar_proxy (:81) │ ←─── minify + /metrics
                            └───────────┬───────────┘
                                        │
                            ┌───────────▼───────────┐
                            │  big model (:8080)     │ ←─── Qwen3.6-35B UD-IQ3_S
                            └───────────┬───────────┘
                                        │
       ┌────────────────────────────────▼────────────────────────────┐
       │                                                              │
┌──────▼──────┐  ┌───────────┐  ┌──────────┐  ┌───────────────────────┐
│ overseer    │  │ tiny LLM  │  │ queue +  │  │ memory (cortexllm)    │
│ (:8082)     │  │ (:8082)   │  │ schedule │  │ hot NDJSON + cold JSON│
└─────────────┘  └───────────┘  └──────────┘  └───────────────────────┘
```

Each box runs as its own process. The proxy is the only thing on the hot path
between you and the big model.

For the full architecture (every span, every state file, every subsystem), see
[`ARCHITECTURE.md`](ARCHITECTURE.md). For the design decisions behind each piece,
see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Development

### Test gates

```bash
# Pure unit tests (no live servers needed)
python3 -m pytest tests/test_tui_status.py         # 27 tests, 0.05s
python3 -m pytest tests/test_response_model.py     # response parsing/sanitize
python3 -m pytest tests/test_overseer_dashboard.py # dashboard widgets

# Full smoke gate (some need live ports)
python3 tests/run_smoke.py
```

### Layout

```
lib/
├── daemon.py                # big model lifecycle
├── overseer.py              # tiny model + queue + scheduler
├── grammar_proxy.py         # token minify + /metrics
├── webui.py                 # :8090 dashboard + chat
├── tui.py                   # terminal UI (Textual 8.x)
├── tui_status.py            # 3-panel status strip (pure render layer)
├── processing_animation.py  # 7-stage "CORTEX ACTIVE" animation
├── tray.py                  # system tray icon
├── overseer_dashboard/      # tk-based popout dashboard
├── session_bridge.py        # shared-file bridge (TUI ↔ webui ↔ overseer)
├── observability.py         # trace spans + metrics + evals
├── response_model.py        # typed response blocks + sanitization
├── beautify.py              # tables / charts / diagrams in terminal output
├── tool_registry.py         # tiny-model tool surface
├── stt.py                   # faster-whisper speech-to-text sidecar
└── ... (40+ modules, all stdlib where possible)
```

### Repo conventions

- **One module per concern.** If a file is over ~600 lines it probably wants splitting.
- **Stdlib-only by default.** Optional dependencies are clearly marked.
- **Atomic writes everywhere.** `O_APPEND` for hot memory, `tmp+rename` for everything else.
- **Sanitize the boundary.** Anything that crosses a process boundary passes through
  `lib/response_model.sanitize_terminal` first.
- **No PII in commits.** See the pre-commit grep in `tests/run_smoke.py` (`PII_PATTERNS`).

---

## Threat model

| Trust | Examples |
|---|---|
| **Trusted** | The user, the local filesystem, the daemon, the overseer |
| **Untrusted** | File contents, web pages, emails, MCP outputs, browser content — any content the model ingests can carry adversarial instructions |

Defenses:

1. **Grammar proxy** strips grammar fields and runs slimtoken minification (catches most tool-injection payloads by reducing the surface the model sees).
2. **Injection guardrails** mark tool outputs with `tool_output` tags and surface them as untrusted.
3. **Output sanitization** — terminal escapes are stripped before any cell lands in the chat scrollback.
4. **Per-origin session cursors** so the TUI and the webui can't stomp each other's history.
5. **Localhost-only bindings** — nothing on `0.0.0.0`, no cloud fallbacks.

---

## License

MIT.