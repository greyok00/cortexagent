# CortexAgent — Output Rules & Overseer Token-Opt Design (Aug 10)

**Status:** Draft for user review · **Date:** 2026-08-10 12:55

This document captures the **new rules** you just defined + the **existing
token-opt rules** already in the overseer that must be preserved. It's the
source of truth for the implementation in actions 1-11 of the changelog.

---

## 🎯 NEW RULES (today, 2026-08-10)

### R1 — No TUI, just CLI
- Drop the `--tui` / `-t` opt-in flag from `bin/cortexagent`.
- Delete `lib/tui.py` (or keep as deprecated stub?) — code is uncommitted.
- Default: `cortexagent` launches `claude` (the agent CLI) directly.
- Interactive UI is provided exclusively by the **8090 webui**.

### R2 — Code is hidden by default
- Every code block in the LLM's output is replaced with a collapsed card:
  `[code: python · 47 lines · python3 file.py to run]`
- User must say "show code" / "with code" / "include code" in the prompt,
  or use `-p` with explicit `code:` directive, to reveal raw code.
- Implementation: `lib/response_model.py` already has `ArtifactBlock` /
  `Collapse()`. Replace the visible-artifact threshold to 0 by default;
  gate `0 → show` behind a per-request flag carried in the body.

### R3 — Thinking goes under the response as a CLI bottom line
- Plain CLI: every response is followed by `_` divider + thinking line:
  ```
  [main response here]
  _
  ▎ thinking: searched 3 files · ran bash `ls -la` · used Read tool (5s)
  ```
- ANSI only, no TUI. Works in any terminal. No scroll-jank.
- Implementation: proxy emits the divider + line via stderr after the
  response stream closes; captured from tool-use events already in the
  proxy's token-metrics buffer.

### R4 — Output is also minified via the proxy
- Currently `lib/grammar_proxy.py` minifies the **request** (input).
- Add response-side minify: collapse repeated tool-output blocks, strip
  model-generated filler ("Sure!", "Here is the code:", "Let me know..."),
  compress long tables to diff-style.
- Slimtoken has `minify_request` only; use a thin local helper (in
  `lib/response_model.py` we already have `sanitize_terminal` + `collapse`).
  Wire `collapse(blocks)` and a new `minify_response(body) → minified_body`
  into the proxy's response path.

### R5 — Tables / charts / graphs / imagery are the default rendering
- Any markdown table → box-drawn aligned table (already in `format_visual`).
- Any numeric column → `█` bar chart (already in `format_visual`).
- ASCII art preserved unwrapped (already in `format_visual`).
- `#` heading → `▎` accent (already in `format_visual`).
- Imagery (image_gen / image_edit results) → inline `[image: <path> · 512×512]`
  link, user opens to view.
- Always on for plain CLI; no `--no-format` escape needed.

### R6 — Overseer asks clarifying questions when ambiguous
- Overseer (tiny LFM2.5-1.2B) classifies every prompt via `pre_flight_gate`.
- If ambiguous → big model is told to ask a clarifying question instead of
  guessing. The clarifying question is presented to the user as normal output.
- "When ambiguous" rule = call the tiny model first, fall back to big only
  when tiny classifies as unambiguous.
- Implementation: `pre_flight_gate` already has rule-based intent classifier
  + cached-response check; extend with "ambiguity" branch that returns a
  AskUserQuestion-style prompt before reaching big.

### R7 — Big model stays loaded (vision + chat at all times)
- `big_idle_unload_sec = 0` (or remove the idle-unload watcher entirely).
- Big is multimodal → handles all vision natively.
- Big orchestrates image/video gen via diffusers in-process (no separate
  vision port, no separate model).

---

## 📜 EXISTING TOKEN-OPT RULES (must preserve — DO NOT DUPLICATE)

I've enumerated all current token-optimization rules across the codebase.
**Treat this as the canonical list — if a "new" rule overlaps one of these,
fold them, don't add new code.**

### O1 — Input minify (proxy, request-side)
- **Location:** `lib/grammar_proxy.py:25-95` + `lib/minify/pipeline.py`
- **Backend:** slimtoken (primary) → lib.minify (fallback) → none
- **Stages (in order):**
  1. `tools` — balanced tool-def minify
  2. `system` — fence-aware system-prompt minify
  3. `messages` — code-aware text-block minify (tool I/O untouched)
  4. `dom` (opt-in) — prune big HTML tool_results
  5. `budget` — drop oldest safe messages if over token_budget (last)
