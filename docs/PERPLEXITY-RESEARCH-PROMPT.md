# CortexAgent — Perplexity Research Prompt (full architectural breakdown)

> One giant prompt. Paste into Perplexity Pro / Deep Research. It is written so the
> model can answer **without ever reading the repo** — every fact about the project
> is inlined below. The model is asked to (a) confirm the architecture, (b) point out
> security / prompt-injection / stability risks, (c) suggest hardening, (d) propose
> beautification / UX improvements, (e) list any architecture-level smells.
>
> If you want to keep it short, the prompt itself begins at the
> "BEGIN PROMPT" line. Everything above it is metadata for humans.

---

## Metadata for the human reader

- **Project:** CortexAgent (`<repo>/cortexagent`) — local coding-agent runtime.
- **Stack at a glance:** two local models on one GPU (35B MoE + ≤2B MoE), a `slimtoken` chokepoint proxy, an always-on `overseer` daemon, two systemd user services, an in-process `diffusers` diffusion backend, and three user-facing surfaces (CLI / 3D webui on `:8090` / system-tray popout). All traffic on `127.0.0.1`. No cloud, no fallback swap.
- **Why we want this report:** we have a 13.7 GB primary model, a 1.2 GB orchestrator, three UIs that partially overlap, a slimtoken middleware that has eaten its own tail more than once, and a `subprocess.run(..., shell=True)` somewhere in the queue path. We need an outside pair of eyes.
- **What we are *not* asking for:** rewriting the whole project, recommending a different framework, replacing llama.cpp, anything that touches external APIs, anything that requires an internet connection at runtime. The whole point of CortexAgent is local / air-gappable.
- **How to read the answer back:** for each finding, please give **(severity: CRITICAL/HIGH/MED/LOW)**, **(where in the architecture, not the file)**, **(exact fix)**, and **(verification step)**. Verdicts like "consider improving X" without a concrete fix are not useful to us.

---

## BEGIN PROMPT

You are a senior security + distributed-systems reviewer doing a deep research pass on **CortexAgent**, a local self-hosted coding-agent runtime. The user is the maintainer; they are not a beginner. Assume you can be technical. They want a single exhaustive report that covers **architecture correctness, three user-facing UIs, beautification, prompt-injection & security, and stability**. Do not rewrite the codebase for them — explain the *shape* of the problem and the *kind* of fix.

Your output must be a single markdown report with the section structure **exactly** as numbered below. Use tables for any comparison. Be concrete. No filler.

---

### Section 1 — Executive summary (≤ 200 words)

A 200-word executive summary a non-technical stakeholder could read. What the product is, who uses it, what it is good at, what is the single biggest risk, what is the single biggest missed opportunity.

### Section 2 — Confirmed architecture (correctness check)

I will describe the architecture below. Your job in this section is to:
1. Restate it back in 3–5 sentences so we know you understood.
2. Flag any **architectural** mistakes (NOT code-level bugs) — wrong defaults, races, single points of failure, missing invariants, components that should exist and don't.
3. Flag anything that smells like "this will not survive a power cut" or "this will not survive two simultaneous users" or "this will not survive 100 GB of memory".

---

#### 2.1 Stack

