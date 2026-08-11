# Claude Code CLI Reference

> Source: https://code.claude.com/docs/en/cli-reference.md
> Pulled 2026-08-11 · 187 docs available; this is just the CLI page.

## Table of Contents

1. CLI Commands
2. CLI Flags
3. Subcommand Behavior Notes

---

## CLI Commands

| Command | Description | Example |
| :------ | :---------- | :------ |
| `claude` | Start interactive session | `claude` |
| `claude "query"` | Start interactive session with initial prompt | `claude "explain this project"` |
| `claude -p "query"` | Query via SDK, then exit | `claude -p "explain this function"` |
| `cat file \| claude -p "query"` | Process piped content | `cat logs.txt \| claude -p "explain"` |
| `claude -c` | Continue most recent conversation in current directory | `claude -c` |
| `claude -c -p "query"` | Continue via SDK | `claude -c -p "Check for type errors"` |
| `claude -r "<session>" "query"` | Resume session by ID or name | `claude -r "auth-refactor" "Finish this PR"` |
| `claude update` | Update to latest version | `claude update` |
| `claude gateway` | Start the self-hosted Claude apps gateway server | `claude gateway --config gateway.yaml` |
| `claude install [version]` | Install or reinstall the native binary | `claude install stable` |
| `claude auth login` | Sign in to your Anthropic account | `claude auth login --console` |
| `claude auth logout` | Log out from your Anthropic account | `claude auth logout` |
| `claude auth status` | Show authentication status as JSON | `claude auth status` |
| `claude agents` | Open agent view to monitor and dispatch parallel background sessions | `claude agents --json` |
| `claude attach <id>` | Attach to a background session in this terminal | `claude attach 7c5dcf5d` |
| `claude auto-mode defaults` | Print the built-in auto mode classifier rules as JSON | `claude auto-mode defaults --label 'Git Destructive'` |
| `claude auto-mode reset` | Restore the default auto mode configuration | `claude auto-mode reset --yes` |
| `claude daemon status` | Print the background-session supervisor's state | `claude daemon status` |
| `claude daemon stop --any` | Stop the background-session supervisor | `claude daemon stop --any --keep-workers` |
| `claude doctor` | Print read-only installation and settings diagnostics | `claude doctor` |
| `claude import [codex\|gemini]` | Start an interactive session that runs /import | `claude import codex --dry-run` |
| `claude logs <id>` | Print recent output from a background session | `claude logs 7c5dcf5d` |
| `claude mcp` | Configure Model Context Protocol (MCP) servers | See MCP doc |
| `claude mcp login <name>` | Run a configured MCP server's OAuth flow | `claude mcp login sentry` |
| `claude mcp logout <name>` | Clear stored OAuth credentials for an MCP server | `claude mcp logout sentry` |
| `claude plugin` | Manage Claude Code plugins | `claude plugin install code-review@claude-plugins-official` |
| `claude project purge [path]` | Delete all local Claude Code state for a project | `claude project purge ~/work/repo --dry-run` |
| `claude remote-control` | Start a Remote Control server | `claude remote-control --name "My Project"` |
| `claude respawn <id>` | Restart a background session with its conversation intact | `claude respawn 7c5dcf5d` |
| `claude rm <id>` | Remove a background session from the list | `claude rm 7c5dcf5d` |
| `claude setup-token` | Generate a long-lived OAuth token for CI and scripts | `claude setup-token` |
| `claude stop <id>` | Stop a background session | `claude stop 7c5dcf5d` |
| `claude ultrareview [target]` | Run ultrareview non-interactively | `claude ultrareview 1234 --json` |

### Subcommand Behavior Notes

If you mistype a subcommand, Claude Code suggests the closest match and exits
without starting a session. For example, `claude udpate` prints
`Did you mean claude update?`.

As of v2.1.199, `claude --dangerously-skip-permissions daemon <subcommand>` runs
the `daemon` subcommand. Earlier versions treated `daemon <subcommand>` as
the prompt for a new interactive session.

---

## CLI Flags

