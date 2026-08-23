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

## CortexAgent Console

The **CortexAgent Console** is a compact floating window that sits next to your chat — it gives you a graphical surface for chat, the active task list, and your open browser tabs, all without leaving the agent. The console binds to `127.0.0.1` and never reaches the network.

![CortexAgent Console](docs/img/cortexagent-console.png)

### What it gives you

| Surface | What you see / do there |
|---|---|
| **Chat stream** | The same conversation as the TUI, with the latest user prompt + assistant reply rendered inline. Tool calls collapse to one-line indicators while they run and expand on demand. |
| **Active task panel** | The primary in-flight task (subject + active form spinner) is always shown at the top of the left rail so you can see what the agent is doing without opening the TUI. |
| **Browser tabs strip** | A live list of your open Brave tabs, populated from the CDP endpoint on `127.0.0.1:9222`. Click a tab to switch to it in Brave — activation goes through Chromium's `Page.bringToFront`, not title guessing, so it picks the right tab even when many share a prefix. |
| **Hotkey footer** | One-line key reminders (interrupt, clear/exit, commands, bash, expand) styled like real keys. |
| **Speech-to-text buttons** | The same Toggle STT / Enter buttons from the tray popout, attached directly to the console. |

### Where it runs

```
bin/cortexagent          # starts both the agent (TUI) AND the console tray item
lib/browser_console.py   # the console itself (Tkinter + WebSocket to CDP)
```

The console is launched as a system-tray entry; clicking it raises the window. The window starts collapsed (thin strip) and expands on demand — the chevron was removed in 2026-08-21 to avoid focus-stealing breaks.

### How tabs work

- Read from `http://127.0.0.1:9222/json` (Brave must have been started with `--remote-debugging-port=9222`).
- Activation uses `Page.bringToFront` over each tab's `webSocketDebuggerUrl` — this is the canonical Chromium-side focus path and is the only reliable way to choose a tab when several are open.
- If CDP fails, the console falls back to X11 (`xdotool`) title-matching. The Brave window is raised without `--sync` to avoid hangs.

### Localhost binding (HARD)

The console, the TUI, and the pipeline server all bind to `127.0.0.1` only. They never listen on `0.0.0.0`. This is enforced in code and checked by `bin/verify`.

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

---

## Accessibility

> **Honest a11y statement.** Read this before depending on any one surface.

| Surface | Accessibility status | Notes |
|---|---|---|
| **TUI** (`cortex`) | ✅ Keyboard-only navigation. Honors `NO_COLOR`, `TERM=dumb`, `--unicode` flag, OSC window titles. Glyph + label pairs every status. | Best text-based experience. Voice control / per-widget screen-reader hints are not implemented. |
| **Web / pipeline** (`http://127.0.0.1:8090`) | ⚠️ Visualization-only; not a chat surface. Focus styles on interactive elements. |
| **Web / security** (`http://127.0.0.1:8093`) | ⚠️ Skeleton CSS + ARIA added (skip-link, focus-visible, `<main>` landmark). axe-core in CI not yet configured. No formal NVDA/VoiceOver pass yet. |
| **Tkinter desktop console** | ❌ **Not accessible to screen readers on Linux** without [Tka11y](https://pypi.org/project/Tka11y/) (last released 2009). Tk bug [0e294d96](https://core.tcl-lang.org/tk/info/0e294d9604) means widgets don't expose to AT-SPI. **The TUI and web surfaces are the primary a11y targets.** The Tk console is an ergonomic convenience for mouse users, not an a11y investment. |

**Conventions we follow** (see `docs/ux/DESIGN-PRINCIPLES.md` for full):

- WCAG 2.2 AA contrast (4.5:1 text, 3:1 UI components).
- Slash command vocabulary is identical across all surfaces.
- Streaming output throttled for screen readers (≤1 announcement/sec).
- Tool calls are never silent — always announced.
- Keyboard-first; handedness is a secondary concern.
- Color is never the sole signal — always paired with glyph + label.

**What we do not yet do:**

- axe-core is not yet wired into CI on web changes.
- No formal NVDA + VoiceOver pass before releases.
- No scheduled sessions with disabled users (per the §2.7 plan in the design doc).