| Component | Address / location | Process | Role |
|---|---|---|---|
| Big reasoning LLM | `127.0.0.1:8080` (llama-server) | llama.cpp | Qwen3.6-35B-A3B-UD-IQ3_S GGUF, ~13.7 GB at 128K ctx, ubatch 1024, multimodal, uncensored. **Only model on `:8080`. No fallback.** |
| Tiny orchestrator LLM | `127.0.0.1:8082` (llama-server) | llama.cpp | LFM2.5-1.2B Q4_K_M, ~728 MB, MoE. Used by overseer only — never answers user prompts directly. |
| Grammar + slimtoken proxy | `127.0.0.1:8081` | `lib/grammar_proxy.py` | **The chokepoint.** Strips `grammar` (which llama-server rejects on chunked), runs `slimtoken.optimize_messages()` pair-safely, attaches a `<cold_memory>` block, forwards to `:8080`, streams SSE back. |
| Daemon | AF_UNIX `~/.cortexagent/control.sock` | `lib/daemon.py run` (systemd `cortexagent.service`) | Owns `:8080` + `:8081`. Manages session lifecycle, idle-unload (default `idle_unload_sec=0` = keep big loaded), adopts the overseer's tiny. CLI is a thin client over this socket. |
| Overseer | always-on | `lib/overseer.py start` (systemd `cortexagent-overseer.service`, `Type=forking`) | Scheduler, hot→cold distillation, tiny-keepalive, watchdog, queue, calendar. Writes `overseer_state.json` + `overseer_queue.json` + `overseer_schedule.json`. Default tick = 30 s. Owns tiny `:8082` exclusively. |
| Tray | system tray | `lib/tray.py` (systemd `cortexagent-tray.service`, `Type=simple`, `Wants=` + `After=` overseer) | Owns overseer lifecycle (calls `start` on launch, `stop` on Quit). Hosts the popout dashboard. |
| Webui | `127.0.0.1:8090` | `lib/webui.py serve` (in-process `ThreadingHTTPServer`) | 3D chat surface + dashboard, served by the daemon, shares session with CLI via SessionBridge. |
| Diffusion | in-process on the same GPU | `lib/diffusion_backend.py` | SDXL / SD 1.5 / LTX-Video via `diffusers` in-process. Daemon unloads big to free VRAM, runs diffusion, reloads (~30 s swap). cuDNN off by default. |
| Memory daemon | AF_UNIX `~/.cortexllm/memory.sock` | `~/.cortexllm/scripts/memory-daemon.py` | CortexLLM hot/cold writes, no caps (per 2026-08-11 user directive). |

#### 2.2 Request chain (the spine)

```
User (CLI / webui / TUI / tray)
   │
   ▼
cortexagent_call.py  →  lib/memory_thin.append()  (hot, no caps)
   │
   ▼
cortex_routing.py    →  pre_flight_gate.classify_intent()  (intent + mode)
   │
   ▼
prompt_framing.py    →  domain framing (business / OSINT / cyber / professional)
   │
   ▼
react_loop.py        →  mode ∈ {react, socratic, direct}
   │
   ▼
grammar_proxy :8081  →  slimtoken.optimize_messages() + cold-memory attach
   │
   ▼
big llama-server :8080
   │
   ▼
back through :8081 (response-side minify, filler strip)
   │
   ▼
response_model.py    →  typed block parse (text / tool_call / artifact)
   │
   ▼
beautify.py          →  tables / bar / line / pie / KV → markdown
   │
   ▼
SessionBridge write  →  ~/.cortexagent/state/webui_session.jsonl (O_APPEND + flock + fsync)
   │
   ▼
All UIs re-render via /webui-events (SSE) deduped by id
```

#### 2.3 Memory model

- **Hot** — `~/.config/cortexllm/memory/hot/cortexagent.jsonl`, every prompt/response, **no cap**.
- **Cold** — `~/.config/cortexllm/memory/cold/*.json`, curated facts by category, written by overseer's `_cold_distill()` every idle tick.
- **SQLite** — `~/.config/cortexllm/cortexllm.db`, mirror for fast queries.
- **Platform key** is always `"cortexagent"` (the in-tree `memory/mcp_server.py` is what the CLI talks to; the generic `~/cortexllm/repo` is the upstream package).
- **SessionBridge** is append-only NDJSON with `flock`+`fsync`; event shape `{id, from, type, username, content, ts, seq}`; SSE consumer dedupes by `id`.

#### 2.4 Session model

- **Daemon** owns the session refcount (`_active_sessions` int + `_last_request` ts) under a `_lock`.
- **CLI** is the only `session-start` / `session-end` caller (on `trap cleanup EXIT INT TERM PIPE`).
- **Grammar proxy** sends `activity` on every forwarded request — keeps big loaded during webui-only use.
- **Webui** does **not** claim a session; it borrows the daemon's active pid for `X-CortexAgent-Session` so CLI + webui share proxy context. Falls back to `webui-<uuid>` if no live CLI.
- **Overseer** is strictly monitor + scheduler. Its LLM traffic goes to tiny `:8082`. It does not write chat messages by default — but can via `username="Overseer"` events on the bridge.

**Session reset paths:**
1. Idle-unload: `sessions == 0` and idle > `idle_unload_sec` (only if `> 0`).
2. Stale-session self-heal: `sessions > 0` but no request for `stale_session_sec` (1800 s) → zero refcount.
3. Overseer watchdog: no CLI/claude `--mcp-config` proc AND daemon idle > 300 s AND `active_sessions > 0` → `session-reset`.
4. Context failsafe: big's `/slots` `n_past/n_ctx ≥ 95%` for 3 ticks → `session-reset`.