Customize Claude Code's behavior with these command-line flags. `claude
--help` does not list every flag, so a flag's absence from `--help` does
not mean it is unavailable.

| Flag | Description |
| :--- | :---------- |
| `--add-dir` | Add additional working directories for Claude to read and edit files |
| `--advisor <model>` | Enable the server-side advisor tool for this session (`opus` or `sonnet`) |
| `--agent` | Specify an agent for the current session |
| `--agents` | Define custom subagents dynamically via JSON |
| `--allow-dangerously-skip-permissions` | Add `bypassPermissions` to the `Shift+Tab` mode cycle |
| `--allowedTools`, `--allowed-tools` | Tools that execute without prompting for permission |
| `--append-subagent-system-prompt` | Append custom text to every subagent's system prompt |
| `--append-system-prompt` | Append custom text to the end of the default system prompt |
| `--append-system-prompt-file` | Load additional system prompt text from a file |
| `--autocompact <auto\|tokens>` | Set the auto-compact window for this session |
| `--ax-screen-reader` | Render screen-reader friendly output |
| `--bare` | Minimal mode: skip CLAUDE.md / hooks / skills / plugins / MCP discovery |
| `--betas` | Beta headers to include in API requests |
| `--bg`, `--background` | Start the session as a background agent |
| `--channels` | MCP servers whose channel notifications Claude should listen for |
| `--chrome` | Enable Chrome browser integration |
| `--cloud` | Create a web session on claude.ai |
| `--continue`, `-c` | Load the most recent conversation in the current directory |
| `--dangerously-load-development-channels` | Enable channels not on the approved allowlist |
| `--dangerously-skip-permissions` | Skip permission prompts (equivalent to bypassPermissions mode) |
| `--debug` | Enable debug mode with optional category filtering |
| `--debug-file <path>` | Write debug logs to a specific file path |
| `--disable-slash-commands` | Disable all skills and commands for this session |
| `--disallowedTools`, `--disallowed-tools` | Deny rules for tools |
| `--effort` | Set the effort level (`low`, `medium`, `high`, `xhigh`, `max`, `ultracode`) |
| `--enable-auto-mode` | Removed in v2.1.111. Use `--permission-mode auto` |
| `--environment <environment-id>` | Create a new cloud session on the named environment |
| `--exclude-dynamic-system-prompt-sections` | Move per-machine sections into the first user message |
| `--exec` | Run a shell command as a PTY-backed background job |
| `--fallback-model` | Enable automatic fallback to the specified model(s) |
| `--fork-session` | When resuming, create a new session ID instead of reusing the original |
| `--forward-subagent-text` | Emit subagent text and thinking blocks in the output stream |
| `--from-pr` | Open the session picker filtered to sessions linked to a PR |
| `--ide` | Automatically connect to IDE on startup |
| `--init` | Run Setup hooks with the `init` matcher before the session |
| `--init-only` | Run Setup + SessionStart hooks, then exit |
| `--include-hook-events` | Include hook lifecycle events from every hook in output |
| `--include-partial-messages` | Include partial streaming events in output |
| `--input-format` | Specify input format for print mode (`text` or `stream-json`) |
| `--json-schema` | Get validated JSON output matching a JSON Schema |
| `--maintenance` | Run Setup hooks with the `maintenance` matcher |
| `--max-budget-usd` | Maximum dollar amount to spend on API calls |
| `--max-turns` | Limit the number of agentic turns (print mode only) |
| `--mcp-config` | Load MCP servers from JSON files or strings |
| `--model` | Set the model (`sonnet`, `opus`, `haiku`, `fable`, or full name) |
| `--name`, `-n` | Set a display name for the session |
| `--no-chrome` | Disable Chrome browser integration |
| `--no-session-persistence` | Disable session persistence (print mode only) |
| `--output-format` | Specify output format for print mode (`text`, `json`, `stream-json`) |
| `--permission-mode` | Begin in a specified permission mode |
| `--permission-prompt-tool` | Specify an MCP tool to handle permission prompts |
| `--plugin-dir` | Load a plugin from a directory or .zip archive |
| `--plugin-url` | Fetch a plugin .zip archive from a URL |
| `--print`, `-p` | Print response without interactive mode |
| `--prompt-suggestions` | Emit a `prompt_suggestion` message after each turn |
| `--ref <branch>` | With `--environment`, base the new session's checkout on a named ref |
| `--remote` | Deprecated alias for `--cloud` |
| `--remote-control`, `--rc` | Start an interactive session with Remote Control enabled |
| `--remote-control-session-name-prefix` | Prefix for auto-generated Remote Control session names |
| `--replay-user-messages` | Re-emit user messages from stdin back on stdout |
| `--resume`, `-r` | Resume a specific session by ID or name |
| `--safe-mode` | Start with all customizations disabled |
| `--session-id` | Use a specific session ID for the conversation |
| `--setting-sources` | Comma-separated list of setting sources to load |
| `--settings` | Path to a settings JSON file or an inline JSON string |
| `--strict-mcp-config` | Only use MCP servers from `--mcp-config` |
| `--system-prompt` | Replace the entire system prompt with custom text |
| `--system-prompt-file` | Load system prompt from a file |
| `--teleport` | Resume a web session in your local terminal |
| `--teammate-mode` | Set how agent team teammates display (`in-process`, `auto`, `tmux`, `iterm2`) |
| `--tmux` | Create a tmux session for the worktree |
| `--tools` | Restrict which built-in tools Claude can use |

## CortexAgent's flags of choice

```bash
# Subagent spawn (lib/overseer._spawn_subagent):
claude -p "<prompt>" \
    --model sonnet \
    --output-format text \
    --bare \
    --dangerously-skip-permissions
```

- `-p` non-interactive (subagent is short-lived)
- `--model sonnet` (or `opus` for LLM_REASONING workflow tasks)
- `--output-format text` parseable output
- `--bare` skips CLAUDE.md (we don't ship one), hooks, skills, MCP auto-discovery
- `--dangerously-skip-permissions` no waiting on user mid-batch
