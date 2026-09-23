# CortexAgent

> **Your private, local AI coding agent — no cloud required, no API key.**

CortexAgent runs entirely on your machine: a local llama.cpp model spawned and owned by the launcher, a terminal TUI plus a floating Console, automatic memory across sessions, local browser automation, message triage from your own logged-in browser, local speech-to-text, and token compression. Everything binds to `127.0.0.1`. No accounts, no telemetry. Optional cloud generation is strictly opt-in — see [Security](#security).

---

## It verifies itself

`bin/verify` is an offline gate that ships with the repo. A release only ships when it passes — and you can run it yourself any time:

| Layer | Check | Last run |
|---|---|---|
| 1 · Manifest | file-hash drift across the repo | ✅ no drift |
| 2 · Contract | doc-vs-code contract | ✅ |
| 3 · Smoke | in-process smoke harness (no live endpoints) | ✅ |
| 4 · Features | **77** feature-catalog reachability checks | ✅ ALL GREEN |

```bash
bin/verify
```

The feature catalog is generated, not maintained: `tools/build_feature_catalog.py` re-derives it from the live handlers, so the count and the checks can't drift from the code.

---

## Install

Linux. An NVIDIA GPU with ~16 GB VRAM is recommended (CPU-only works, slower).

```bash
git clone https://github.com/greyok00/cortexagent
cd cortexagent
./install.sh     # config, memory dirs, systemd units, the `cortexagent` command
cortexagent      # first run starts your local model
```

`install.sh` is re-runnable and non-destructive — existing config is backed up, never silently overwritten.

---

## Start in 60 seconds

**Code with it** — open the TUI and give it a task:

```bash
cortexagent
# → "add a --dry-run flag to bin/publish and test it"
```

**One-shot, no session:**

```bash
cortexagent -p "find why the daemon is unresponsive and fix it"
```

**Drive the browser** — open two tabs in your debugging window (chromium by default) and pin them. The agent has ten site-agnostic CDP tools — navigate, click, type, snapshot, evaluate and more — it never restarts the browser, never touches the CDP port, never closes your tabs.

**Or let it answer your messages** — it watches one configured thread plus your inbox and replies from your default browser; your logged-in tabs are the credential. OAuth is an optional alternative, never a requirement.

**Or dictate** — a mouse-only speech-to-text popup (Start/Stop + Enter). Audio never leaves the machine.

---

## Features

- **Terminal TUI + floating Console** — chat TUI plus a tray-launched window showing the chat stream, the active task, and your open browser tabs.

### The Console

![CortexAgent Console](assets/cortexagent-console.png)

A floating Tkinter window launched from the tray. Three panels: chat (where the agent streams its work), a tab list of the browser pages you're actively using, and the running tasks. The Console is what you watch while the agent works — start a task, switch away, glance back to see progress, jump in when you need to.
- **Local model by default** — a 35B-class MoE on llama.cpp at `127.0.0.1:11599`, spawned by the launcher as its own child: context auto-fits your free VRAM, and the model dies with the app.
- **Automatic memory** — hot/warm/cold tiers on local disk; sessions resume without re-explaining yourself.
- **Token compression** — SlimToken lanes minify requests before the backend sees them: a distill+dedup lane for cloud calls, a full pipeline for everything else. More fits the window either way.
- **Optional cloud dispatch** — the cloud side is a separate MCP server that contains everything cloud: queued tasks, complexity grading, remote generation. Disable it and cortexagent is fully offline; enable it and heavy work runs in a parallel lane that never interrupts the local model.
- **Message triage** — one configured thread plus your inbox, answered from your default browser; sends are deterministic, verified, and never require OAuth.
- **Local speech-to-text** — mouse-only dictation popup; audio stays on your machine.
- **VRAM back on exit** — close cortexagent and the model's VRAM is freed instantly; nothing lingers.
- **Self-repair** — `cortexagent doctor` detects and fixes config drift.

---

## When it's not for you

A tool that tests itself should name its own limits:

- **Frontier reasoning.** A local MoE is capable but not frontier-class. For a genuinely novel puzzle you'll often do better with a hosted model — and nothing here stops you from exporting a conversation and running it there.
- **It wants VRAM.** The launcher picks the largest context that fits your free VRAM automatically; forcing a bigger fit than the GPU holds OOMs — that's your experiment, so test it yourself.
- **Text-first.** The main model is text-only; images route through a bundled vision model. Vision works, the text model just never sees a pixel.
- **Single-user, Linux-only.** One agent on one machine — not a multi-user team platform.

---

## How it works

| Service | Address | Role |
|---|---|---|
| Local model (llama.cpp) | `127.0.0.1:11599` | the agent's brain — spawned by the launcher, dies with it |
| SlimToken cloud lane | `127.0.0.1:11435` | minifies cloud-model requests (distill + dedup, tool schemas untouched) |
| Raw ollama backend | `127.0.0.1:11600` | optional cloud models — zero VRAM, used only if configured |
| CDP (default browser) | `127.0.0.1:9224` | page-level browser automation |

Everything binds to `127.0.0.1` — never `0.0.0.0`. Enforced in code, checked by `bin/verify`.

> 💡 **VRAM:** the launcher owns the model lifecycle — close the app and VRAM is free the same second.
> ⚠️ **Model fit:** context is chosen from free VRAM at each start; display load varies, so the fit varies with it.
> 🔒 **Localhost:** these ports are local-only by design — don't forward or expose them.

### Hybrid by design — local owns the session, cloud owns the queue

- **Your conversation never leaves.** The TUI is pinned to the local model — cloud is not a chat fallback, it's a separate lane for separate work.
- **The cloud lane is an optional MCP server, not a personality.** Message triage, research, and other parallel jobs are queued, graded for complexity, and executed with real tool access — alongside the local model, never interrupting it. The two lanes claim work independently, so a busy brain never blocks a queued send. With the dispatcher disabled, none of this exists: fully offline.
- **Sends are deterministic.** Outbound texts and emails execute as scripted payload steps with a post-send landing check — no model call in the loop, so a send can't loop, stall, or invent a recipient.
- **Cloud traffic is minified on the way out.** Every cloud request passes through the local SlimToken lane first. Configure no cloud backend and the lane simply doesn't exist.

---

## CLI

```bash
cortexagent                      # interactive session (TUI + tray)
cortexagent -p "task"            # one-shot
cortexagent --restart            # restart the background services
cortexagent doctor               # detect + fix config drift
cortexagent status               # is everything up?
```

---

## Security

- **Binds `127.0.0.1` only** — enforced in code, verified by `bin/verify`.
- **No API keys stored, no telemetry, nothing uploaded by default.** Cloud generation is opt-in: the cloud dispatcher is a separate MCP server — disable it and cortexagent is fully offline; if you enable a cloud endpoint, requests are minified through the local proxy on the way out.
- **Browser-mode messaging stores no tokens** — your logged-in tabs are the credential. OAuth is an optional alternative for setups that prefer a token.
- **Local-first by construction** — memory, browser state, and voice all live on your machine.

---

## License

MIT — see [LICENSE](LICENSE).