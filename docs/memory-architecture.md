# CortexLLM Unified Memory — Architecture

> **Date:** 2026-08-17
> **Status:** Verified against the live system (daemon, MCP, symlinks, CortexAgent wiring).
> **Headline:** There is NO cloud memory. Everything is local, on-disk, air-gapped.

## One shared local memory: CortexLLM

All memory funnels into a single store at `~/.config/cortexllm/memory/`. The MCP
config (`~/.cortexllm/local-mcp.json`) calls it *"the ONLY memory for any model."*

| Tier | What it is | Example |
|---|---|---|
| 🔥 **hot/** | NDJSON working buffer, one file per platform — every prompt appends | `claude.jsonl`, `cortexagent.jsonl` (largest), `brain.jsonl` |
| 🌡️ **warm/** | Deprecated (v0.4.2 removed it) — kept as a no-op shim | — |
| ❄️ **cold/** | Curated persistent facts: `.md` files + category `.json` | `agent_critical_rules.json`, `sec-popup-action-console-shipped.md` |

## The wiring (verified)

```
┌─ Claude Code ──────────────────────────────┐
│  ~/.claude/projects/-home-grey/memory       │
│      └─ SYMLINK ──► ~/.config/cortexllm/memory   ◄── same store
└─────────────────────────────────────────────┘
        │  writes via MCP (memory_read/write/search/clear)
        ▼
┌─ CortexLLM memory ─────────────────────────┐
│  hot/  claude.jsonl · cortexagent.jsonl     │
│  cold/  *.md + *.json                       │
│  daemon: ~/.cortexllm/memory.sock (Unix)    │
└─────────────────────────────────────────────┘
        ▲
        │  writes via lib/memory_thin.py → daemon socket
┌─ CortexAgent ───────────────────────────────┐
│  + its OWN session store: ~/.cortex/agent/sessions/
│  + its OWN state: ~/.cortexagent/
└─────────────────────────────────────────────┘
```

**The Claude memory dir is a symlink** to the CortexLLM dir:
`/home/grey/.claude/projects/-home-grey/memory -> /home/grey/.config/cortexllm/memory`.
A memory file written by Claude lands directly in the shared cold memory.

## Key components

- **Memory daemon** — `~/.cortexllm/scripts/memory-daemon.py`, a persistent
  Unix-socket server (`~/.cortexllm/memory.sock`) that batches hot-memory writes
  (SQLite + NDJSON, flush every 50ms / 20 writes) to avoid ~80ms Python startup
  overhead per hook call. Started via `memory-daemon.sh`; checked by the
  SessionStart hook ("memory-daemon already running (pid …)").
- **MCP server** — `~/cortexllm/repo/start-cortexllm-mcp.sh` exposes
  `memory_read / memory_write / memory_search / memory_clear` to any model.
- **CortexAgent client** — `lib/memory_thin.py` writes to the SAME hot buffer
  (`hot/cortexagent.jsonl`) and cold buffer (`cold/cortexagent.jsonl`) via the
  SAME daemon socket (`~/.cortexllm/memory.sock`). CortexAgent is a client of the
  unified memory, not a separate store.

## CortexAgent's own (non-memory) stores

- **Session store:** `~/.cortex/agent/sessions/` — the real work sessions.
- **Config/state:** `~/.cortexagent/` — config, state files, logs.

These are separate from the memory system.

## Answers to the three questions

| Question | Answer |
|---|---|
| Is it cloud? | **No.** Localhost-only, local files, local Unix-socket daemon, local MCP. No cloud anywhere. |
| Is it tied into CortexAgent? | **Yes.** CortexAgent is a client of the same unified memory via `lib/memory_thin.py` → daemon socket. |
| Does CortexAgent have its own, or call it? | **Both.** Own session/state store (`~/.cortex/agent/sessions/`, `~/.cortexagent/`) AND calls the shared CortexLLM memory through the daemon socket. |
