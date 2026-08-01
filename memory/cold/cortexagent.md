# CortexAgent — runtime
Local coding agent (GreyOK00): Claude Code CLI on local llama.cpp Qwen3.6-35B-A3B (IQ3_S, ~14GB VRAM). No cloud/API key. Brand: CortexAgent.

Self-contained: own CLAUDE.md/memory/config; excludes global `~/.claude/CLAUDE.md`. Auto-recovery via `SessionStart` (startup|clear|compact) injects recent CortexAgent memory; auto-save via `UserPromptSubmit`+`Stop` through the `memory_manager.add_message` pipeline.
