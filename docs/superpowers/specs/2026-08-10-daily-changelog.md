# CortexAgent — Condensed Plan (Aug 9 + Aug 10 + Aug 11)

**Owner:** grey · **Last updated:** 2026-08-11 · **Status:** 🟢 active

Append-only daily log. Latest entries supersede prior ones. Aug 8 ignored
per user (2026-08-10). Each item: **what**, **files**, **why**, **status**.

---

## 🎯 ACTIVE PLAN (Aug 11 — supersedes everything below)

### UI separation: tray popout ACTIVE, :8090 webui DEFERRED
User pivot 2026-08-11: "the system tray popout UI for the overseer model is
NOT the same thing. do not mix them up."

| UI | Status | Reason |
|---|---|---|
| Tray popout dashboard (`lib/tray_dashboard.py`) | ✅ **ACTIVE** | Local, stdlib-only, no extra deps. Shows overseer state + big-model step counter + idle tip. |
| :8090 webui | ⏸️ **DEFERRED** | Not a core feature until CLI is 100%. tui/streaming block cards stay local-only until then. |
| Tray click → launch 8090 | ❌ **REMOVED** | Was confusing tray popout with webui. Menu still offers both, but they're separate. |

### Big model behavior
- Live install uses **Qwen3.6-35B-A3B UD-IQ3_S** (UD uncensored fine-tune, 13 GB).
- github copy at `/home/grey/cortexagent-github/` uses base **IQ3_S** (no UD).
- **No fallback model** — both copies ship `fallback_model = ""`. User: "I just want the UD model."
- `idle_unload_sec = 0` — big stays loaded.

### Branding
- "CortexAgent by GreyOK00" in `bin/cortexagent:2`, `README.md:7`, and `lib/config.py:355` (author default).
- Authorship strings are NOT PII — PII exclude covers README.md + bin/cortexagent.

### Overseer watchdog
- Requires BOTH signals before unloading big on apparent CLI close: no `bin/cortexagent` process AND daemon idle > 300s (or active_sessions == 0). Prevents webui-only sessions from false-positive unload.

---

## 🎯 ACTIVE PLAN (today's latest decisions supersede everything)

### Pipeline topology (3 components only)

| Component | Choice | Notes |
|-----------|--------|-------|
| Big model | **Qwen3.6-35B-A3B UD-IQ3_S** (13 GB, :8080) | Already loaded + serving. "UD" = Uncensored/Distilled community fine-tune of Qwen3-VL family. **Multimodal** — handles vision natively. |
| Overseer (tiny) | **LFM2.5-1.2B Q4_K_M** (728 MB, :8082) | Always-on sidecar; tool-calling capable. Candidate swap research pending. |
| Fallback | **LFM2.5-8B-A1B Q4_K_M** (~6.7 GB) | MoE + Mamba-2 hybrid; only loaded if big can't fit. |
| Image/video gen | **diffusers in-process** (`lib/diffusion_backend.py`) | SD1.5/SDXL/LTX; cuDNN off. |
| ~~Separate qwen3vl-8b~~ | ❌ **DROPPED** | Big is already multimodal. No separate vision port. |
| ~~Whisper / SmolVLM / optimizer~~ | ❌ **DROPPED** | Not implementing. Qwen 3.6 + diffusers cover the use cases. |

### Single dashboard
- **8090 = the only webui.** No second web port. No second dashboard.
- **TUI = opt-in only** (`cortexagent --tui` / `-t`). Default `cortexagent` = plain CLI.
- **Tray** = just a tray icon (wolf head) + click-to-launch 8090 webui. Owns the overseer process. Not a parallel dashboard.
- No pop-out 360×360 square, no separate tray chat. The webui IS the dashboard.

### Big model behavior
- **`big_idle_unload_sec = 0`** — big stays loaded forever (user: "keep it loaded at all times"). User sees the daemon's auto-swap as bad UX; paying ~14 GB to keep big resident is fine.
- Big is multimodal → handles ALL vision (image understanding + orchestration of image/video gen via tool calls).

