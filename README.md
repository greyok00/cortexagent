# CortexAgent

**A private, local AI coding agent that runs entirely on your machine — no cloud, no API key, no data leaves your computer.**

CortexAgent combines a local llama.cpp model with a clean terminal chat interface, automatic memory, and a live view of every step of your request — from prompt to response.

---

## Quick start

```bash
# 1. Clone and install
git clone <repo>/cortexagent
cd cortexagent
./install.sh            # sets up config, memory, and the `cortexagent` command

# 2. Launch the terminal TUI
cortexagent
```

`cortexagent` opens the terminal chat interface. Your first prompt loads the local model and you are talking to your own private agent.

> Everything binds to `127.0.0.1`. Nothing leaves your machine.

---

## Core features

- **Local-by-default model** — Qwen3.6-35B MoE runs on your GPU via llama.cpp. No cloud, no account, no API key.
- **One terminal interface** — a single clean TUI (`cortex`) for chatting and reviewing output. No other terminal UIs.
- **Live processing animation** — watch your request move through each stage: context prep → SlimToken compression → sending → generating → done.
- **Automatic memory** — remembers across sessions (hot working memory + curated cold knowledge), so you do not re-explain yourself.
- **Token compression (SlimToken)** — your context is minified before it reaches the model, so you fit more into the context window.
- **Speech-to-text (STT)** — dictate instead of type, using a small popout control with the mouse and your voice only.
- **Overseer routing** — a dedicated small model plans and routes your request to the big model.
- **Domain memory** — recalled context from your own notes is injected automatically.

---

## Browser automation (generic, any site)

The agent can drive your real browser (Brave on `127.0.0.1:9222`) through 10 generic tools registered in the tool registry:

| Tool | What it does |
|---|---|
| `brave_status` | CDP reachability + open tab count |
| `brave_tabs` | List open tabs (index, title, url) |
| `brave_navigate` | Navigate a tab to a URL |
| `brave_fetch` | Fetch page text via the browser (good for JS-heavy sites) |
| `brave_click` | Click by CSS selector or accessible text |
| `brave_type` | Type into an element; optionally press Enter |
| `brave_evaluate` | Evaluate JS and return the result |
| `brave_snapshot` | Return the accessibility tree |
| `brave_fill_send` | Fill a shadow-DOM controlled component and press Enter |
| `brave_health` | Engine health: calls, reconnects, retries, failures, last-call latency |

All tools are site-agnostic — no embedded URLs, no site markers, no canned messages in the engine. Site-specific automation lives in standalone scripts under `scripts/`.

The engine itself (`lib/browser_control.py`) is hardened:

- per-tab websocket pool with one-shot retry on transient errors
- per-target locks so different tabs run in parallel; same tab serializes
- 150 ms TTL cache on the tab list so bursts don't re-hit `/json`
- atexit cleanup so process death doesn't leak sockets on the browser
- read-only `health()` + `bin/cortexagent-browser-health` for observability

It **never** restarts Brave, **never** touches the CDP port, **never** closes your open tabs.

```bash
bin/cortexagent-browser-health           # human summary
bin/cortexagent-browser-health --json    # machine-readable
bin/cortexagent-browser-health --watch 2 # live ticker (Ctrl-C to stop)
```

---

## Speech-to-text popout

Dictate to CortexAgent with a floating control window you use **with the mouse and your voice only** — no keyboard required.

- Open it from the system tray under **STT Controls**.
- Two big, easy-to-click buttons: **Toggle STT** (start/stop voice input) and **Enter** (submit what you said).
- Your voice is transcribed locally (faster-whisper) and appears in the chat box.

---

## How it works (at a glance)

| Piece | What it does |
|-------|--------------|
| **Terminal TUI** (`cortex`) | The one interface you talk to |
| **Daemon** | Owns the big model + proxy lifecycle |
| **Overseer** | Small model that plans, routes, and schedules |
| **Proxy** | Compresses tokens (SlimToken) + routes traffic |
| **Memory** | Hot/cold recall across sessions |
| **STT** | Voice dictation with a mouse-only popout |

---

## Requirements

- Linux with an NVIDIA GPU (16 GB+ VRAM recommended)
- Python 3.10+
- A GGUF model file (see `config/MODELS.md`)

---

## License

MIT — see `LICENSE`.