- **Slimtoken adds:** `dedup` (repeated tool results) + `distill` (old turns)
- **Budget backstop:** 131072 tokens (slimtoken) — hard ceiling at server cap
- **Env knobs:** `CORTEXAGENT_MINIFY`, `CORTEXAGENT_MINIFY_TOOL_SKIP`,
  `CORTEXAGENT_MINIFY_BUDGET`, `CORTEXAGENT_MINIFY_DOM`,
  `CORTEXAGENT_MINIFY_DEDUP_MIN`, `CORTEXAGENT_MINIFY_DISTILL_MAX`
- **Stats:** `MinifyStats` tracks tokens_in, tokens_out, tools_minified,
  system_minified; exposed via `/metrics` endpoint

### O2 — Context pruning (`lib/context_pruner.py`)
- **Method:** Token-budget context pruning (RAG-style retrieval,
  sliding-window). Stdlib only.
- **LOW_VALUE_PATTERNS stripped:** filler phrases ("I think", "Basically",
  "Honestly"), ≥3 repeated punctuation, ≥4 newlines, leading/trailing whitespace
- **Metadata stripped from memory entries:** `id`, `tokens_in`, `tokens_out`,
  `metadata`, `platform`
- **CLI:** `python3 context_pruner.py smoke | prune --cold-file --warm-file [--query]`

### O3 — DOM pruning (`lib/dom_pruner.py`)
- **Pipeline:** Strip non-semantic tags → strip low-value sections (nav,
  footer, sidebar) → strip non-semantic attrs (class, id, aria-*, data-*)
  → collapse to visible text → session-aware LRU cache (clear on task boundary)
- **Max entries:** 100

### O4 — Pre-flight gate (`lib/pre_flight_gate.py`)
- **Pre-LLM gates:** rule-based intent classifier, cached-response check
  (reads in-repo SQLite hot memory), model-capability override table
  (env-driven), budget check (token budget counter, advisory)
- **Claude Code** handles its own schema, iteration control, file-type routing
- **CLI:** `python3 pre_flight_gate.py check | intent | cached | smoke`

### O5 — Output formatting (`lib/response_model.py`)
- `sanitize_terminal()` — strip SGR/OSC/cursor/bracket-paste/2-byte ESC/BEL/BS/SI
- `parse_response()` — fence-aware block extraction (Text, CodeArtifact, Tool, Disclosure)
- `collapse()` — keep first 1500 chars of text visible, tail into `[Details (N)]`,
  first 4 artifacts visible, rest `[Code artifacts (N)]`, first 8 tool events,
  rest `[Tool activity (N)]`
- `format_visual()` — markdown tables → box-drawn, numeric → `█` charts,
  ASCII preserved, `#` → `▎` accent
- `render_plain()` — width-aware word-wrap

### O6 — Context-window monitor + failsafe (`lib/overseer.py`)
- **Warn at ≥88% ctx used** (yellow alert)
- **Failsafe at ≥95% sustained 3 ticks (~90 s)** → force session-reset
- **Resets counter** when below threshold
- **Output:** "CONTEXT WINDOW at 95%..." / "Context window at 88%..."

### O7 — Stale-session self-heal (`lib/daemon.py`)
- If `active_sessions > 0` AND no request for `stale_session_sec=1800` →
  auto-release sessions so idle-unload can free VRAM
- **Env knob:** `CORTEXAGENT_STALE_SESSION_SEC`

### O8 — Banner safety (`lib/banner.py`)
- Frame-uniform: every frame has same line count (LOG + 2 tagline rows)
- Padded to LOGO_W with spaces
- Cursor-positioned fragments with `\033[H` (overwrite, never `clear`)
- Each line ends with `\033[K` (no residue)
- Banner is the BRAND surface, never randomized

### O9 — Heartbeat daemon (`lib/heartbeat_service.py`)
- **Runs every 30 s** via tiny LFM2.5-1.2B
- Monitors memory pressure (hot/warm/cold counts)
- Auto-compacts warm memory at 85% cap
- Cold-distills warm entries periodically
- Tiny LLM calls for periodic health summaries

### O10 — Memory safety (`lib/cold_distiller.py`, `lib/loop_guard.py`,
  `lib/anti_hallucination.py`, `lib/post_response_verifier.py`)
- LLM-based cold distillation into facts
- Loop guard breaks infinite tool-call loops
- Anti-hallucination pre-check on model output
- Post-response verifier: schema validation, retry-once on failure

### O11 — Hard rules from `config/CLAUDE.md` (already loaded into agent)
- Visual scannable output (tables/charts/checklists)
- Hide code by default (already in CLAUDE.md — R2 enforces it in CLI too)
- No code-dumps (already in CLAUDE.md)
- Terse, outcome-first
- Compact one-liner per item, truncate with …
- STATE block under 150 tok for substantive work

### O12 — Memory hygiene (`config/CLAUDE.md` + CortexLLM)
- Auto-saved each turn to shared CortexLLM
- Keep entries short; auto-prune/dedup
- Uses `mcp__cortexagent__memory_read` for resume (NOT local files)