#### 2.5 Models (two-models-only rule)

- **Big** = `Qwen3.6-35B-A3B-UD-IQ3_S.gguf`, ~13.7 GB, 128K ctx, ubatch 1024 (LOCKED).
- **Tiny** = LFM2.5-1.2B Q4_K_M, ~728 MB.
- **No fallback.** `lib/daemon._fallback_extra_args()` is a back-compat no-op stub. If big can't fit, daemon logs and leaves big down; user is expected to fix VRAM, not swap.

#### 2.6 Minify & grammar

- Proxy strips `grammar` field (fixes llama-server 400 on chunked transport past repetition threshold).
- Slimtoken pipeline: `tools` (drop `$comment`, `title`, `examples`; compress description) → `system` (collapse whitespace outside fences) → `messages` (collapse blanks; pass tool/image blocks untouched) → `dedup` (collapse repeated `tool_result`; latest kept verbatim) → `distill` (truncate old assistant prose beyond last 4 turns, fence-aware) → `budget` (hard token cap, pair-safe prefix drop). All on by default. Budget = `big_ctx * 0.85` per request.
- `SLIMTOKEN_MINIFY_<STAGE>=0` per-stage disable. Full disable is `SLIMTOKEN_MINIFY=0`, in which case the proxy is a pass-through.
- `lib/minify_stats.json` is persistent across restarts (proxy `/metrics` resets on restart, so dashboards fall back to the file).

#### 2.7 Diffusion

- In-process `diffusers`. SD 1.5 / SDXL via `StableDiffusionPipeline.from_single_file` (reuses existing `.safetensors`). Video via `LTXPipeline.from_pretrained("Lightricks/LTX-Video")` → `export_to_video`.
- Orchestrator unloads big to free VRAM, runs diffusers, reloads. ~30 s swap.
- cuDNN off by default (`CORTEXAGENT_DIFFUSION_CUDNN=0`) — verified workaround for cuDNN 9.2 / driver 550 `CUDNN_STATUS_NOT_INITIALIZED` on first UNet conv. Native conv works.
- Image: SD 1.5 ~8 it/s @ 512², peak 3.74 GB.

#### 2.8 CLI output rules

| | |
|---|---|
| R1 | Plain CLI by default; dashboard is the webui at `:8090`. |
| R2 | Code hidden by default. Prefix prompt with `show code` or `with code` to reveal. |
| R3 | After every response: `_` divider and a `▎ thinking:` line. |
| R4 | Output-side minify via `lib/grammar_proxy.minify_response()`. |
| R5 | Visual output always on — box-drawn tables, numeric `█` bars, lists `▎`. |
| R6 | Ambiguous prompts trigger a clarifying question, not a guess. |
| R7 | Big model stays loaded (`idle_unload_sec=0`), is multimodal. |

### Section 3 — Confirmed UI inventory (correctness check)

We have **three** user-facing surfaces. Below is what each is supposed to do. Tell me if any of them does not actually do what it claims.

#### 3.1 CLI (`bin/cortexagent` → `engine/cli.py` → `lib/grammar_proxy.py` + `lib/session_bridge.py`)

**Intended:**
- Default surface. Plain text in, plain text out.
- One-shot (`-p "..."`) or interactive.
- Status: `cortexagent status`. Doctor: `cortexagent doctor`. Restart: `cortexagent --restart`.
- Shares session with webui and tray via SessionBridge; what you type here appears in the unified chat on `:8090`.
- Output follows R1–R7 above.

**Known concerns to validate:**
- R2 "code hidden by default" — does this actually work end-to-end through the proxy, or does the proxy strip the prefix and the model never sees it?
- R3 "thinking line" — is this genuinely useful or just visual noise?

#### 3.2 3D Webui on `:8090` (`lib/webui.py`)

