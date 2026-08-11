# Claude Code Reference — saved locally

> **Pulled 2026-08-11** from https://code.claude.com/docs/llms.txt
> Source: https://code.claude.com/docs/en/

## Why this exists

CortexAgent spawns `claude` as a child process for non-interactive work
(lib/overseer.py `_spawn_subagent`). The right flags change between
Claude Code versions; these are the canonical reference docs so the
right commands are always used.

## Pages saved

| File | Source | Notes |
|------|--------|-------|
| `01-cli-reference.md` | https://code.claude.com/docs/en/cli-reference.md | All commands + flags |
| `02-environment-variables.md` | https://code.claude.com/docs/en/env-vars.md | Full env var reference |
| `03-tools-reference.md` | https://code.claude.com/docs/en/tools-reference.md | Built-in tools |
| `04-interactive-mode.md` | https://code.claude.com/docs/en/interactive-mode.md | Shortcuts + slash cmds |
| `05-checkpointing.md` | https://code.claude.com/docs/en/checkpointing.md | /rewind behavior |
| `06-hooks-reference.md` | https://code.claude.com/docs/en/hooks.md | All hook events |
| `07-plugins-reference.md` | https://code.claude.com/docs/en/plugins-reference.md | Plugin schema |
| `08-channels-reference.md` | https://code.claude.com/docs/en/channels-reference.md | MCP channel contract |

## Critical flags for CortexAgent

### `--print` / `-p`
Non-interactive mode. REQUIRED for `_spawn_subagent` — without it, claude
launches an interactive REPL and hangs the subagent timeout.

### `--bare`
Skip CLAUDE.md / hooks / skills / MCP auto-discovery. Set in `_spawn_subagent`
so subagents don't re-read CLAUDE.md (which we no longer ship) or pollute
the parent's auto-memory. Sets `CLAUDE_CODE_SIMPLE=1`.

### `--dangerously-skip-permissions`
Subagents run with permission prompts disabled — the user already authorized
the work by queuing it. Without this, the subagent blocks on the first
Bash call.

### `--model sonnet | opus`
Default `sonnet`; `opus` for LLM_REASONING workflow tasks (heavier reasoning).

### `--output-format text`
Plain text for parseable output. `stream-json` for live streaming but
harder to parse.

## Critical env vars

| Var | Effect |
|-----|--------|
| `CLAUDE_CODE_SIMPLE=1` | Set by `--bare`; disables hooks/skills/CLAUDE.md auto-discovery |
| `MCP_TIMEOUT` | MCP server connection timeout (30s default) |
| `ANTHROPIC_MODEL` | Default model (overridden by `--model`) |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` | Suppresses telemetry |

## Forbidden patterns

- ❌ `--no-input` — does not exist in `claude` CLI (was the original bug
  before Task #59; subagents failed silently).
- ❌ `--continue` inside a subagent — should use `--resume <id>` instead.
- ❌ `--teleport` from a subagent — web session target.
