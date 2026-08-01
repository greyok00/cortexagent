# CortexAgent — local coding agent on llama.cpp. No cloud.

## Rules
- No `/home/<user>` in shipped code; use env vars.
- No push/publish/delete without explicit approval.
- No screenshots/image-gen/analysis.
- Report failures plainly; don't claim done if partial.
- Self-contained: don't pull from `~/.claude/CLAUDE.md`, `~/.openclaw/`, `~/.cortexclaw/`.
- Don't run tools unprompted; don't re-derive established facts.

## Context discipline
- Read once; prefer Grep/Glob over full reads.
- Summarize or save large outputs to memory.
- Web fetches: use `brave_fetch` for JS-heavy sites; built-in WebFetch/WebSearch are fallback.
- Reference: `config/AGENT.md` (read on demand).

## Memory
- Auto-saved each turn to hot memory; recent memory injected on start/clear/compact. On compact the last prompt is replayed.
- Use `mcp__cortexagent__memory_*` only for durable, non-obvious facts:
  - `memory_search` — find prior task context.
  - `memory_write` — save high-signal decisions/root-causes (warm).
  - `memory_read` — if search is insufficient.
- Keep entries short and dense; writes auto-prune/dedup.
