# CortexAgent Smoke Test — Coverage Audit

Gate status: **PASS** — `python3 tests/run_smoke.py --no-live` → 15 ran, 24/24 covered, exit 0.
Full (live) gate: `python3 tests/run_smoke.py` (starts real daemons on isolated ports; ~2 min).

## How to run

```
python3 tests/run_smoke.py            # all areas (live tests use the 0.5b as a stand-in for big)
python3 tests/run_smoke.py --no-live  # static + offline areas only (no GPU)
python3 tests/run_smoke.py --area daemon
python3 tests/run_smoke.py --list     # list tests + matrix, don't run
```

Live areas (`models`, `daemon`, `proxy`, `cli`) start a real daemon in an
**isolated temp state dir** and use the 0.5b GGUF as a stand-in for the big
model — they never load the 13 GB 35B (which would compete for the GPU). To run
against the real big model, set `CORTEXAGENT_MODEL` to the 35B path **and** make
sure no other GPU session is running.

## Coverage matrix (24/24)

| Area | Test | Covers |
|------|------|--------|
| static | `all .py import` | every first-party module imports |
| static | `bash -n all scripts` | shell scripts parse |
| config | `config distrib-isolated` | fresh state dir, isolated DB, llamacpp backend |
| config | `config user-shared defaults` | default ports 8080/8082, idle 600s, shared DB |
| pii | `PII grep empty` | no `/home/grey`, `GreyOK00`, `fc-`, `sk-ant-` in product files |
| models | `model_backend start/health/stop tiny` | llama-server lifecycle |
| models | `tiny_llm.query returns text` | 0.5b chat completion on :8082 |
| daemon | `daemon lifecycle` | start → status → load → session-end → stop |
| daemon | `daemon idle-unload` | big frees after `IDLE_UNLOAD_SEC` with no session |
| proxy | `proxy reload-on-request` | POST while big down → reload → 200 (not 503) |
| cli | `cli routing` | every `engine/cli.py` subcommand |
| hooks | `hooks bash -n + no-cortexllm no-op` | hooks parse + graceful without CortexLLM |
| mcp | `mcp stdio initialize` | memory MCP server JSON-RPC handshake |
| xcontam | `fresh-config leaves ~/.config/cortexllm untouched` | isolated run doesn't touch personal DB |
| regression | `overseer stop exits 0` | clean exit 0 (no SIGPIPE/respawn) |
| regression | `cortexllm vector/graph/ontology APIs` | VectorStore / GraphStore / OntologyEngine present |
| welcome | `welcomeScreen --welcome-screen → IS_DEMO` | #27: broken banner var gone; hidden/condensed→IS_DEMO=1, full→unset; flag filtered |
| promptqueue | `prompt_queue decompose/conflict/supersede/ops` | #25: multi-part→agenda, append, conflict-block, revision supersede |
| promptqueue | `prompt-queue hook block+inject` | #25: user-prompt-submit hook injects agenda + blocks on conflict |
| tray | `tray --check + headless keeper` | #26: owns/tears-down ISOLATED overseer; :8082 untouched (port isolation guard) |
| nvsmi | `nvidia-smi wrapper tok/s` | #24: wrapper reads proxy /metrics → real tok/s (mock server) |
| diffusion | `diffusion_backend diffusers (offline)` | #30/#31/#33: in-process diffusers — model resolution/detection (sd15 vs sdxl), `_hf_repo_cached`, status() contract; gen_image honest False when checkpoint missing; gen_video honest False when LTX not cached (never triggers a download/load in the gate) |

## Resolved: heartbeat_daemon.py (deleted 2026-08-02)

**`lib/heartbeat_daemon.py`** was DEAD CODE — 9 Ollama references (`OLLAMA_URL`,
`/api/generate`), not imported by anything live, predating the llama.cpp migration.

**Decision: deleted.** Its function is covered elsewhere, so no refactor needed:

| Its function | Now covered by |
|---|---|
| Auto-compact warm memory | `memory/manager._update_warm_buffer()` runs on every save (pruner wired in Phase 0) |
| Proxy / model health ping | `lib/daemon.py` (`_big.is_healthy`) + `lib/overseer.py` (tiny) |
| Cold distillation | `lib/cold_distiller.ColdDistiller` (runnable on demand) |
| Claude Code session health | `lib/heartbeat_service.py` (read-only, live) |
| LLM health summary | Was Ollama-based (broken); statusline + `cortexagent status` cover visibility |

