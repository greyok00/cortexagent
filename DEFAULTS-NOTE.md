# PORTS, DEFAULTS, AND WHY EDITS DON'T TAKE EFFECT — READ THIS FIRST

## Model lanes (2026-09-22 architecture)

| What | Started by | Config lives in | Port |
|------|-----------|-----------------|------|
| Local llama model (Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated IQ3_XS) | the `cortexagent` launcher ITSELF — spawned as a direct child via `scripts/pdeathspawn.py` (PR_SET_PDEATHSIG=SIGKILL: kernel kills llama-server the instant the launcher dies — any exit path, no daemon, no systemd); legacy systemd-owned instances are killed+swept at launch. Context auto-fits: 98304 → 73728 → 49152 → 32768, first size that fits the free VRAM wins (display/desktop VRAM varies per session — 2026-09-22 log showed `cudaMalloc OOM` at 98304 with only 14.3 GiB free; 73728 served in ~13s) | `~/.cortexagent/cortexagent.conf` `[backend] model_path` (read via `python3 lib/config.py local`) | **11599** (alias `cortexagent`) |
| slimtoken CLOUD lane (minify+dedup → ollama) | `slimtoken` compose | `~/canaryshare/compose.yaml` | **11435** (hard-baked 2026-09-21) |
| slimtoken LOCAL lane (minify+goodies → ollama) | same container | same | **11436** (hard-baked 2026-09-21) |
| Raw ollama backend (CLOUD models only — zero local manifests, verified 2026-09-22) | `ollama` container | same | **11600** |
| ~~Grammar/minify proxy~~ | DELETED 2026-09-22 — minify lives in slimtoken; ollama + llama-server take standard openai-completions bodies | — | — |
| ~~:8080 model server~~ | REMOVED 2026-09-22 — replaced by :11599 direct llama-server | — | — |
| Tiny model | removed 2026-09-21 | — | — |
| Dispatcher / task queue | dispatcher server | `~/dispatcher/server.py` | 8084 |
| Browser automation CDP (cortexagent sessions) | launcher chromium | `~/.cortexagent/chromium-cdp-profile` | **9224** |
| SearXNG (web_search) | `searxng.service` (user systemd) | `~/.config/systemd/user/searxng.service` | **8888** |

## The TWO model knobs (separate on purpose — never merge them)

1. **CLOUD model**: `~/.cortexagent/cortexagent.conf` `[provider] ollama_model`
   → read as `CFG.model_cloud` (lib/config.py). Env `CORTEXAGENT_CLOUD_MODEL`
   overrides. Default `glm-5.3-flash:cloud`. Used by launcher settings.json,
   subagent model, overseer, media pipeline, tool registry, AND the whole
   dispatcher via `~/dispatcher/cloud_llm.py` (single client — 2026-09-22
   consolidation; five former hardcoded `deepseek-v4.1-flash:cloud` call
   sites now read this same knob). Gotcha: glm on /api/chat must NOT get
   `"think": false` — with `think` omitted, reasoning lands in a separate
   `message.thinking` field and `content` stays clean; think:false is what
   merges reasoning INTO content (probed 2026-09-22).
2. **LOCAL model**: same conf `[backend] model_path` (the GGUF) → read by
   the launcher's `_start_model` via `lib/config.py local`.

Changing the ollama model never touches the local lane. There is NO model
selector and NO `models` CLI subcommand — the model is the conf value.

## Session default (HARD — grey 2026-09-22)

The LOCAL model is the default and only session model. The launcher pins
`defaultProvider: "cortex-local"` / `defaultModel: "cortexagent"` and the
same pair for subagents; `models.ts` registers ONLY `cortex-local`, so a
cloud model cannot be selected from the TUI. Cloud exists exclusively for
the dispatcher (its model name shows up only in the cloud-dispatcher
panel).

## Why an edit doesn't take effect

- conf edit (local model) → takes effect on next `cortexagent` launch
  (the launcher resolves the GGUF via `lib/config.py local` at each
  start). No service to restart — the model lives and dies with the app.
- `~/.cortex/agent/extensions/models.ts` + `settings.json` → next session
  start (launcher rewrites settings.json defaultProvider/defaultModel from
  the conf value on every launch).
- The launcher (`bin/cortexagent`) has NO hardcoded model — it reads the
  conf. Do not re-introduce one.

## Port 8801

Nothing in our code or configs binds 8801 — it is not in any script, unit,
or config on this machine. It appeared transiently once (a spawned helper
grabbing a dynamic port) and is not listening now. If you see it again:
`fuser 8801/tcp` gives the owning PID; `ps -o args= -p <pid>` names it.
It is NOT part of cortexagent's contract and nothing depends on it.

Written 2026-09-20 after the owner saw 8801 open unexpectedly; updated
2026-09-22 for the :11599 direct-llama architecture (grammar proxy + :8080
removed, single cloud/local conf split).