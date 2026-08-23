# Claude Code Tools Reference

> Source: https://code.claude.com/docs/en/tools-reference.md
> Pulled 2026-08-11
> Full content saved to: ~/.claude/projects/-home-grey/07fc395c-c92e-4395-8d07-9777db5fb74b/tool-results/call_b34292221ef24c3ea4814ed0.txt
> (size 86 KB — too large to inline here without re-fetching)

## Tools available in Claude Code

The full built-in tool list (Read, Write, Edit, Bash, Grep, Glob, WebFetch,
WebSearch, TodoWrite, Task, etc.) is in the upstream doc. Tool names are the
exact strings used in:

- permission rules (`/docs/en/permissions#tool-specific-permission-rules`)
- subagent tool lists (`/docs/en/sub-agents`)
- hook matchers (`/docs/en/hooks`)

To add custom tools, connect an MCP server. To extend Claude with reusable
prompt-based workflows, write a skill (runs through the existing `Skill` tool).

## Permission semantics

The `Permission required` column shows whether the tool prompts in the default
permission mode for paths inside the working directory. File-access tools
marked No (`Read`, `Grep`, `Glob`) still prompt for paths outside the working
directory and additional directories. `Bash` is marked Yes but runs a built-in
set of read-only commands without prompting.

## CortexAgent's tool restriction pattern

Subagents spawned by `lib/overseer._spawn_subagent` use `--bare` which leaves
Bash, Read, Write, Edit (the default tools). To restrict further, pass
`--tools "Bash,Read"` etc. via the subagent prompt kwargs.
