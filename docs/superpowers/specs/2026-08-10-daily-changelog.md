# CortexAgent — Condensed Plan (Aug 9 + Aug 10 only)

**Owner:** grey · **Last updated:** 2026-08-10 12:50 MST · **Status:** 🔴 active

Append-only daily log. Latest entries supersede prior ones. Aug 8 ignored
per user (2026-08-10). Each item: **what**, **files**, **why**, **status**.

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

## ✅ DONE (Aug 9 + Aug 10 only — latest first)

| # | When | Item | Files | Why |
|---|------|------|-------|-----|
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
| Tray pop-out 360×360 dashboard showing overseer activity | User: "shouldn't be multiple dashboards" → tray = click-to-launch 8090. Activity visible IN 8090, not in tray. |
| SmolVLM2-2.2B vision bridge | User: "no other models" + Qwen 3.6 35B is already multimodal. |
| Whisper audio → text | Same — no separate models. |
| Prompt optimizer (2-pass) | Qwen 3.6 + slimtoken minify in proxy covers the use case. |
| Separate qwen3vl-8b server (:8083) | Qwen 3.6 35B IS multimodal. Drop the entire `[vision]` block. |

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