# Claude Code Plugins Reference

> Source: https://code.claude.com/docs/en/plugins-reference.md
> Pulled 2026-08-11
> Full content (88 KB) saved to:
> ~/.claude/projects/-home-grey/07fc395c-c92e-4395-8d07-9777db5fb74b/tool-results/call_1ed2e491a0fa41a382d14cbd.txt

## Overview

A **plugin** is a self-contained directory of components that extends Claude
Code with custom functionality. Components include:

- skills (`/name` shortcuts)
- agents (subagents)
- hooks (event handlers)
- MCP servers
- LSP servers
- monitors

## Plugin components reference

### Skills

Plugins add skills to Claude Code, creating `/name` shortcuts that you or
Claude can invoke.

**Location**: `skills/` or `commands/` directory in plugin root, or a single
`SKILL.md` file at the plugin root.

**Structure**:

```text
skills/
├── pdf-processor/
│   ├── SKILL.md
│   ├── reference.md (optional)
│   └── scripts/ (optional)
└── code-reviewer/
    └── SKILL.md
```

Skills are automatically discovered when the plugin is installed.

If a plugin has no `skills/` directory and no `skills` manifest field, a
`SKILL.md` at the plugin root is loaded as a single skill. Set the frontmatter
`name` field to control the skill's invocation name. Without it, Claude Code
falls back to the install directory name, which for marketplace-installed
plugins is a version string that changes on every update.

For plugins that ship more than one skill, use the `skills/` directory layout.

## Plugin installation

```bash
claude plugin install code-review@claude-plugins-official
```

Aliases: `claude plugins` (plural also works).

## CortexAgent's relationship

CortexAgent ships its own skill: `superpowers:llm-optimize-layer` (in
`~/.claude/plugins/`). It's used by the model to optimize token usage before
requesting slimtoken. The plugin is standalone — not packaged as a cortexagent
plugin (we don't use claude's plugin mechanism).

## Marketplace reference (truncated in upstream)

Plugins are distributed via marketplaces (`/docs/en/plugin-marketplaces`).
Marketplaces can be private (your org) or public (`claude-plugins-official`).

## Full reference

For the complete plugin manifest schema, see the upstream doc (88 KB).
