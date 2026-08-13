# Cortex CLI — the `cortex` command (Claude Code replacement)

**Date:** 2026-08-13
**Status:** Design (approved by user direction)

## Goal

Replace the single piece of software the user opens daily: the `claude` command
and its chat window. A new `cortex` command opens a similar chat window —
fully branded, fully offline, air-gapped, CPU-capable — wired to CortexAgent's
local models and skills. **Nothing else in CortexAgent is touched.**

## Scope

**INCLUDE:**
- A `cortex` command that opens a chat TUI (like `claude`)
- Custom theme / branding
- Wiring to local models (`:8080` big 35B, `:8082` tiny) with auto-switch by task
- Extensions: auto-yes mode, plan mode, task strip above chat, stats bar
  (tokens/sec, total tokens, auto mode), Shift+Tab mode cycling
- Port Claude's skills to local Python scripts, with a cache + preload layer
- Fully offline / air-gapped operation

**EXCLUDE (do NOT touch):**
- CortexAgent itself — stays whole, keeps working
- MCP servers — left alone (kept in codebase, disabled by default)
- Daemon / overseer / webui / tray / STT / browser / media / RAG

**CONSTRAINTS:**
- Fully offline — no cloud, no API keys, no network calls
- CPU-capable — must run without GPU if needed
- MCP stays in the codebase but **disabled by default** (optional; offline
  mode works first; minification + readme handled in another session)
- No personal info leaks; localhost-only bindings

## Architecture

**Base: fork of [Pi](https://github.com/earendil-works/pi)** (MIT, ~89k stars,
minimal terminal coding agent harness). Pi is chosen because it is plain by
design, extensible (extensions, skills, themes, packages), supports local
OpenAI-compatible providers, and has no built-in permission popups / plan mode
/ MCP — those are exactly the pieces we control.

```
cortex/                          ← fork of Pi, rebranded
├── src/                         ← Pi core (minimal, untouched where possible)
├── theme/                       ← custom theme (branded)
├── extensions/
│   ├── models.ts                ← wire :8080 big + :8082 tiny, auto-switch
│   ├── permissions.ts           ← auto-yes toggle + permission gate
│   ├── modes.ts                 ← plan mode flag + Shift+Tab cycling
│   ├── ui.ts                    ← task strip widget + stats bar footer
│   └── skills.ts                ← bridge to CortexAgent Python skills + cache
├── skills/                      ← ported Claude skills (Python modules)
└── README.md
```

## Components

### 1. Fork + rebrand

Fork `earendil-works/pi`, rename to `cortex`. Keep the Pi core minimal and
upstream-syncable. All customization lives in `extensions/` + `theme/` so the
core stays clean.

### 2. Theme

Custom terminal theme via Pi's theme system (`theme.bg()`, `theme.fg()`,
`theme.bold()`). Fully branded — colors, accents, status text.

### 3. Model wiring (`extensions/models.ts`)

- Register `:8082` (tiny LFM2.5) and `:8080` (big Qwen3.6-35B) as
  OpenAI-compatible providers via `pi.registerProvider("local-openai", ...)`.
- Auto-switch by task: intent classification (reuse CortexAgent's
  `pre_flight_gate.classify_intent`) — quick chat → tiny, complex/coding → big.
- Verified: `:8082` responds to `/v1/models` (OpenAI-compatible llama-server);
  `:8080` is the same when loaded.

### 4. Extensions

| Extension | Mechanism | Feature |
|-----------|-----------|---------|
| `permissions.ts` | `tool_call` event (block/allow) | Auto-yes toggle — when on, never block; when off, prompt |
| `modes.ts` | `pi.registerFlag("plan", ...)` + `pi.registerShortcut("shift+tab", ...)` | Plan mode flag; Shift+Tab cycles command types |
| `ui.ts` | `ctx.ui.setWidget()` + `ctx.ui.setStatus()` + `ctx.getContextUsage()` | Task strip above chat; stats bar (tokens/sec, total, auto mode) |
| `skills.ts` | `pi.registerTool()` bridging to Python | Load CortexAgent Python skills as Pi tools |

### 5. Skills port + cache

Port Claude's skills (brainstorming, TDD, systematic-debugging, writing-plans,
etc.) to local Python modules — each exposing `NAME`, `DESCRIPTION`, `SCHEMA`,
`run(args) -> {"ok", "output", "error"}` (the existing CortexAgent skill
format). Loaded via a Pi extension bridge.

**Cache + preload layer (the optimization):**
1. **Module cache** — load each skill module once, reuse forever (kills
   re-execution cost on every session).
2. **Preload** — warm the cache at startup, not first tool call.
3. **Usage tracking** — count which skills actually get called; preload only
   the hot ones. Scales when 50+ skills are ported.

### 6. MCP — kept, disabled

MCP support stays in the codebase but is **disabled by default**. Fully offline
mode works first. MCP is optional — if it works later, enable it. Minification
+ readme explanation is handled in another session (not this build).

## Data flow

```
user types in cortex chat
  → intent classification (tiny vs big)
  → model emits <function_call> tags (Pi's tool loop)
  → permission gate (auto-yes on → no prompt)
  → tool executes (core / browser / skill)
  → observation returned to model
  → loop until answer
  → stats bar updates (tokens/sec, total, auto mode)
```

## Verification

1. `cortex` opens a chat window — branded, themed
2. Chat works fully offline (no network calls, no API keys)
3. Auto-switch: simple chat → tiny; complex task → big
4. Auto-yes toggle works (on = no prompts, off = prompts)
5. Plan mode + Shift+Tab cycling work
6. Task strip shows scheduled tasks above chat
7. Stats bar shows tokens/sec, total tokens, auto mode
8. Skills load from cache (preloaded, no re-execution)
9. MCP disabled by default; enabling it later doesn't break offline mode
10. Runs on CPU (no GPU required)

## Out of scope

- MCP minification + readme (other session)
- Releasing skills/tools as standalone downloads for other harnesses (later)
- Touching CortexAgent's daemon/overseer/webui/tray
- Replacing the existing CortexAgent TUI (`lib/tui.py`)

## Risks

- **Pi upstream changes** — mitigate: keep core minimal, extensions isolated,
  upstream-syncable
- **TUI quality** — mitigate: build on Pi's proven TUI, not from scratch;
  verify live; fall back to CLI view if broken
- **Skill port volume** — mitigate: cache + preload + usage tracking; port in
  batches after the core loop works
- **Model auto-switch misclassification** — mitigate: reuse the proven
  `pre_flight_gate` intent classifier