**Intended:**
- Browser interface, served by the daemon, single-process `ThreadingHTTPServer`.
- 3D chat surface + dashboard. Live tok/s, VRAM, minify stats, alerts, queue, schedule.
- Multi-voice unified chat pane: User / Big Model / Overseer. Consumes SessionBridge over SSE (`/webui-events`).
- Auth: `Bearer` or `X-CortexAgent-Token` header, or `?token=…` query param (the query-param fallback exists for EventSource which cannot carry custom headers).
- Routes include: `/`, `/api/state`, `/api/models`, `/api/tps`, `/api/overseer`, `/api/active`, `/api/schedule/{add,remove}`, `/api/chat`, `/api/image`, `/api/video`, `/api/load`, `/webui-events` (SSE), `/message` (legacy).
- Settings page exists (operator.yaml + per-route options).

**Known concerns to validate:**
- The `?token=…` query-param fallback for SSE leaks the token to browser history, referer headers, and any access log. This is a known design tradeoff — is there a better way to do SSE auth?
- Webui sends a message to `claude-code` via `subprocess.run` (legacy `/message` route). What is the threat model here?
- "3D" — is this a real Three.js 3D scene, or marketing? (This is the public-facing framing; I want to know what it actually renders.)

#### 3.3 System-tray popout (`lib/tray.py` + `lib/tray_dashboard.py`)

**Intended:**
- System-tray icon (pystray + Pillow, falls back to headless stdin keeper).
- Owns the overseer (calls `start` on launch, `stop` on Quit). `Wants=` + `After=` overseer in systemd so tray auto-starts overseer if it is down.
- Right-click → "Overseer Dashboard" → tkinter popout window.

**Popout widget inventory (from `lib/tray_dashboard.py`):**
- Banner: "CortexAgent · by the maintainer · overseer dashboard"
- Left column: session identity, overseer state + dot, rotating tip
- Mid column: tok/s sparkline (60-sample rolling), big-model step counter (▓▓░░ with pulse on update), minify savings (% saved + 60s sparkline + runs + tokens)
- Right column: memory tier panel (hot H, cold C), alerts list, queue list
- Footer bar: Refresh button (the only interactive control besides `R` and `Esc`)
- Data sources: `overseer_state.json`, `big_model_steps.json`, `~/.cortexagent/minify_stats.json`, daemon `control.sock` for live VRAM

**Critical UX issue we already know about (the user has complained):**
- The popout has **one** interactive control (a Refresh button + `R` shortcut + `Esc`).
- Many of the panels are read-only with no actions.
- Some panels (the "overseer state", the "queue", the "alerts") have no buttons to actually do anything — you can see the state but you cannot act on it from the popout. You have to go to the CLI.
- The tray popout does not have a chat input. If you want to send a prompt, you have to use the CLI or the webui.
- The "overseer" persona: when the overseer writes a `username="Overseer"` event to the bridge, does the popout render it the same way it would render a "Big Model" event, or is there a special Overseer chat pane?

#### 3.4 Your job in this section

For each UI, tell us:
1. What is the **core unique value** of this surface? (i.e., what does it do that the other two cannot?)
2. What is the **dead weight** in this surface? (i.e., panels, endpoints, or widgets that exist but are not used or have no effect?)
3. What is the **redundancy** between the three? (i.e., the same information shown in three places with no new value?)
4. Concrete recommendations for pruning.

### Section 4 — Beautification pass

`lib/beautify.py` is a post-processor on the model's final answer. It does (today):
- Normalize markdown tables (align columns, ensure separator row)
- Convert CSV/TSV blocks → markdown tables
- Convert `key: value` blocks → two-column tables (or bar chart if numeric)
- Render numeric series as bar / line / pie (text-based)
- Render tree/hierarchy structures (passthrough — just keeps `├──` `└──`)
- Stub flowchart renderer (hardcoded INPUT → PROCESS → OUTPUT — not data-driven)

It is called from `react_loop.py` (`_beautify_response()`) on react/socratic/direct output, and from `overseer.py` (`_beautify_status()`) on CLI status.

**Known concerns:**
- The pie chart "renders" as a labeled legend only — there is no actual pie. Is this honest UX?
- The line chart's x-axis is just the row index 0..N, not the label. Multi-series does not work (one of the two series is just dropped).
- The flowchart renderer is a hardcoded stub. It is not data-driven. This looks like a placeholder.
- `beautify_html()` wraps the whole output in `<pre>`. The webui is supposed to be a 3D chat surface — does the webui actually do anything fancier with the beautified output than `<pre>`? Or is the 3D claim a lie?
- `_KV_RE` is `^([A-Za-z0-9_ .\-/]+):\s+(.+)$` — it does not match unicode keys, it does not match quoted values, and it will false-positive on prose that contains a colon (e.g., "Next steps: block the IPs." — this is why the regex requires 2+ consecutive lines, but the heuristic is fragile).
- The CSV detector picks the dominant delimiter by occurrence count — what if a row has an embedded comma in a quoted field? Quotes are not handled.
- The tree detector only matches if **every** line matches the tree pattern. It does not handle mixed prose + tree.

