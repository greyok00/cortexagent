# CortexAgent — local coding agent on llama.cpp. No cloud.

## Response Style (HARD)
Default to visual, scannable output. Favor in order: 📊 Tables > 📈 Charts > ✅ Checklists > 📋 Lists > 🎨 Emoji markers.
- Never dump raw tool call names — explain in plain language.
- Use 🔴🟡🟢 for status, 📦🔥📋 for memory tiers.
- Keep compact — one line per item, truncate with ….
- End with STATE block (under 150 tok) for substantive work.

## UI / Output Guidelines (HARD)
The CortexAgent terminal is a locked-screen TUI (no scroll); the banner
(`lib/banner.py`) and statusLine (`lib/statusline.py`) are the brand surfaces.
- **Hide code by default.** Show minimal snippets only — reference `file:line`
  instead of pasting whole files. Never dump a file you didn't change.
- **No code-dumps.** If a change is mechanical (rename, sweep), summarize it;
  show one representative diff hunk, not every occurrence.
- **Terse, outcome-first.** Lead with what changed + verification, not the
  journey. One-line per item.
- **Terminal animation house style** (for any in-process CLI/TUI we build):
  overwrite in place with `\033[H` — never `clear`/`\033[2J` (it strobes);
  every line ends with `\033[K` so shorter frames leave no residue; keep
  frames a uniform line count; hide the cursor (`\033[?25l`) during an
  animation and restore (`\033[?25h`) on exit.

## Rules
- No `/home/<user>` in code; use env vars.
- No push/publish/delete without approval.
- No screenshots/image-gen/analysis.
- Report failures plainly.
- Shares CortexLLM memory with all platforms (Claude Code, OpenClaw, etc.).
- Don't run tools unprompted; don't re-derive established facts.

## Context
- Read once; prefer Grep/Glob over full reads.
- Summarize/save large outputs to memory.
- Web: `brave_fetch` for JS-heavy; WebFetch/WebSearch fallback.
- Reference: `config/AGENT.md` (on demand).

## Memory
- Auto-saved each turn to both cortexagent DB + shared CortexLLM.
- Injected on start from both sources (dual-read).
- `mcp__cortexllm__memory_*` for durable facts (shared across all platforms).
- Keep entries short; auto-prune/dedup.

## Tools
- **Workflow Engine** (`engine/`): DAG-based 5-stage pipeline. Import: `from engine import WorkflowEngine`. Use for multi-step tasks (website builds, research, API dev).
- **Coding Practices DB** (`Coding_Practices` table): 107 practices, 30 categories, 7 sources. Query: `sqlite3 ~/.config/cortexllm/cortexllm.db "SELECT practice, description FROM Coding_Practices WHERE category='Input Validation' ORDER BY priority;"`.
- **Model Stack** (`config/MODELS.md`): 🧠 Qwen3.6-35B (14.3GB) on llama-server; 🎨 SD1.5/SDXL + 🎬 LTX-Video via **in-process diffusers** (`lib/diffusion_backend.py`, #33) — diffusion shares the GPU, no LLM swap. cuDNN off by default (`CORTEXAGENT_DIFFUSION_CUDNN=0`).

## Hard Rules → Cold Memory (HARD)
When user states a rule/constraint/directive:
1. Save to cold memory via `memory_write` (tier=cold, category=agent_critical_rules, priority=critical).
2. Include exact wording + context + why it matters.
3. Do NOT edit CLAUDE.md — cold memory is source of truth.
4. Startup scans cold memory and displays rules automatically.

## Session Resume (HARD)
First message in new session is "continue"/"go"/"retry"/"resume" or implies picking up work:
1. Read hot memory from shared CortexLLM (mcp__cortexllm__memory_read tier=hot platform=cortexagent) for last 5+ user prompts.
2. Quote the last user prompt verbatim.
3. Summarize what was being worked on.
4. Ask what to do next.
Do NOT ask "what were we working on?" — read memory and report.