### GitHub defaults (safe for new users)
| Field | Ship default | Reason |
|-------|-------------|--------|
| `big_model` | `""` (must-configure) | Forces new user to set it in `cortexagent.conf` or `CORTEXAGENT_MODEL` env. No wrong assumption about GPU capability. |
| `fallback_model` | `lfm2.5-8b-a1b/...` | Already shipped, fine. |
| `tiny_model` | `lfm2.5-1.2b/...` | Already shipped ("overseer fine to add" — small enough). |
| `vision_*` | **REMOVED** | Drop entire `[vision]` block. Remove `:8083`, qwen3vl references in webui/tray/img2img. |
| `big_idle_unload_sec` | **0** (disabled) | Big stays loaded. |

### Overseer model swap goal
User: "find a better overseer model to match it." Target = tool-calling specialist. Research pending; candidates to evaluate (no work yet):
- lfm2.5-1.2b (current — tool-call native, 728 MB, fine for now)
- Qwen2.5-1.5B-Instruct (better instruction following, ~1.5 GB)
- Qwen2.5-Coder-1.5B (coding-tuned, may help when overseer writes code)
- llama-3.2-3b-instruct (~2 GB, strong tool use)
- Hermes-3-2B, Functionary-small (smaller tool-call specialists)

Decision deferred until everything else ships. Current lfm2.5-1.2b works.

---

## ✅ DONE (Aug 9 + Aug 10 + Aug 11 — latest first)