Tell us:
1. What are the highest-value additions? (Genuine sparklines, syntax-highlighted code blocks, Mermaid-like ASCII diagrams that are actually expressive, ASCII heatmaps, sequence diagrams, dependency graphs, ASCII calendars, sparkline matrix, per-series line charts with legends, Sankey, treemap-as-text.)
2. What are the lowest-effort correctness fixes? (Quote-aware CSV, real pie geometry, multi-series line chart, label-aware x-axis, data-driven flowchart.)
3. How should the webui render beautified output to make the 3D claim real? (Canvas overlay? Three.js geometry? Inline `<table>` with custom CSS?)
4. How should the tray popout render beautified output? (tkinter has no markdown rendering — does it strip back to plain text, or does it try to render tables in tkinter Text?)

### Section 5 — Prompt injection & security

This is the most important section. The product is air-gapped and trusted, but the *user prompt* comes from a person, and the *tool outputs* may come from the OS, the filesystem, the browser, the diffusion backend, or — if MCP servers are opted in — from external HTTP services. We are a single-vector product: the LLM is the trust boundary, and the LLM is on the same machine as everything else.

Threat model:
- The user is the principal. The LLM is the agent. Everything else (filesystem, network, browser, GPU) is a tool the agent may invoke.
- The local user is fully trusted (this is a single-operator product). The product is not a multi-tenant service.
- However, the **content** the LLM reads can contain adversarial text: emails, documents, web pages, browser pages, MCP server responses, file contents, git history. Any of these can contain text that looks like an instruction. This is the prompt-injection surface.
- The product runs as a user-level systemd service with no privilege separation, no seccomp, no namespacing. If the LLM is convinced to run a command, the user-level account is fully exposed.

**Areas to audit, with the architecture context (NOT the source code — the maintainer will map your findings to the files):**

| # | Surface | Concern |
|---|---|---|
| 5.1 | Grammar proxy request body | The proxy reads the request body, parses JSON, rewrites system/messages, and forwards. Can an injected string inside a tool_result or a long system prompt trick the proxy into forwarding attacker-controlled grammar, system instructions, or images? |
| 5.2 | Slimtoken minify pipeline | The minifier is *trusted code* rewriting *untrusted content*. Does the pair-safe pruning guarantee that a `tool_result` cannot be merged with an attacker-supplied `tool_use`? Does fence-aware compression hold across multi-line code? |
| 5.3 | Cold-memory attachment | The proxy attaches a `<cold_memory>` block. The block content comes from `~/.config/cortexllm/memory/cold/*.json`. If an attacker can write to that path (e.g., they have a shell on the box, or they tricked the agent into `cortexllm.memory_write`), they have a persistent prompt-injection payload that survives across sessions. Is there a content-hash or signature check? |
| 5.4 | Tool outputs (MCP) | When MCP servers are opted in via `CORTEXAGENT_MCP_SERVERS`, the tool outputs are forwarded into the LLM context verbatim. The stub-mode minification is name+description only on the schema; the actual results are not minified or sandboxed. What is the injection surface here? |
| 5.5 | Webui SSE channel | The `/webui-events` SSE stream forwards bridge events to the browser. The bridge is on disk. If the disk file is tampered with (or an Overseer is compromised and writes a crafted event), the browser renders it. Is there integrity validation? |
| 5.6 | Webui `?token=…` query param | The token is in the URL. Browser history, referer headers, server access logs all see it. Recommend mitigation. |
| 5.7 | Webui subprocess calls | The webui calls `subprocess.run` against `lib/overseer.py` for `/api/schedule/{add,remove}` and against `claude-code` for `/message`. The arguments come from the request body. Are they ever interpolated unsafely? |
| 5.8 | Overseer queue | The overseer reads scheduled tasks from disk. If a task in `overseer_queue.json` has a `prompt` field, is that field treated as code? Is there any shell-injection surface? (We are not telling you where — you tell us, based on the architecture: which subsystem would naturally run queued tasks as shell commands, and what is the input source?) |
| 5.9 | Overseer watchdog | The watchdog reads process lists and emits `session-reset` if conditions are met. If an attacker can spawn a process whose name matches the watchdog's allowlist, they can suppress the watchdog. What is the right identity check (pid, start time, exe path, env)? |
| 5.10 | Diffusion backend | The diffusion pipeline is in-process on the same GPU. If the LLM is convinced to call `gen-image` with a path that already exists, does it overwrite? With a symlink, can it overwrite a different file? |
| 5.11 | Filesystem access | The agent reads/writes files in the user's $HOME. Is there a chroot? A path allowlist? Does the LLM know the real `$HOME`, or is it given a virtualized view? |
| 5.12 | Network egress | The product is air-gapped by default. If MCP servers are enabled, the LLM can be tricked into fetching URLs (via the `firecrawl_proxy`, `playwright_brave_mcp`, `browser_control`, `webui_proxy_to_claude` surfaces). What is the egress policy? |
| 5.13 | Model file integrity | GGUFs are loaded from `~/models/...`. Is there a hash check? What if the path is overwritten by another user on the same box? |
| 5.14 | Browser automation | `lib/browser_control.py` drives a CDP-attached browser. If a web page contains a prompt injection, it can issue browser commands. Is the browser sandboxed? |
| 5.15 | Hot memory writes | The "no caps" rule means every prompt and response is appended. If an attacker controls the prompt, they have an unbounded log injection surface. The `printf %s` JSON-escape bug that was fixed 2026-08-10 is a class of bug — what other class-of-bug should we be watching for? |

