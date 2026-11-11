---
name: memory-tiers
description: Use when persisting or recalling durable facts across sessions - the baked-in memory lane (memory_read, memory_write, memory_search, memory_stats, memory_clear) with hot/cold tiers and per-platform JSONL stores.
---

# memory-tiers

The memory lane is **baked in**: it spawns at every session start from
repo-vendored, sha256-pinned sources and cannot be disabled. Tool names carry
the historical `mcp_memory_` prefix:

- `mcp_memory_memory_read` — read a tier (`hot` = chat buffer, `cold` =
  distilled permanent facts; cold falls back to `cold/<platform>.md`).
- `mcp_memory_memory_write` — write `hot` (immediate facts, what the operator
  asked for / decided this session) or `cold` (facts that should outlive the
  session: preferences, verified toolchain rules, incident lessons).
- `mcp_memory_memory_search` — substring search across hot JSONL + cold JSONL
  + cold markdown. Cheap and offline; use before guessing.
- `mcp_memory_memory_stats` — entry counts + file sizes per tier; the honest
  "is anything stored at all" check.

## Rules

- Store sparingly and specifically: one fact per cold record, with the source
  in the entry text. A pile of vague notes is not memory.
- Solved incidents belong in cold memory the moment they are verified.
- Never write a memory note "to save state before compaction" — the harness
  owns compaction (a HARD rule in APPEND_SYSTEM.md). Memory notes are for
  facts worth surviving, not for panic summaries.
- Transcripts (per-cwd session JSONL) are a separate channel — do not try to
  make memory tiers into a transcript replayer.