| # | When | Item | Files | Why |
|---|------|------|-------|-----|
| 30 | Aug 12 | **STT blazing-fast optimization** — `stt_device=auto` (CUDA only when ≥6GB free so whisper fits beside the 13.7GB big + 1.6GB overseer; CPU int8 otherwise); `stt_model=base` (2.5× faster than small on CPU, near-small accuracy, cached offline); async transcription (queue + worker — VAD never blocks, fixes missed speech); adaptive beam (5 CUDA / 1 CPU); `unload_if_idle()` frees CUDA on VRAM pressure / big-model-up / 120s idle; cleanup off by default (was +9.5s/clip); PID-guarded daemon shutdown write (stop→start no longer clobbers state). Steady-state 0.16s/clip CUDA, 2.1s CPU. | `lib/stt.py`, `lib/stt_daemon.py`, `lib/config.py`, `tests/run_smoke.py` | User: "make sure it's perfect, optimized, and blazing fast" + "if it's gonna use vram make sure it fits with the overseer and big model loaded" |
| 31 | Aug 12 | **STT whisper stays resident in VRAM** — user: "stays in vram so its faster". Corrected VRAM accounting (measured: big 13.7GB + overseer LFM2.5-1.2B 0.95GB + whisper base fp16 0.43GB = ~15.1GB, ~1GB free — the old "2.2GB system + 1.6GB overseer" comment was wrong). `unload_if_idle()` no longer frees on idle or big-model-up — whisper stays resident once loaded; only a genuine OOM risk (free <512 MiB, a big-model generation spike) frees it. Removed dead `_model_last_used`/`time`; smoke test rewritten to OOM-floor. Daemon restarted (pid 1565451). | `lib/stt.py`, `tests/run_smoke.py` | User: "make sure it works and stays in vram so its faster" |
| 28 | Aug 12 | **STT integration** — shared engine `lib/stt.py` (faster-whisper small, CPU) + tiny-overseer cleanup; `lib/stt_daemon.py` hotkey hold-to-talk + VAD speak-to-capture, xdotool type at cursor; `cortexagent voice start|stop|status|set-mode`; webui `/api/stt` + 🎙️ MediaRecorder button; tray STT submenu (toggles + test mic). Default mic = Logi USB Headset. | `lib/stt.py` (new), `lib/stt_daemon.py` (new), `lib/config.py`, `lib/webui.py`, `assets/webui_template.html`, `lib/tray.py`, `bin/cortexagent`, `tests/run_smoke.py` | User: "let's fully incorporate speech to text into the cli and webui for cortexagent" |
| 29 | Aug 12 | **Step 2: ReAct/Socratic loop** — `lib/react_loop.py` (run_react, classify_mode, max_steps=8, task_steps publishing), `query_with_tools` in tiny_llm, `_execute_task` llm → run_react, guardrails (run_command process-group kill, subagent allowlist, media async, rag empty-query) | `lib/react_loop.py`, `lib/tiny_llm.py`, `lib/tool_registry.py`, `lib/overseer.py`, `tests/run_smoke.py` | Spec: `2026-08-12-react-loop-design.md` |
| 25 | Aug 12 | **SlimToken orchestration layer — 5 design specs** — reconciled the master build prompt against the codebase (gap analysis), then designed the 5-step build: (1) tool registry + `rag_query` CortexLLM half, (2) ReAct/Socratic loop (overseer-driven, tool-call via :8082), (3) domain DBs (SQLite FTS5 + sqlite-vec, all-MiniLM-L6-v2 embeddings, hybrid RRF search) + ingestion, (4) adapters (Moondream, faster-whisper via existing `lib/stt.py`, Docling/pdftotext), (5) integration capstone (ingestion job library, e2e, overseer model eval). Architecture: queue schedules → loop executes → registry acts; two-memory split (CortexLLM = conversation/commands, domain DBs = knowledge); orchestration stays in cortexagent (divergence note). | `docs/superpowers/specs/2026-08-12-{slimtoken-orchestration,react-loop,domain-db,adapters,integration-capstone}-design.md`, `docs/CORTEXLLM-0.4.0-DIVERGENCE.md` | User: "expand slimtoken to include all of the multimodal adapters and the react/socratic loop, handle the rag tool calls, handle the domain data ingestion and creation of the domain databases. the overseer model should be able to handle all of it by using the cpu and scripts." Design-doc phase only — implementation pending. |
| 26 | Aug 12 | **SOC analyst overseer design spec** — the overseer becomes a 24/7 active SOC analyst: monitors honeypot/canary/process/network, consults dfir domain DB, makes decisions (block/quarantine/kill/revoke), learns from review. **Graduated autonomy** (user-confirmed): training mode → per-action toggles in `soc_autonomy.json` → auto at confidence threshold; audit trail + undo on every action. **Model: Qwen2.5-3B-Instruct-abliterated Q4_K_M (~1.93 GB)** — abliterated (matches uncensored big model), native tool calling, Apache 2.0 (`huihui-ai`). Fits 16 GB only with big-model trim (`big_ub` 1024→512 + `big_ctx` 128k→64k, ~0.7 GB freed). **Optimize-further path: LoRA fine-tune on logged SOC trajectories** (teacher = 35B, Unsloth on 16 GB). Ruled out: Nemotron-Flash-3B (no tool calling — only 30B Nemotrons have it; no GGUF; non-commercial), Nemotron-Nano-30B (Q4_K_M = ~19–23 GB, needs ~25 GB VRAM — doesn't fit 16 GB even alone). | `docs/superpowers/specs/2026-08-12-soc-analyst-overseer-design.md` | User: "i want to see how large we can go on an overseer model... i want it to eventually be able to persistently monitor my computer for threats, like an active soc analyst working 24/7." + "overseer should be able to consult domain specific data and make decent decisions like blocking attacks" + "i like 3. its a training mode... maybe have a list of things i can toggle" + "ok fine use 3b ablit". Design-doc phase only — implementation pending. |
| 27 | Aug 12 | **Step 1: tool registry + `rag_query` (CortexLLM half)** — `lib/tool_registry.py` (stdlib-only): declarative `TOOLS` dict, `list_tools()` (OpenAI function schemas), `execute_tool(name, args)`, `register_tool()`. v1 tools: `run_command`, `query_llm`, `spawn_subagent`, `generate_image/video/media`, `web_search` (firecrawl → DuckDuckGo fallback), `rag_query` (CortexLLM hot/warm/cold/vector search); stubs `describe_image`/`transcribe_audio`/`parse_document`/`ingest_domain` return not-implemented. `_execute_task` refactored to a thin wrapper over the registry (queue bookkeeping unchanged). `--smoke` + `tests/run_smoke.py` registry area. | `lib/tool_registry.py`, `lib/overseer.py`, `tests/run_smoke.py` | Spec: `2026-08-12-slimtoken-orchestration-design.md` §4-5. Foundation for ReAct loop (step 2), domain DBs (step 3), adapters (step 4), SOC analyst. |
| 20 | Aug 11 | **ASU watcher: random keep-alive cadence** — keep-alive ("." + Enter) now fires on a random 60–90 min interval instead of fixed 30 min. Each send schedules the next via `random.uniform(3600, 5400)`; state stores `next_keepalive_at` (migrated from `last_keepalive`). | `scripts/asu_chat_watcher.py` | User: "change the . enter to be every 1-1 1/2 hours randomly" |
| 21 | Aug 11 | **Proxy t/s fix — Anthropic usage shape** — token accounting in `lib/grammar_proxy.py` only parsed OpenAI (`usage.prompt_tokens`/`completion_tokens`) + llama-server `timings` shapes, but live traffic is Anthropic-format (`/v1/messages?beta=true`) which reports `usage.input_tokens` (in `message_start`, nested under `message`) + `usage.output_tokens` (in `message_delta`) → `/metrics` showed all zeros → statusline/webui showed no t/s. Added Anthropic shape handling (incl. the `message.usage` nesting). Verified all 3 shapes + real request through :8081 → `[proxy] tokens: 13 in → 16 out (17.1 tok/s)`; statusline now shows `in 14 t/s · out 17 t/s`. Proxy reloaded (kill+respawn, big model stayed loaded). | `lib/grammar_proxy.py` | User: "i still can't see live tokens/second count on cortexagent" |
| 22 | Aug 11 | **Prompt-queue conflict detector — blocking DISABLED** — the UserPromptSubmit hook's conflict detector was blocking real prompts with "what do you want?" questions, using stale prompts from yesterday. Root causes: (1) **stale cross-session items** — the queue persisted 241 items across sessions (junk like "hi", "are you working", statusline output), so new prompts were compared against yesterday's agenda; (2) **stopword target bug** — `_directive()` took the word right after the verb as the target, which is usually "the", so any two prompts starting "use the…"/"keep the…" false-conflicted on "the"; (3) **distant negation** — "i use the internet. i dont want to block it" negated "use" because "dont" appears later in the sentence. **Final fix (user's hard directive "i want it to stop blocking shit im doing"): the hook NEVER blocks.** `hooks/user-prompt-submit.sh` still runs `prompt_queue.submit()` + injects the agenda as context, but the `decision: block` path is removed — a prompt can never be held. Also: `_directive()` skips stopwords for the target + only applies negation within 3 tokens of the verb; queue is **session-scoped** — `hooks/session-start.sh` clears it on startup/`/clear`/`/compact` (so `/clear` now resets it). Cleared 241 stale items. Verified: prompt that WOULD have conflicted passes through unblocked, agenda context still injected, memory append intact. | `hooks/user-prompt-submit.sh`, `lib/prompt_queue.py`, `hooks/session-start.sh` | User: "i want it to stop blocking shit im doing" |
| 23 | Aug 11 | **ASU watcher: crisis-fund message appended to 2nd message** — `FOLLOWUP_MSG` now ends with "I also received a $300 crisis fund because I was in a car accident a week ago. It's deducting it from my unsub loans, however. Can you fix that? They said it was a grant." Watcher reloaded (PID 2838097), state preserved (sent_count=0, agent not joined yet — change applies to next send). | `scripts/asu_chat_watcher.py` | User: "add to the second message 'I also received a $300 crisis fund…'" |
| 24 | Aug 12 | **ASU watcher: join-race fix** — 15:54:50 fired a FALSE "AGENT JOINED" on a mid-load frame (queue text paints after the header) → `fill_and_send` failed, no retry ever re-fired (page re-rendered to queue state → joined=False). Now: join must be CONFIRMED across 3 consecutive polls (`_join_streak`), textarea probed before send, and the send retried 3×/3s (`send_with_retry`). Watcher reloaded (PID 2472162). `--test` passes, queue at 2082, textarea ready. | `scripts/asu_chat_watcher.py` | User: "test it. somehow the chat ended and now im at 2082" |
| 19 | Aug 11 | **ASU watcher: second follow-up message** — watcher now sends 2 messages in order on agent join (canned Grad PLUS question, then "If so, can you please tell me how to apply and then accept the loans?"), 10s gap between them. State schema migrated `sent` → `sent_count` (old `sent:true` → `sent_count:1`). | `scripts/asu_chat_watcher.py` | User: "for the second message on the asu chat, have it say 'If so, can you please tell me how to apply and then accept the loans?'" |
| 18 | Aug 11 | **General browser control engine** — `lib/browser_control.py` (new): Playwright-style API over **page-level CDP websockets** on :9222 — `list_tabs`, `find_tab`, `navigate`, `click`, `type_text`, `evaluate`, `snapshot`, `read_text` + shadow-DOM helpers (`fill_and_send`, `element_value`, `clear_element`, `page_text`). Persistent per-tab websocket, reconnect on failure. `lib/playwright_brave_mcp.py` refactored to a thin MCP transport over the engine (no per-call connect/close churn) + 2 new tools (`brave_tabs`, `brave_fill_send`). `scripts/asu_chat_watcher.py` refactored to consume the engine (verified: `--test` fill/read-back/clear PASS, watcher restarted PID 1858007). **Transport note:** Playwright `connect_over_cdp` (browser-level) wedges on this browser — ws connects but handshake times out (118 tabs + stale `@playwright/mcp` servers). Page-level CDP is the robust path; Playwright-backed transport can be swapped in behind the same API after a Brave restart. | `lib/browser_control.py` (new), `lib/playwright_brave_mcp.py` (rewrite), `scripts/asu_chat_watcher.py` (rewrite), venv +`playwright` +`websocket-client` (MCP server was crashing on import — venv lacked both) | User: "roll the ASU watcher into cortexagent so we can control the browser that way... using the 9222 port and playwright... we will add to it later." |
| 17 | Aug 11 | **Tray popout overseer dashboard** — `lib/tray_dashboard.py` (Tkinter, stdlib-only). Shows overseer state (offline/thinking/idle + dot), big-model step counter (▓▓░░ progress bar with labels), 30-message rotating tip pool (15s cadence). Polls daemon control socket + overseer state JSON + big-model steps JSON at 1Hz. Plain language, no raw numerals (no t/s, ports, MiB). Esc closes. Wired into tray menu + double-click handler. | `lib/tray_dashboard.py` (new, 391 lines), `lib/tray.py` (+21), `lib/grammar_proxy.py` (+57, `_emit_dashboard_step`) | User: "implement ALL" of the tray dashboard. CLI 100% working milestone. |
| 16 | Aug 11 | **Branding: 'CortexAgent by GreyOK00'** — consistent across launcher, README, config author default. Added `README.md` + `bin/cortexagent` to PII exclude (authorship is not PII). | `bin/cortexagent:2`, `README.md:7`, `lib/config.py:355`, `tests/run_smoke.py` PII_EXCLUDE_FILES | User feedback: "it should say CortexAgent by GreyOK00 but it says CortexAgent by CortexAgent". Authorship ≠ PII. |
| 15 | Aug 11 | **Overseer watchdog false-positive fix** — requires BOTH `no bin/cortexagent` AND `daemon idle > 300s` before unloading big on apparent CLI close. Previously unloaded big mid-conversation during webui-only sessions. | `lib/overseer.py` (`_watchdog_cortexagent`, +31 lines) | User selected "Fix watchdog (proper)" option after diagnosing the unload-during-webui race. |
| 14 | Aug 11 | **No-fallback config + smoke fix** — `fallback_model = ""` (empty) in both live install conf + github copy. `test_fallback_config_and_args` now passes when empty (per user "I just want the UD model") while still validating ctx/threshold/args constants. | `~/.cortexagent/cortexagent.conf`, `lib/config.py` github copy, `tests/run_smoke.py` (+30 lines) | User explicit: "I dont want a fallback model just the uncensored model. i told you this several times". |
| 13 | Aug 11 | **GitHub copy prepared** at `/home/grey/cortexagent-github/` — 217 files / 6.8 MB, PII scrubbed (`/home/grey`, `GreyOK00` kept as legit author, `fc-`, `sk-ant-`, `UD-IQ3_S`→`IQ3_S`). Old changelogs removed (Aug 4 overseer-registry design, output-rules-design). `big_model` default = base IQ3_S (no UD), `fallback_model = ""`, version 0.3.2. Git initialized + commit `5c20b87`. | `/home/grey/cortexagent-github/` (full copy) | User: "purge any PII from the public repo... remove any old changelogs that have personal info". |
| 12 | Aug 11 | **Big-model step emission in proxy** — `_emit_dashboard_step(body, elapsed)` counts tool calls in response and writes `~/.cortexagent/big_model_steps.json` (atomic tmp+rename). Read by `lib/tray_dashboard.py` to render the step counter. | `lib/grammar_proxy.py` (+57 lines) | Feeds the tray dashboard's big-model panel. |
| 10 | Aug 10 | **Daily changelog tracking** — this file + MEMORY.md pointer | `docs/superpowers/specs/2026-08-10-daily-changelog.md`, `~/.claude/projects/-home-grey/memory/cortexagent-daily-changelog.md`, `MEMORY.md` entry | Never lose context again. Future sessions READ THIS FIRST. |
| 9 | Aug 10 | **Wolf-head tray icon** — replaced fake-looking AI wolf. Built from `/home/grey/Desktop/Twitch/GREYOK_ ANIME DUDE.PNG` (768×1376 wolf-knight). Auto-detected head region, square-cropped to 767×767, multi-size. Tray.py auto-picks via existing fallback. | `assets/cortexagentsquarelogo.{png,jpg}`, `assets/cortexagent-icon-{16,32,48,64,128,256,512}.png`, `assets/cortexagent-webui-{128,256,512}.png`, `extension/assets/favicon-32.png`, `*.pre-wolf-20260810-*` (backups of old), `/tmp/build-wolf-icon.py` (re-runnable) | User: "find an actual wolf head image... the one you made doesn't look real" |
| 8 | Aug 10 | **Hot-memory hook JSON-escape bug fix** — `printf '%s' "$CONTEXT"` was sending unescaped newlines → daemon `json.loads` silently dropped every multi-line Bash/Read result → **39 hours of lost messages** (Aug 9 00:24 → Aug 10 12:14). Fix: replaced printf with `python3 -c 'json.dumps(...)'` in both `hook-save-context.sh` + `hook-save-user-prompt.sh`. 4-case escape test suite passes. Cold-memory rule saved (priority=critical). | `~/.cortexllm/scripts/hook-save-context.sh`, `~/.cortexllm/scripts/hook-save-user-prompt.sh`, `~/.config/cortexllm/memory/cold/agent_critical_rules.json` | Daemon/socket/script all looked fine in isolation; only the JSON payload construction was broken. Hooks must use python json.dumps, NEVER printf %s. |
| 7 | Aug 10 | **Slimtoken as primary minify backend** in `lib/grammar_proxy.py` — real compression (dedup + distill + 131072 backstop budget). lib.minify kept as fallback. Auto-detected; env-overridable. | `lib/grammar_proxy.py` (+47) | Better compression than stdlib lib.minify; already shipped at v0.3.3 on github.com/greyok00/slimtoken. |
| 6 | Aug 10 | **Context-window monitor + failsafe** in overseer — hard 400s when context hit server ceiling and auto-compact never fired. Monitor warns at ≥88% ctx used; failsafe force-resets session at ≥95% sustained 3 ticks (~90 s). | `lib/overseer.py` (+86) | User hit hard 400s in prod; this gives visibility + auto-recovers. |
| 5 | Aug 10 | **Stale-session self-heal** in daemon idle watcher — wrapper that died without `session-end` (SIGPIPE/SIGKILL/orphaned bash) leaves refcount stuck >0, blocks idle-unload forever. New `stale_session_sec=1800` config knob auto-releases leaked sessions. | `lib/config.py` (+6), `lib/daemon.py` (+15) | Required to make idle-unload work after crashes. |
| 4 | Aug 9 | **8090 webui consolidation** — ported 8095 tray elements into 8090 template (model tabs, live t/s+VRAM, sessions sidebar, overseer pane, 15-card picker, schedule add/remove, upload, streaming chat/image/video). Verified via Brave CDP :9222. 4 tabs render, tps 40.8, vram 14.9/16G, 6 overseer cards, picker 15 cards/6 checked, 0 console errors, 0 HTTP≥400. **This is the single webui dashboard — no second port.** | `lib/webui.py` (+280), `assets/webui_template.html` (+934), `lib/tray.py` (+16) | User: "shouldn't be multiple dashboards... just have 8090 as the working one for the web ui and the cli" |
| 3 | Aug 8 (still applies — already shipped) | **Wrapper TUI opt-in** — `bin/cortexagent` plain CLI by default; `--tui` / `-t` opens full-screen Textual interface. `trap cleanup EXIT INT TERM PIPE` so SIGPIPE from `| head` doesn't skip session-end. Wolf head PNG/JPG fallback chain (`.jpg` → `.png` → drawn mark). | `bin/cortexagent` (+34, includes SIGPIPE trap), `lib/tray.py` (+16) | User: "no TUI, TUI sucks" → opt-in only. User: "find actual wolf head" → assets-based icon. |

### Items REMOVED (superseded by current plan)

| Old item | Why removed |
|----------|-------------|
| ~~Tray pop-out 360×360 dashboard showing overseer activity~~ **(Aug 11: RE-ADDED)** | Aug 10: "shouldn't be multiple dashboards". Aug 11: user pivoted — "tray popout dashboard is ACTIVE, webui :8090 is DEFERRED. they are NOT the same thing." Re-added as item #17. |
| SmolVLM2-2.2B vision bridge | User: "no other models" + Qwen 3.6 35B is already multimodal. |
| Whisper audio → text | Same — no separate models. |
| Prompt optimizer (2-pass) | Qwen 3.6 + slimtoken minify in proxy covers the use case. |
| Separate qwen3vl-8b server (:8083) | Qwen 3.6 35B IS multimodal. Drop the entire `[vision]` block. |
| Fallback model swap path | Aug 11: user: "no fallback model anymore. I just want the UD model." Both live + github ship `fallback_model = ""`. |

---

## 🚧 NEXT (in order — verify smoke between blocks)

| # | Action | Files | Verify |
|---|--------|-------|--------|
| 1 | `.gitignore` — add `*.bak*` and `*.pre-wolf-*` | `.gitignore` |
| 2 | Empty `big_model` default | `lib/config.py:241` |
| 3 | Remove `vision_*` defaults | `lib/config.py:252-262` |
| 4 | `big_idle_unload_sec = 0` (disable idle unload) | `lib/config.py` + `lib/daemon.py` |
| 5 | Strip `:8083` / `qwen3vl` / `vision` references | `lib/webui.py` + `lib/tray.py` + `lib/img2img.py` |
| 6 | Drop `--tui` / `-t` flag from wrapper | `bin/cortexagent` |
| 7 | **R2 + R5**: flip `lib/response_model.py` — default hidden code, always-on visual format | `lib/response_model.py` |
| 8 | **R4**: add `minify_response()` to proxy (output-side minify) | `lib/grammar_proxy.py` |
| 9 | **R3**: add thinking-bottom-line to proxy stderr | `lib/grammar_proxy.py` |
| 10 | **R6**: extend `pre_flight_gate` with ambiguous-prompt → clarification branch | `lib/pre_flight_gate.py` |
| 11 | Tray → click launches 8090 (no separate dashboard) | `lib/tray.py` |
| 12 | Update README + MODELS.md | `README.md`, `config/MODELS.md` |
| 13 | Smoke tests for all new behavior | `tests/run_smoke.py` |
| 14 | `cortexagent doctor` + full smoke → MUST pass | shell |
| 15 | Commit as ONE ready-for-GitHub commit | git |
| 16 | Overseer tool-call research (separate) | web |

**Detailed design (rules R1-R7 + existing token-opt O1-O15 enumeration):**
→ `docs/superpowers/specs/2026-08-10-output-rules-design.md`

---

## 📌 Tracking

- This file = `~/cortexagent/docs/superpowers/specs/2026-08-10-daily-changelog.md`
- Auto-memory pointer = `~/.claude/projects/-home-grey/memory/cortexagent-daily-changelog.md` + MEMORY.md entry
- **Every commit appends a ✅ row to DONE table. Every cancellation gets a REMOVED row.**
- Future sessions READ THIS FILE FIRST. Aug 8 is out of scope per user 2026-08-10.

## 🐺 Wolf head build reference

Source: `/home/grey/Desktop/Twitch/GREYOK_ ANIME DUDE.PNG` (768×1376 RGB)
Build script: `/tmp/build-wolf-icon.py` (re-runnable)
Strategy: brightness threshold (>50/255) → figure bbox → top 32% (head) → square-crop centered → LANCZOS multi-size.
Regenerate: `python3 /tmp/build-wolf-icon.py`