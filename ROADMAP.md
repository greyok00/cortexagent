# CortexAgent Roadmap — deprecated, replaced, and what's next

_Last reviewed 2026-08-02 (after the daemon + CLI + system-tray + prompt-queue
architecture landed: #24 tok/s, #25 prompt queue, #26 tray, #27 welcomeScreen,
#28 hot-swap, #29 smoke gate 23/23)._

This is a living map of what the current architecture **replaced**, what is
**broken by design** and needs a new backend, what is **duplicated** and should
be pruned, and what is **still core**.

## Current architecture (the spine)

```
cortexagent (bin/cortexagent)        ← session launcher: env, hooks, memory, banner
   ├─ engine/cli.py                  ← control-plane dispatcher (models/daemon/status/queue/tray/install)
   ├─ hooks/                         ← SessionStart, UserPromptSubmit (prompt queue #25), Stop
   ├─ lib/daemon.py                  ← persistent backend: big :8080 + tiny :8082 + proxy :8081
   ├─ lib/overseer.py                ← heartbeat + tiny keepalive + plan/workflow tracking
   ├─ lib/tray.py (#26)             ← system-tray owner of the overseer (CLI close ≠ kill overseer)
   ├─ lib/webui.py                   ← browser/mobile chat on :8090
   └─ lib/prompt_queue.py (#25)     ← default per-prompt agenda + conflict detector
```

## 🟢 Still core (keep)

| Module | Role |
|---|---|
| `lib/config.py` | single config loader, env-overridable, PII-free |
| `lib/daemon.py` | persistent backend, idle auto-unload, hot-swap (#28), adopted-model guard |
| `lib/model_backend.py` | llama-server lifecycle (start/health/stop) |
| `lib/control.py` | AF_UNIX control socket client/server |
| `lib/grammar_proxy.py` | reload-aware proxy + `/metrics` (real tok/s source) |
| `lib/overseer.py` | heartbeat, tiny keepalive, plan/workflow, clean exit 0 |
| `lib/tiny_llm.py` | 0.5b chat on :8082 (replaces Ollama) |
| `lib/tray.py` (#26) | system-tray overseer owner |
| `lib/prompt_queue.py` (#25) | per-prompt agenda + conflict detection (default) |
| `lib/webui.py` | browser/mobile UI (started by `bin/cortexagent` when `WEBUI_ENABLED=1`) |
| `lib/cortexagent_call.py` | memory save/recall pipeline |
| `lib/{statusline,tui}.py` | terminal UI |
| `lib/{context_pruner,dom_pruner,fast_extract,pdf_knowledge,cold_distiller,heartbeat_service}.py` | memory/context hygiene |
| `lib/{anti_hallucination,post_response_verifier,pre_flight_gate,loop_guard,reliability,humanize,coding_practices}.py` | agent guardrails |
| `lib/{profiles,patch_binary,lazy_mcp_proxy,firecrawl_proxy,playwright_brave_mcp}.py` | optional integrations |
| `engine/{cli,workflow,dag,types,progress}.py` | dispatcher + DAG workflow planner (wired into overseer status) |
| `scripts/nvidia-smi` (#24) | privacy wrapper + live tok/s |

## 🟢 Fixed — image/video generation (#31/#33, was broken by design)

#28 proved **llama-server cannot host diffusion models** (`unknown model
architecture: 'flux'`). The entire image/video path tried to load flux/ltx
into llama-server, so it was broken. **#31 first routed it through the
ComfyUI HTTP app; #33 replaced that with HuggingFace `diffusers` in-process**
(no GUI app, no second process, no `:8188` port):

| Module | Was | Now |
|---|---|---|
| `lib/diffusion_backend.py` | — | **diffusers in-process**: image via `StableDiffusionPipeline.from_single_file` (reuses existing SD1.5/SDXL `.safetensors`), video via `LTXPipeline.from_pretrained("Lightricks/LTX-Video")` → `export_to_video`. Pipeline-cached, VRAM-managed on the same CUDA device. |
| `lib/model_switcher.py` | 🔴 loaded flux/ltx into llama-server | 🟢 thin shim over `diffusion_backend` (signatures preserved) |
| `lib/media_pipeline.py` | 🔴 `_swap_via_llama_server` TODO stub + broken `img2img` binary | 🟢 routes image/video through in-process diffusers (no LLM swap) |
| `lib/img2img.py` | 🔴 `llama_cpp` text API for images + nonexistent `img2img` CLI | 🟢 deprecated shim over `diffusion_backend` |
| `lib/orchestrator.py` image/video queue | 🔴 → broken `model_switcher` | 🟢 works via the shim (no change needed) |

diffusion runs **in-process** on the same CUDA device the daemon already
manages; the daemon's LLM hot-swap (#28) stays LLM-only. **cuDNN is disabled by
default** (`CORTEXAGENT_DIFFUSION_CUDNN=0`) — verified 2026-08-02: the bundled
cuDNN 9.2 / driver 550 raises `CUDNN_STATUS_NOT_INITIALIZED` on the first UNet
conv; native conv works (SD 1.5: ~8 it/s @512², peak 3.74 GB). Env renamed
`CORTEXAGENT_FLUX_MODEL` → `CORTEXAGENT_IMAGE_MODEL` (backward-compat shim).
Video needs the LTX-Video model cached (downloaded on first `gen-video`, or set
`CORTEXAGENT_VIDEO_MODEL` to a local path); GGUF is incompatible with diffusers.
Smoke gate covers the offline resolution + honesty paths (24/24).

## 🟢 Fixed — scheduler consolidation (#32, was duplicated)

There were **four overlapping task-queue/scheduler systems**. The overseer
**already inlined** the live queue + scheduler (`# TASK QUEUE (from
orchestrator)`, `# SCHEDULER (from orchestrator)`) and is self-contained (no
`from lib.orchestrator`). #32 made the overseer the **single** queue by
deleting the three zero-importer dead modules:

| Module | Status | Why |
|---|---|---|
| `lib/orchestrator.py` | 🟢 DELETED | zero importers; queue+scheduler already inlined into the overseer; image/video types broken. |
| `lib/scheduler.py` | 🟢 DELETED | zero importers; stdlib cron/interval/at duplicated the overseer's inlined scheduler. |
| `lib/dispatcher.py` | 🟢 DELETED | zero importers; async priority queue + worker pool was a 4th, unused queue system. |
| `lib/prompt_queue.py` (#25) | 🟢 KEEP | per-prompt agenda + conflict detection (the user-facing queue) — distinct from the overseer's task queue. |
| `lib/overseer.py` (inlined) | 🟢 KEEP | THE single queue + scheduler (self-contained). |

## 🟡 Stale comments (trivial fixes)

| Where | Issue |
|---|---|
| `lib/overseer.py:790` | ✅ fixed (now says "the llama-server frees VRAM"). |
| `lib/overseer.py:78,685` | "replaces Ollama" historical notes — fine as history, or trim. |
| `lib/tiny_llm.py:6-11,47` | "replaces Ollama `/api/generate`" docstrings — fine as history. |

## 📋 Recommended next steps (ordered)

1. ✅ **Scheduler consolidation (#32, done).** Deleted `orchestrator.py`,
   `scheduler.py`, `dispatcher.py` (zero importers); the overseer's inlined
   queue+scheduler is the single queue. Smoke gate green after each deletion.
2. ✅ **Image/video via diffusers in-process (#33, done).** Replaced the
   ComfyUI HTTP client with in-process `diffusers` (SD1.5/SDXL via
   `from_single_file`, LTX-Video via `from_pretrained`); cuDNN disabled by
   default (verified workaround). Live image gen verified; video pending a
   live run once the LTX download completes.
3. **Overseer tiny-keepalive noise.** The keepalive uses a 3s `/health` timeout;
   under GPU/CPU contention (e.g. a running game) it false-negatives and logs
   "Tiny model down — restarting…" plus occasional bind races. It self-heals,
   so low-severity. Fix: require N consecutive failures before restart, and/or
   bump the timeout.
4. **Then** resume the deferred packaging pass (Phase 7 systemd/install #21,
   Phase 8 end-to-end verify #22). Cython/Nuitka still deferred.

## Out of scope for this pass (still deferred)

- Nuitka/Cython compilation (the plan defers this until Phases 0–8 work + test).
- GitHub push (held until everything works; standing constraint).
## 📋 Completed (added 2026-08-14)

4. ✅ **System tray icon fix.** Fixed pystray crash caused by missing notification daemon. Added xfce4-notifyd autostart + guard patch in `lib/tray.py`. Tray now runs in GUI mode with greyok logo icon.

5. ✅ **Minify stats dashboard.** Fixed dashboard reading reset proxy metrics instead of persistent file. Dashboard now falls back to `~/.cortexagent/minify_stats.json` when proxy shows 0. Shows real savings: 257 runs, 7.8% ratio, 977K tokens saved.

6. ✅ **Queue cleanup.** Added `_cleanup_queue()` — removes tasks older than 1 hour, keeps last 10. Called every 10 ticks (~5 min). CLI: `overseer.py queue cleanup` or `queue prune`.

7. ✅ **Code blocks disabled.** Added "NO code blocks (never use ```)" to `_REACT_SYSTEM` and `_SOCRATIC_SYSTEM` prompts in `lib/react_loop.py`.

8. ✅ **Beautification pass.** Integrated `lib/beautify.py` into react/socratic/direct output paths. Converts markdown tables, CSV, key:value blocks to formatted output. Applied to all overseer output.

9. ✅ **Stuck scheduler tasks removed.** Removed "smoke-test" and "verify-test" from schedule via CLI. Schedule is now clean.

## Out of scope for this pass (still deferred)

- Nuitka/Cython compilation (the plan defers this until Phases 0–8 work + test).
- GitHub push (held until everything works; standing constraint).
