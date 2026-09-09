# CortexAgent

> **Your private, local AI coding agent — no cloud, no API key, nothing uploaded.**

CortexAgent is an AI assistant that runs entirely on **your** computer. It helps you write and fix software, automate repetitive work in your web browser, and answer questions about your own files — all without sending anything to an outside service.

**What that means for you:**

- **Private by design.** Your code, files, and conversations never leave your machine.
- **No monthly fees.** There is no cloud subscription and no API key. It uses a model stored on your own computer.
- **Always yours.** Nothing is monitored, logged remotely, or shared. If the internet goes down, it keeps working.

---

## It verifies itself

CortexAgent ships with its own automated self-check, and a version is only released once that check passes. The check runs through four layers — file integrity, documentation accuracy, an in-process test harness, and a feature-catalog sweep — so the version you install is the version that was tested. You can run it yourself any time:

```bash
bin/verify
```

---

## Install

CortexAgent runs on Linux. An NVIDIA graphics card with roughly 16 GB of memory is recommended for best speed (it works on CPU only, just slower).

```bash
git clone https://github.com/greyok00/cortexagent
cd cortexagent
./install.sh      # sets up configuration and the `cortexagent` command
cortexagent       # first run walks you through starting your local model
```

`install.sh` is safe to re-run — it never overwrites your existing settings.

---

## Start in 60 seconds

**Code with it.** Open the assistant and give it a task:

```bash
cortexagent
# → "add a --dry-run flag to bin/publish and test it"
```

**One shot, no session:**

```bash
cortexagent -p "find why the daemon is unresponsive and fix it"
```

**Automate your browser.** Point it at your running Chrome and just ask — to fetch a page, fill in a form, or collect data. It uses ten generic, site-neutral commands (`chrome_status`, `chrome_tabs`, `chrome_navigate`, `chrome_fetch`, `chrome_click`, `chrome_type`, `chrome_evaluate`, `chrome_snapshot`, `chrome_fill_send`, `chrome_health`) and never restarts the browser or closes your tabs.

**Or dictate.** A mouse-only speech-to-text popup lets you talk instead of type. Your audio never leaves the machine.

---

## Features

- **A single command-line assistant.** Everything happens in one terminal window — type a task, watch it work, and read what it changed.
- **Remembers between sessions.** Past work is saved locally and resurfaces when it matters, so you don't re-explain yourself.
- **Fits more in one conversation.** Long discussions are compressed automatically, so more context stays available without you having to trim it.
- **Built-in scheduling.** A background coordinator plans and sequences work on your behalf.
- **Frees up resources when idle.** Release the model's memory in one command to make room for other tools, then bring it back.
- **Self-repair.** A built-in diagnostic detects and fixes configuration drift.

### The command line

![CortexAgent CLI](assets/cortexagent-cli.png)

Everything runs in a single terminal session. Type a task, watch the assistant work through your files and browser, and read what it changes — no window-switching, no separate panels.

---

## When it's not for you

A tool that tests itself should be honest about its limits:

- **Not a frontier research system.** The local model is fast and capable, but for a genuinely novel, never-before-seen puzzle a hosted model is sometimes stronger. Nothing here stops you from exporting the conversation and running it elsewhere.
- **It wants memory.** The recommended setup needs a graphics card with roughly 16 GB. Raising the model's context window beyond the shipped defaults can run out of memory — the shipped settings are the ones that were tested.
- **Text-first.** The assistant works with text — it writes and fixes code, reads your files, and drives your browser — but it doesn't interpret images itself.
- **Single user, Linux only.** One assistant on one machine — not a multi-user team platform.

---

## How it works

| Component | Address | Role |
|---|---|---|
| Model | `127.0.0.1:8080` | the assistant's "brain" — a large language model stored locally |
| Context manager | `127.0.0.1:8081` | compresses conversation so more fits at once |
| Browser (Chrome) | `127.0.0.1:9224` | the browser session the assistant can read and control |

Every component binds to `127.0.0.1` — the loopback address used only by your own machine — and is never exposed to the wider network.

> 🔒 **Local only.** These addresses work only on your computer. Do not forward or expose them to the network.

---

## Command line

```bash
cortexagent                     # interactive session
cortexagent -p "task"           # one-shot task
cortexagent daemon start        # persistent backend
cortexagent models status       # model / context state
cortexagent models unload big   # free memory for other work
cortexagent models load big     # bring the model back
cortexagent doctor              # detect + fix config drift
cortexagent status              # is everything up?
```

---

## Security

- **Local only.** All components bind to `127.0.0.1` and are verified never to expose a network port.
- **No data leaves your machine.** No API keys are stored, no telemetry is collected, and nothing is uploaded. The only network activity in the whole system is yours, if you ever choose to connect to a hosted provider.
- **Local-first by construction.** Your memory, browser state, and voice all live on your computer.

---

## License

MIT — see [LICENSE](LICENSE).
