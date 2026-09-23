# CortexAgent

> **Your private, local AI coding agent — no cloud required, no API key.**

![CortexAgent session](assets/cortexagent-cli.png)

CortexAgent runs entirely on your machine: a local llama.cpp model spawned and owned by the launcher, a terminal chat session pinned to it, automatic memory across sessions, local browser automation, message triage from your own logged-in browser, and token compression. Everything binds to `127.0.0.1`. No accounts, no telemetry. The optional cloud dispatcher is a separate MCP server — disable it and there is nothing cloud left in the box. See [Security](#security).

---

## It verifies itself

`bin/verify` is an offline gate that ships with the repo. A release only ships when it passes — and you can run it yourself any time:

```bash
bin/verify
```

![bin/verify output](assets/cortexagent-verify.png)

| Layer | Check |
|---|---|
| 1 · Manifest | file-hash drift across the repo |
| 2 · Contract | doc-vs-code contract |
| 3 · Smoke | in-process smoke harness (no live endpoints) |
| 4 · Features | **77** feature-catalog reachability checks |
| 5 · Model package | models.json + local model conf |

The feature catalog is generated, not maintained: it is re-derived from the live handlers, so the count and the checks can't drift from the code.

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

**Code with it** — open the session and give it a task:

```bash
cortexagent
```

**One-shot, no session:**

```bash
cortexagent -p "find why the daemon is unresponsive and fix it"
```

**Drive the browser** — open two tabs in your debugging window (chromium by default) and pin them. The agent has ten site-agnostic CDP tools — navigate, click, type, snapshot, evaluate and more — it never restarts the browser, never touches the CDP port, never closes your tabs.

**Or let it answer your messages** — it watches one configured thread plus your inbox and replies from your default browser; your logged-in tabs are the credential. OAuth is an optional alternative, never a requirement.

---

## What the agent can do

The tool belt is a generated catalog — every tool below is reachability-checked by `bin/verify` on every run.

- **Memory** — 14 tools over hot/warm/cold tiers on local disk: read, write, search, graph queries, session history. Sessions resume without re-explaining yourself.
- **Browser** — ten CDP tools driving your own default browser: navigate, click, type, snapshot, evaluate, fill-and-send, health. Site-agnostic by design.
- **Security posture** — live checks across sshd, nftables, auditd, sysctl, unbound, capabilities, and the LSM stack; hardening status in one call.
- **CVE + MITRE intel** — recent CVEs, per-CVE lookup, technique mapping, mitigation coverage, polling.
- **SIEM + SOAR** — event feed, posture push, playbook runs over recent events, run history.
- **Messages** — triage of one configured thread plus the inbox; sends are scripted payload steps with a post-send landing check, so a send can't loop, stall, or invent a recipient.
- **Documents + RAG** — ingest a domain or a PDF, query it back; coding-practices lookup.
- **Images + video** — local generation through ComfyUI or diffusers (SDXL, SD 1.5, LTX-Video) at up to 4K.
- **Markets** — Alpaca account data, IBKR positions, a strategy hook.
- **Downloads** — verified downloads only: checksum-proven artifacts, stale-file cleanup at task boundaries.
- **Subagents** — spawn workers on the optional cloud lane for parallel research while the local model keeps your session.

---

## When it's not for you

A tool that tests itself should name its own limits:

- **Frontier reasoning.** A local MoE is capable but not frontier-class. For a genuinely novel puzzle you'll often do better with a hosted model — and nothing here stops you from exporting a conversation and running it there.
- **It wants VRAM.** The launcher picks the largest context that fits your free VRAM automatically; forcing a bigger fit than the GPU holds OOMs — that's your experiment, so test it yourself.
- **Single-user, Linux-only.** One agent on one machine — not a multi-user team platform.

---

## How it works

| Piece | Where | Role |
|---|---|---|
| Local model (llama.cpp) | `127.0.0.1:11599` | the agent's brain — spawned by the launcher, dies with it |
| SlimToken cloud lane | `127.0.0.1:11435` | minifies cloud-model requests (distill + dedup, tool schemas untouched) |
| SlimToken local lane | `127.0.0.1:11436` | full compression pipeline for everything else |
| Raw ollama backend | `127.0.0.1:11600` | optional cloud models — zero VRAM, used only if configured |
| CDP (default browser) | `127.0.0.1:9224` | page-level browser automation |
| Cloud dispatch MCP | stdio — no port | scheduler + cloud queue; only exists if you enable it |

Everything binds to `127.0.0.1` — never `0.0.0.0`. The cloud dispatcher is a stdio MCP server, so it holds no port at all.

> 💡 **VRAM:** the launcher owns the model lifecycle — close the app and VRAM is free the same second.
> ⚠️ **Model fit:** context steps down (98304 → 73728 → 49152 → 32768) until it fits the free VRAM; display load varies, so the fit varies with it.
> 🔒 **Localhost:** these ports are local-only by design — don't forward or expose them.

### Hybrid by design — local owns the session, cloud owns the queue

- **Your conversation never leaves.** The session is pinned to the local model — cloud is not a chat fallback, it's a separate lane for separate work.
- **The cloud lane is an optional MCP server, not a personality.** Message triage, research, and other parallel jobs are queued, graded for complexity, and executed with real tool access — alongside the local model, never interrupting it. The two lanes claim work independently, so a busy brain never blocks a queued send. With the dispatcher disabled, none of this exists: fully offline.
- **Sends are deterministic.** Outbound texts and emails execute as scripted payload steps with a post-send landing check — no model call in the loop.
- **Cloud traffic is minified on the way out.** Every cloud request passes through the local SlimToken lane first. Configure no cloud backend and the lane simply doesn't exist.

---

## Self-repair

```bash
cortexagent doctor --dry-run
```

![cortexagent doctor](assets/cortexagent-doctor.png)

Doctor detects config drift — rendered templates, MCP wiring, launcher integrity, model-conf locks — and repairs it in place. `--dry-run` shows what it would fix without touching anything.

---

## CLI

```bash
cortexagent                      # interactive session (TUI)
cortexagent -p "task"            # one-shot
cortexagent --restart            # restart the background services
cortexagent status               # is everything up?
cortexagent queue list           # the prompt queue
cortexagent doctor               # detect + fix config drift
```

---

## Security

- **Binds `127.0.0.1` only** — enforced in code, verified by `bin/verify`.
- **No API keys stored, no telemetry, nothing uploaded by default.** Cloud generation is opt-in: the cloud dispatcher is a separate stdio MCP server — disable it and cortexagent is fully offline; if you enable a cloud endpoint, requests are minified through the local proxy on the way out.
- **Browser-mode messaging stores no tokens** — your logged-in tabs are the credential. OAuth is an optional alternative for setups that prefer a token.
- **Local-first by construction** — memory and browser state live on your machine.

---

## License

MIT — see [LICENSE](LICENSE).