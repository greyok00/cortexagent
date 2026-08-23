# Claude Code Hooks Reference

> Source: https://code.claude.com/docs/en/hooks.md
> Pulled 2026-08-11

Hooks are user-defined shell commands, HTTP endpoints, MCP tool calls, or LLM
prompts that execute automatically at specific points in Claude Code's
lifecycle.

## Hook Lifecycle

- **Once per session**: `SessionStart`, `SessionEnd`
- **Once per turn**: `UserPromptSubmit`, `Stop`, `StopFailure`
- **On every tool call**: `PreToolUse`, `PostToolUse` (except `EndConversation`)

## Hook Events

| Event | When it fires |
|:------|:--------------|
| `SessionStart` | When a session begins or resumes |
| `Setup` | When starting with `--init-only`, `--init`, or `--maintenance` in `-p` mode |
| `UserPromptSubmit` | When you submit a prompt, before Claude processes it |
| `UserPromptExpansion` | When a user-typed command expands into a prompt; can block the expansion |
| `PreToolUse` | Before a tool call executes. Can block it |
| `PermissionRequest` | When a tool call needs a permission decision |
| `PermissionDenied` | When a tool call is denied by the auto mode classifier. Return `{retry: true}` to allow retry |
| `PostToolUse` | After a tool call succeeds |
| `PostToolUseFailure` | After a tool call fails |
| `PostToolBatch` | After a full batch of parallel tool calls resolves |
| `Notification` | When Claude Code sends a notification |
| `MessageDisplay` | While assistant message text is displayed |
| `SubagentStart` | When a subagent is spawned |
| `SubagentStop` | When a subagent finishes |
| `TaskCreated` | When a task is being created via `TaskCreate` |
| `TaskCompleted` | When a task is being marked as completed |
| `Stop` | When Claude finishes responding |
| `StopFailure` | When the turn ends due to an API error |
| `TeammateIdle` | When an agent team teammate is about to go idle |
| `InstructionsLoaded` | When a CLAUDE.md or `.claude/rules/*.md` file is loaded |
| `ConfigChange` | When a configuration file changes during a session |
| `CwdChanged` | When the working directory changes |
| `DirectoryAdded` | When a working directory is added mid-session |
| `FileChanged` | When a watched file changes on disk |
| `WorktreeCreate` | When a worktree is being created |
| `WorktreeRemove` | When a worktree is being removed |
| `PreCompact` | Before context compaction |
| `PostCompact` | After context compaction completes |
| `Elicitation` | When an MCP server requests user input during a tool call |
| `ElicitationResult` | After a user responds to an MCP elicitation |
| `SessionEnd` | When a session terminates |

## Hook Resolves — Example

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(rm *)",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh",
            "args": []
          }
        ]
      }
    ]
  }
}
```

Resolution flow:
1. Event fires (`PreToolUse` sends tool input as JSON on stdin)
2. Matcher checks (`"Bash"` matches the tool name)
3. If condition checks (`"Bash(rm *)"` matches the subcommand)
4. Hook handler runs (script inspects command, returns decision)
5. Claude Code acts (blocks the tool call, shows Claude the reason)

## Configuration

Three levels of nesting:
1. Choose a **hook event** (e.g., `PreToolUse`, `Stop`)
2. Add a **matcher group** to filter when it fires (e.g., "only for Bash")
3. Define one or more **hook handlers** to run when matched

### Hook Locations

| Location | Scope | Shareable |
|:---------|:------|:----------|
| `~/.claude/settings.json` | All your projects | No, local to machine |
| `.claude/settings.json` | Single project | Yes, commit to repo |
| `.claude/settings.local.json` | Single project | No, gitignored |
| Managed policy settings | Organization-wide | Yes, admin-controlled |
| Plugin `hooks/hooks.json` | When plugin enabled | Yes, bundled |
| Skill/agent frontmatter | While component active | Yes, in component file |

## Matcher Patterns

| Matcher value | Evaluated as |
|:--------------|:-------------|
| `"*"`, `""`, or omitted | Match all |
| Letters, digits, `_`, `-`, spaces, `,`, `\|` | Exact string or list |
| Contains any other character | JavaScript regular expression, unanchored |

### MCP tools

MCP tools follow `mcp__<server>__<tool>` pattern:
- `mcp__memory__create_entities`
- `mcp__filesystem__read_file`
- `mcp__github__search_repositories`

Match every tool from a server: `mcp__memory__.*` (the `.*` is required)

### Match by Event Type

| Event | What the matcher filters |
|:------|:-------------------------|
| `PreToolUse`, `PostToolUse` | tool name |
| `SessionStart` | how session started (`startup`, `resume`, `clear`, `compact`, `fork`) |
| `SessionEnd` | why session ended (`clear`, `logout`, `prompt_input_exit`) |
| `Notification` | notification type |
| `SubagentStart`/`SubagentStop` | agent type |
| `PreCompact`/`PostCompact` | trigger |

## Hook Handler Types

- **`command`** — run a shell command
- **`http`** — POST to an HTTP endpoint
- **`mcp_tool`** — call an MCP server tool
- **`prompt`** — send to a Claude model for yes/no evaluation
- **`agent`** — spawn a subagent to verify conditions (experimental)

All matching hooks run in parallel. The same handler defined in multiple
settings files runs once.

## Exit Codes

- **Exit 0** — Success. Stdout parsed for JSON output fields
- **Exit 2** — Blocking error. Stderr fed back to Claude; blocks the action
- **Any other exit code** — Non-blocking error. Action proceeds; stderr logged

### Exit Code 2 Blocking Behavior

| Event | Can block? | Effect on exit 2 |
|:-------|:-----------|:-----------------|
| `PreToolUse` | Yes | Blocks the tool call |
| `PermissionRequest` | Yes | Denies the permission |
| `UserPromptSubmit` | Yes | Blocks prompt processing, erases prompt |
| `Stop` | Yes | Prevents Claude from stopping |
| `PostToolUse` | No | Shows stderr to Claude; tool already ran |

> ⚠️ For most events, only exit code 2 blocks. Exit 1 is non-blocking.

## CortexAgent's relationship

CortexAgent's `bin/cortexagent` configures 3 hooks in the isolated config dir
(`~/.cortexagent-config/settings.json`):

- `SessionStart` (auto-injects memory)
- `UserPromptSubmit` (saves prompt to CortexAgent via cortexagent_call.py)
- `Stop` (cleanup)

The config dir is generated fresh from `config/settings.json.template` every
launch, so hook changes flow through the template (not via this doc).