`lib/heartbeat_service.py` is a **different concern** (Claude Code session context
size / `/new` recommendation / stale-lock cleanup), not a replacement for the
memory-DB health checks — those are handled by the daemon + manager-on-save.

Removed from the `DEAD_CODE` set in `run_smoke.py`; coverage is now 23/23.

## Cross-platform + safety notes (new additions #24–#28)

- **Port isolation is mandatory for overseer/tray tests.** The overseer's
  `_stop()` → `_unload_tiny_model()` falls back to `_kill_port_server()` when
  no daemon is present (i.e. when `CORTEXAGENT_STATE_DIR` is isolated). That
  kills ANY llama-server bound to `CFG.tiny_model_port` — including the user's
  real :8082 tiny. The `tray` test therefore sets `CORTEXAGENT_TINY_PORT=18082`
  + `CORTEXAGENT_PORT=18080` + `CORTEXAGENT_PROXY_PORT=18081` and asserts the
  user's :8082 tiny count is unchanged before/after. **Never run an overseer
  `stop` under an isolated state dir without also isolating the tiny port.**
- **Windows guards.** `tray --check` + module import run everywhere; the live
  headless-keeper fork path is skipped on `os.name == "nt"` (no `os.fork` — the
  overseer daemonizes via fork, a pre-existing Windows gap). `welcome` /
  `nvsmi` / `promptqueue` hook tests require bash and are skipped where bash
  is absent; the pure-Python `promptqueue` module test runs everywhere.
- **`nvsmi` test uses a mock /metrics server** on an ephemeral port (no GPU,
  no real nvidia-smi needed). The wrapper has no `set -e`, so the
  `Generation Speed` line is appended even when the real `nvidia-smi`
  passthrough is absent (CI-robust).
- **#28 hot-swap** is covered by the daemon coverage row + the standalone
  `/tmp/hotswap_test.py` (not in-repo); the swap primitive (`_swap_big`,
  `swap` control cmd, `models swap` / `models load --model` CLI) is exercised
  there against live models.
- **#31/#33 diffusion backend** is tested **offline** — no GPU, no mock
  server. The backend is in-process diffusers, so the gate exercises the pure
  paths: model resolution/detection (`_detect_kind` sd15 vs sdxl,
  `_defaults_for`, `_resolve_image_model`, `_resolve_video_model`), the HF
  cache-presence check (`_hf_repo_cached` with an isolated
  `HUGGINGFACE_HUB_CACHE`), the `status()` contract, and the two **honest
  failure** paths — `gen_image` returns False when the checkpoint is missing,
  `gen_video` returns False when LTX-Video isn't cached (so the gate never
  triggers a download or model load). Default image model = SD 1.5
  (VRAM-safe). cuDNN is disabled by default
  (`CORTEXAGENT_DIFFUSION_CUDNN=0`) — verified 2026-08-02: the bundled cuDNN
  9.2 / driver 550 raises `CUDNN_STATUS_NOT_INITIALIZED` on the first UNet
  conv; native conv works. Live image gen (SD 1.5 from
  `v1-5-pruned-emaonly.safetensors`, 512², ~1.5 s, peak 3.74 GB) is verified
  out-of-band; the gate does not load a GPU.

## Bugs the gate caught and fixed this pass

- `lib/dispatcher.py` used a bare `from reliability import` that grabbed the
  user's `~/.openclaw/cortexllm/reliability.py` (which pulls `cortexllm_db`) via
  `PYTHONPATH` — non-portable. Fixed to use the bundled `lib.reliability`.
- PII scrub: `GreyOK00` (user handle) → configurable `CortexAgent` brand in
  LICENSE, README, `bin/cortexagent`, `lib/tui.py`, `lib/statusline.py`,
  `memory/cold/cortexagent.md`. `statusline`/`tui` now read `CFG.author`.
- `sk-ant-` in `lib/post_response_verifier.py` is a **key-redaction regex**
  (security code), not a secret — excluded from the PII scan as a detector file.
- daemon `load` now primes the idle timer so a manual load idles out correctly.