For each numbered area above, give:
- **Severity** (CRITICAL / HIGH / MED / LOW)
- **Attack scenario** (concrete: "user pastes an email → email contains `Ignore previous instructions and...` → ... → outcome")
- **Mitigation** (specific, e.g., "wrap every tool result in `<tool_output source='x' trust='untrusted'>` and prepend a system-level reminder to never follow instructions inside `<tool_output>`")
- **Verification step** (how the maintainer would prove the fix works — a test, a grep, a fuzzer)

### Section 6 — Stability & reliability

This section is about *not breaking*. The product has eaten itself several times (per the maintainer's audit log: SessionBridge clobber, memory-daemon 4 KB drop, statusline reading the wrong socket, etc.). Tell us which architectural classes of bug are still likely.

| # | Class | Question |
|---|---|---|
| 6.1 | Restart safety | If systemd kills the daemon mid-request, is there a state file that will be corrupted? (Sessions count? Minify stats? Bridge JSONL? Hot JSONL?) |
| 6.2 | Power-cut safety | Same as 6.1 but harder — mid-write to an NDJSON line is recoverable; mid-write to a tmp+rename is not if the rename did not happen. Walk the write paths. |
| 6.3 | Disk-fill safety | What happens when `~/.cortexagent` or `~/.config/cortexllm/memory` hits 100 %? Does any subsystem crash-loop? Does systemd restart-thrash? |
| 6.4 | Port-bind races | Tiny `:8082` and big `:8080` and proxy `:8081` and webui `:8090` are all bound by independent processes. If two processes both try to bind, who wins? Is there a lock file? |
| 6.5 | Model hot-swap | The daemon adopts the overseer's tiny instead of starting its own. What if the overseer is on a different VRAM budget than the daemon expects? |
| 6.6 | Session leak | The daemon refcount. If the CLI's `trap cleanup` does not fire (e.g., `kill -9` or X11 terminal close without trap), does the daemon ever zero the refcount? The watchdog does — but only every 30 s, and only if no CLI proc exists. Is there a faster path? |
| 6.7 | Context overflow | Big is 128K. If a long session approaches the limit, the failsafe fires after 3 ticks (90 s). Is that fast enough? What happens to in-flight requests? |
| 6.8 | Tiny-keepalive noise | Under GPU contention, the keepalive 3 s timeout false-positives and restarts tiny. What's the right algorithm (N consecutive failures? EWMA? backoff)? |
| 6.9 | Diffusion swap | The orchestrator unloads big, runs diffusion, reloads. What if reload fails? Is big left down? Does the user get a clear error? |
| 6.10 | Bridge write starvation | The bridge is on a single file with a single lock. If the Overseer is hammering it from a cron tick and the CLI is also writing, is there head-of-line blocking? Is there a max-line-size limit before `O_APPEND` stops being atomic? |
| 6.11 | Cold-memory size | Cold is unbounded. If the distiller runs every 30 s and produces 1 KB of new facts, that's 2.8 MB/day. After a year: 1 GB. Does the next cold attach to the LLM re-include all 1 GB? |
| 6.12 | systemd restart-thrash | `Restart=on-failure` for all three services. If big fails to load (OOM, missing file), the daemon exit-loops. Is there backoff? A "stop trying" circuit breaker? |
| 6.13 | Multi-user | Single-operator product. But: if the user SSHes in from two places, the AF_UNIX socket is per-user. Each shell has its own daemon. Two daemons can both try to load big — who wins? |
| 6.14 | Update safety | The product is `git pull`-able. The systemd services auto-restart on file change (no, they don't — but `cortexagent --restart` does). What is the safe-update protocol? |
| 6.15 | Backup/restore | `~/backups/cortexagent-2026-08-11/` exists. What is in it? What is *not* in it that should be? |

For each class:
- **Likelihood** (LOW / MED / HIGH)
- **Failure mode** (what the user sees)
- **Hardening** (concrete: e.g., "use `os.replace()` after writing to a tmp file, never `os.rename()` on a non-empty target", "add a `fsync()` between write and rename", "bound the cold attach to the last 256 KB with a relevance filter", "circuit-breaker after 5 daemon restarts in 60 s")
- **Verification** (test, integration test, chaos test)

### Section 7 — UIs: beautification & UX

(This is the section the user is most frustrated about. The overseer popout is described as "I don't even know what the hell is talking about or what it's saying, or it has no controls. I think the overseer is way less useful than it should be.")

For each of the three UIs, answer:

#### 7.1 CLI
- Is the CLI actually the right default surface for an LLM-coding agent? Or should it be the secondary, with the webui as primary?
- R2 (hide code by default) — is this a feature or a footgun? In an IDE-driven world, the user is *expecting* code. Hiding it until they type `show code` may make the product feel evasive.
- R3 (thinking line) — useful or noise? Should it be collapsed by default, expandable on click?
- What is the *one thing* the CLI does that no other UI can do? (Hint: it is the only one that can do `cortexagent doctor`, `cortexagent --restart`, `cortexagent status` from outside a browser. Is the CLI being used for what it is uniquely good at?)

#### 7.2 Webui
- "3D" — is this a Three.js scene, a WebGL canvas, or just `<canvas>` with a 2D drawing? Be honest.
- The chat pane is multi-voice (User / Big Model / Overseer). Are the voices visually distinct? Are message timestamps shown? Is there a "scroll to bottom" auto-follow? Is there a typing indicator?
- The dashboard is on the same page as the chat, or a separate route? Is it always visible, or behind a tab?
- Settings: is there a way to change the model, the temperature, the system prompt, the bound port, the auth token? Without re-running the install?
- Diff viewer: when the LLM edits a file, is there a side-by-side or inline diff? Can the user accept/reject edits one at a time?
- Cancel button: can the user kill an in-flight request? What about cancel-and-retry-with-different-prompt?
- History: is there a way to search past sessions? To export a session as a markdown file? To fork a session at message N?
- Multi-tab: can the user have two conversations open at once, with different system prompts? (Critical for "OSINT vs. cybersecurity" framing per the chain-overhaul plan.)

#### 7.3 Tray popout — **the section the user is most frustrated with**

The popout today is **read-only**. You can see:
- Overseer state (running pid, started, ticks, model, memory counts, last compact, last distill, queue size, schedule entries, minify stats)
- A session identity
- A rotating tip
- A tok/s sparkline
- A big-model step counter
- A minify savings panel
- A memory tier panel
- An alerts list
- A queue list
- A freshness popover (mtime of each data source)

You can press **Refresh**, **R**, or **Esc**. That is the entire interaction surface.

The user's complaint: "I don't even know what the hell is talking about or what it's saying, or it has no controls. I think the overseer is way less useful than it should be."

Tell us:
1. **What is the overseer for, from the user's point of view?** The user knows the daemon is for the LLM, the webui is for chat, the CLI is for status/restart. What is the *unique* job of the overseer? If the answer is "scheduler and distillation", is the user even aware of that? Is the popout surfacing it?
2. **What controls should the popout have that it does not have today?** (Examples to consider: "Pause scheduler", "Trigger cold distill now", "Show next 5 scheduled tasks with countdown", "Unload big to free VRAM", "Restart big", "Switch profile", "Open the webui in a browser", "Send a quick prompt to the overseer's tiny directly", "Add a one-shot task to the queue".)
3. **What is the overseer "saying" right now that the user cannot parse?** The state JSON has fields like `last_llm_summary: "System is healthy with normal performance metrics."` — this is the tiny model being asked to summarize, once per tick. Is this useful? Is it trustworthy (1.2B model, 2K ctx, can it actually summarize)? Is the language clear? Should the popout hide it, replace it with structured fields, or make it dismissable?
4. **What is the Overseer persona?** When the overseer writes `username="Overseer"` to the bridge, where does that show up? In the popout? In the webui chat pane? In both? Should the Overseer have its own chat pane, or a structured log ("10:23 distilled 12 facts", "10:30 fired daily backup", "10:45 tiny restarted")?
5. **What is the visual identity of the overseer?** The brand bar is teal/ice blue. Does the Overseer have its own color? Its own avatar? Its own typographic treatment? Or does it just inherit the brand?
6. **Layout redesign.** If you were redesigning the popout from scratch, what would be on it? Three columns? A single column? A chat-first layout with status-as-rail? A status-first layout with chat-as-modal?

#### 7.4 Cross-UI redundancy

| Surface | Shows tok/s | Shows minify | Shows memory | Shows queue | Shows alerts | Has chat input | Has controls |
|---|---|---|---|---|---|---|---|
| CLI status | yes | yes | yes | yes | partial | no (one-shot only) | `doctor`, `restart` |
| Webui dashboard | yes | yes | yes | yes | yes | yes | settings, image gen, video gen, schedule add/remove |
| Tray popout | yes (sparkline) | yes (% + sparkline) | yes (H/W/C bars) | yes (count) | yes (list) | **no** | **Refresh only** |

What is the *minimum* amount of info that should be on the tray popout (so it is not a duplicate of the webui) and what is the *unique value* the tray should provide (so it is not just a stripped-down webui)?

### Section 8 — Architecture smells

Independent of bugs and security, what *architectural* smells do you see? Examples to consider:
- The proxy sits between every request and the model — is this the right chokepoint, or should it be a sidecar?
- The Overseer is a single long-running process with a 30 s tick — is that the right cadence? What is the latency budget for "triggered a scheduled task → user sees the result"?
- The SessionBridge is a single file on disk — is that the right substrate for a multi-voice multi-process chat? What are the alternatives (Unix datagram socket, in-process pub/sub, named pipe)?
- The CLI/webui/tray are three processes that all read the same state files — is there a way to push state instead of poll?
- The diffusers backend is in-process with the LLM backend — is that the right coupling? What if the user wants to use diffusers on a different GPU?
- The grammar proxy is python — at 12 ms/request, is that the bottleneck? Should it be Rust?
- The hot/cold tiering is manual (the LLM is asked to write to cold, the overseer distills) — would automatic vector-based retrieval be better?

For each smell:
- **What is the smell?** (one sentence)
- **What is the cost?** (in time, in complexity, in failure mode)
- **Is it worth fixing?** (yes / no / defer)

### Section 9 — Prioritized recommendation list

End the report with a single prioritized list of the **top 15 recommendations**, sorted by **impact / effort** ratio. For each:
- **Title** (≤ 60 chars)
- **Impact** (CRITICAL / HIGH / MED / LOW)
- **Effort** (S / M / L / XL — S = < 1 hour, XL = > 1 week)
- **One-sentence description**
- **Verification step** (how the maintainer would know it worked)

### Section 10 — Open questions for the maintainer

End with **5 questions** the maintainer should answer before any of the above is implemented. These should be the questions where the answer changes the design.

---

## END PROMPT

### What to do with the answer

1. Save the report to `~/cortexagent/docs/PERPLEXITY-RESEARCH-REPORT.md` when it comes back.
2. For each CRITICAL or HIGH finding, file a one-line ticket in `~/cortexagent/.superpowers/` (or wherever the project tracks issues).
3. For the top 3 recommendations, draft an implementation plan and bring it back to the manager session for review.

---

**Maintainer:** the maintainer ·
**License:** MIT ·
**Repository:** `<repo>/cortexagent`