### O13 — Tool-result dedup (slimtoken)
- `dedup_tool_results` — repeated identical tool outputs collapse to one
- `distill_old_turns` — old multi-turn conversations summary-compressed
- `dedup_min_chars=200`, `distill_max_chars=240` (defaults)

### O14 — Document fetchers (`lib/pdf_knowledge.py`, `lib/fast_extract.py`)
- `fast_extract` — fast text extraction from web pages (uses brave_fetch)
- `pdf_knowledge` — PDF text extraction with chunk awareness
- Both feed into the same minify pipeline

### O15 — Plugin isolation (`lib/lazy_mcp_proxy.py`)
- MCP servers loaded only when called (not in every prompt tool context)
- Generic lazy proxy: any personal MCP server added to
  `~/.cortexagent/config/lazy_mcp_servers.json` only loads on call

---

## 🛠️ IMPLEMENTATION PLAN (effects on existing code)

| New rule | Affects existing rule(s) | What to do |
|----------|--------------------------|------------|
| R1 (no TUI) | n/a | Drop `--tui` from `bin/cortexagent`. Delete `lib/tui.py` (or keep untracked). |
| R2 (hide code) | O5 (collapse) already hides artifacts after 4 | Change visible_artifacts default to 0; add a `show_code` flag in request that bumps to N for that request only. |
| R3 (thinking bottom CLI) | n/a | Proxy emits `_\n▎ thinking: ...` to stderr after response stream closes. Source from existing tool-event buffer. |
| R4 (output minify) | O1 (input minify) | New `minify_response(body)` in proxy: runs collapse(R2) + strip filler phrases + dedup table rows. Slimtoken has no response minify → local helper. |
| R5 (tables/charts default) | O5 (format_visual exists) | Flip from opt-in to always-on. Remove `--format` flag wiring (already in `bin/cortexagent`). |
| R6 (ask when ambiguous) | O4 (pre-flight gate) | Extend `pre_flight_gate.check()` to flag ambiguous prompts → return clarification prompt instead of passing to big. |
| R7 (big always loaded) | O6 (context monitor) + O7 (stale self-heal) | Set `idle_unload_sec = 0` (or O6+O7 short-circuit). Monitor still useful but never triggers unload. |

### SPEC RULES THAT BECOME OBSOLETE
- ❌ **Tray pop-out dashboard** (ruled out 2026-08-10 12:50) — tray = click-to-launch 8090
- ❌ **SmolVLM2 vision bridge** (ruled out earlier) — big is multimodal
- ❌ **Whisper audio** (ruled out) — no separate models
- ❌ **2-pass prompt optimizer** (ruled out) — slimtoken minify + big covers it
- ❌ **Separate qwen3vl-8b server** (ruled out) — big handles vision

---

## ✅ Action plan becomes (after applying these rules)

| # | Action | Files |
|---|--------|-------|
| 1 | `.gitignore` — `*.bak*`, `*.pre-wolf-*` | `.gitignore` |
| 2 | Empty `big_model` default | `lib/config.py:241` |
| 3 | Remove `vision_*` defaults | `lib/config.py:252-262` |
| 4 | `big_idle_unload_sec = 0` | `lib/config.py`, `lib/daemon.py` (confirm short-circuit) |
| 5 | Strip `:8083`/`qwen3vl`/`vision` refs | `lib/webui.py`, `lib/tray.py`, `lib/img2img.py` |
| 6 | Drop `--tui` flag from wrapper | `bin/cortexagent` |
| 7 | Update `lib/response_model.py` — flipping R2 (default hidden code) + R5 (always format) | `lib/response_model.py` |
| 8 | Add `minify_response()` to proxy | `lib/grammar_proxy.py` (new function) |
| 9 | Add thinking-bottom-line to proxy stream | `lib/grammar_proxy.py` (stderr emit) |
| 10 | Extend `pre_flight_gate` with ambiguous-prompt → clarification branch | `lib/pre_flight_gate.py` |
| 11 | Tray → click launches 8090 (no separate dashboard) | `lib/tray.py` menu |
| 12 | Update README + MODELS.md | `README.md`, `config/MODELS.md` |
| 13 | Smoke tests for all new behavior | `tests/run_smoke.py` |
| 14 | `cortexagent doctor` + full smoke → MUST pass | shell |
| 15 | Commit everything as ONE ready-for-GitHub commit | git |
| 16 | Overseer tool-call research (separate) | web |

---

## 📌 Tracking

- This file = `docs/superpowers/specs/2026-08-10-output-rules-design.md`
- Master changelog = `docs/superpowers/specs/2026-08-10-daily-changelog.md`
- Every commit appends a ✅ row to DONE table. Every cancellation gets a REMOVED row.
