# Claude Code Interactive Mode

> Source: https://code.claude.com/docs/en/interactive-mode.md
> Pulled 2026-08-11
> Full content saved to: ~/.claude/projects/-home-grey/07fc395c-c92e-4395-8d07-9777db5fb74b/tool-results/call_5751350611dd4f57840c2db9.txt

## Keyboard shortcuts

Keyboard shortcuts may vary by platform and terminal. In fullscreen rendering,
press `?` in the transcript viewer to see available shortcuts.

### macOS Option/Alt as Meta

Option/Alt key shortcuts (`Alt+B`, `Alt+F`, `Alt+Y`, `Alt+P`) require configuring
Option as Meta in your terminal:

- **iTerm2**: Settings → Profiles → Keys → General → set Left/Right Option key to "Esc+"
- **Apple Terminal**: Settings → Profiles → Keyboard → check "Use Option as Meta Key"
- **VS Code**: set `"terminal.integrated.macOptionIsMeta": true` in VS Code settings

### General controls (full table upstream)

Includes standard text editing shortcuts (line navigation, word jumps, undo,
delete), session controls (`Ctrl+C` interrupt, `Esc Esc` rewind menu,
`Ctrl+L` clear), and prompt-bar controls.

## CortexAgent's relationship to interactive mode

CortexAgent subagents run via `claude -p` (print mode) — never interactive.
The tray popout + webui are the interactive surfaces, written by cortexagent
itself, not by claude. So this doc is reference-only — we don't depend on
specific interactive shortcuts.

If the bin/cortexagent wrapper ever re-launches an interactive claude session,
the relevant shortcuts are: `Ctrl+C` interrupt, `Esc Esc` rewind, `?` help in
fullscreen.
