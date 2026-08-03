# CortexAgent

<p align="center">
  <img src="assets/cortexagent.jpg" alt="CortexAgent" width="600">
</p>

A local coding agent by **CortexAgent**. Runs entirely on a local [llama.cpp](https://github.com/ggml-org/llama.cpp) model — no cloud, no API key — with a fully minified prompt system, lazy-loaded MCP tools, and built-in SQLite memory. Designed for maximum token efficiency and speed on a single 16 GB GPU.

## Features

### 🧠 Minified prompt system
Every instruction passed to the model is aggressively minified — CLAUDE.md, AGENT.md, tool descriptions, and system prompts are stripped to the essential signal. This means more of your context window is available for actual work, not boilerplate.

### 🦥 Lazy MCP tools
MCP servers are not loaded into every prompt's tool context. Instead, they expose a single stub tool that spawns the real server only when called. This keeps the per-turn token tax near zero for tools you rarely use, while keeping them available on demand.

- **Firecrawl** — lazy 1-tool wrapper for web scraping/search/crawl
- **Brave/Playwright** — browser automation via CDP on port 9222
- **wp-studio** — WordPress development (lazy, configured locally)
- **Generic lazy proxy** — any personal MCP server can be added to `~/.cortexagent/config/lazy_mcp_servers.json` and it will only load when called

### 💓 Heartbeat daemon
A background monitor using a tiny LLM (`qwen2.5:0.5b` via Ollama, ~350 MB) that runs in spare VRAM alongside the main model. It automatically:
- **Monitors** memory pressure (hot/warm/cold counts) every 30 seconds
- **Auto-compacts** warm memory when it hits 85% capacity
- **Cold distills** warm entries into distilled facts periodically
- **Queries the tiny LLM** for periodic health summaries
- **Logs alerts** to `~/.cortexagent/heartbeat.log`

Start it with `python3 lib/heartbeat_daemon.py start` after your session is running.

### 🎨 Image / video generation (diffusers, in-process)
Image and video generation run through **HuggingFace `diffusers` loaded
in-process** (`lib/diffusion_backend.py`) — no separate GUI app, no second
process, no extra port. The main coding LLM (Qwen3.6-35B) **stays loaded** the
whole time; diffusion runs on the same CUDA device with its own VRAM budget,
and the daemon's idle-unload still governs the big model.

> #28 proved `llama-server` cannot host diffusion models
> (`unknown model architecture: 'flux'`), so the old flux/ltx-GGUF-into-the-LLM
> path was broken by design. diffusers is the correct backend.

**Supported models (default = 4K UHD 3840×2160 output):**
- **SDXL** (`sd_xl_base_1.0.safetensors`, ~6.5 GB) — preferred image base (best
  4K quality; auto-used when its download is complete)
- **SD 1.5** (`v1-5-pruned-emaonly.safetensors`, ~4 GB) — fallback image base
- **LTX-Video** (`Lightricks/LTX-Video`, ~10 GB) — short 4K video clips;
  downloaded to the HF cache on first `gen-video` (or set
  `CORTEXAGENT_VIDEO_MODEL` to a local path). Group-offloaded to fit 16 GB.

> Image/video can't generate natively at 4K (UNet attention OOMs 16 GB and
> quality collapses outside the training res), so the backend generates at a
> model-native res (SDXL ~1920×1088, SD1.5/LTX ~1024×576) then upscales to 4K
> with cv2 LANCZOS4 (`CORTEXAGENT_UPSCALER=lanczos`; `=realesrgan` for sharper,
> optional).

> **cuDNN note:** on this GPU/diver (cuDNN 9.2 / driver 550) a standard SD 1.5
> conv raises `CUDNN_STATUS_NOT_INITIALIZED`, so cuDNN is **disabled by
> default** (`CORTEXAGENT_DIFFUSION_CUDNN=0`); native conv runs at ~8 it/s.

**Usage:**
```bash
python3 lib/model_switcher.py gen-image "a cat wearing a hat" --output cat.png
python3 lib/model_switcher.py gen-video "a dog running on a beach" --output dog.mp4
python3 lib/model_switcher.py status
```

The generated file is saved to disk for you to open.

### ⚡ High token-per-second speed
The default model is **Qwen3.6-35B-A3B** (hybrid SSM/Mamba + attention MoE). Its tiny KV cache (~5 KB/token at q4_0) means 128K context fits in ~640 MB of VRAM, leaving the rest for weights. KV cache stays on the GPU for full generation speed. Output is fast on short prompts and remains usable as context grows.

> Benchmarks will be added after a controlled run. Typical output on this hardware is 50–70+ tok/s depending on context length and prompt complexity.

### 📦 Self-contained memory (CortexLLM)
Three-tier memory backed by a local SQLite database (`~/.cortexagent/memory/cortexagent.db`). No external service, no cloud.

- **Hot** — FIFO buffer of the last 300 prompts/responses. Fast read/write for immediate session context.
- **Warm** — 2000-entry curated buffer (70% recent hot + 30% preserved). Auto-deduplicated and pruned on every write.
- **Cold** — Distilled facts extracted from warm memory. Long-term knowledge organized by category.

SessionStart auto-injects the last request + recent memory on startup, `/clear`, and auto-compact. The last prompt is replayed after compact. The heartbeat daemon periodically cold-distills warm entries into cold facts automatically.

### 🔧 Grammar proxy
A thin proxy between Claude Code and llama.cpp that strips the `grammar` field from client requests — fixing the 400 error that occurs when llama.cpp's grammar repetition threshold is exceeded. Logs per-request diagnostics for debugging.

### 📐 Auto-compact at 95%
Context auto-compacts at 95% of the window instead of the default lower threshold. This stops "compact every turn" — compact only fires when context is actually nearly full.

## Why this model and settings

| Component | Default | Why |
|---|---|---|
| Model weights | `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` | ~13 GB in VRAM. Large enough to act as a real coding assistant; small enough to leave headroom for KV cache and OS overhead on a 16 GB GPU. |
| Context window (`-c`) | `262144` (256K) | Native limit of the hybrid architecture. KV cache at q4_0 is ~1.3 GB — still fits in 16 GB VRAM alongside the model. |
| KV cache type (`-ctk/-ctv`) | `q4_0` | ~5 KB per token. At 128K context that is ~640 MB, leaving plenty of room for weights and growth. |
| KV cache offload | enabled | Keeps KV on the GPU with the weights; generation stays fast instead of falling back to system RAM. |
| GPU layers (`-ngl`) | `999` | All weight layers on GPU. |
| Flash attention (`-fa`) | on | Faster attention and lower VRAM/RAM pressure. |
| Auto-compact threshold | 95% of the context window | Compacts only when context is actually full, not every turn. |

## Requirements

- llama.cpp build with `bin/llama-server`
- GGUF model (default: Qwen3.6-35B-A3B quant; override with `CORTEXAGENT_MODEL`)
- NVIDIA GPU with ~16 GB VRAM (defaults tuned for that)
- `claude` (Claude Code) CLI on `PATH`
- Optional: Brave/Chrome for browser tools, `npx` + `FIRECRAWL_API_KEY` for Firecrawl

## Install

```bash
git clone <this-repo> ~/cortexagent
cd ~/cortexagent
bash install.sh
```

## CLI usage

```bash
cortexagent                       # interactive
cortexagent -p "fix this bug"     # one-shot
CORTEXAGENT_CTX=65536 cortexagent # smaller window
```

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `CORTEXAGENT_MODEL` | path to default Qwen3.6-35B-A3B GGUF | model file |
| `CORTEXAGENT_ALIAS` | `cortexagent` | model alias |
| `CORTEXAGENT_PORT` | `8080` | llama-server port |
| `CORTEXAGENT_PROXY_PORT` | `8081` | grammar-proxy port |
| `CORTEXAGENT_CTX` | `131072` | context window |
| `CORTEXAGENT_NGL` | `999` | GPU layers |
| `CORTEXAGENT_FA` | `on` | flash attention |
| `CORTEXAGENT_CTK` / `CORTEXAGENT_CTV` | `q4_0` | KV cache type |
| `CORTEXAGENT_KV_OFFLOAD` | `1` | KV cache on GPU |
| `CORTEXAGENT_LLAMA_DIR` | `$HOME/llama.cpp/build` | llama.cpp build dir |
| `CORTEXAGENT_FIRECRAWL_ENABLED` | `1` | enable lazy firecrawl tool |
| `CORTEXAGENT_BRAVE_ENABLED` | `1` | enable Brave/Playwright tools |
| `CORTEXAGENT_WEBUI_ENABLED` | `1` | enable local web UI |
| `CORTEXAGENT_MEMORY_DIR` | `$HOME/.cortexagent/memory` | SQLite DB + seed files |
| `CORTEXAGENT_FLUX_MODEL` | `$HOME/models/flux/flux1-schnell-q4.gguf` | Flux Schnell GGUF for image gen |
| `CORTEXAGENT_LTX_MODEL` | `$HOME/models/ltx/ltx-video-q4.gguf` | LTX-Video GGUF for video gen |

## Project layout

```
cortexagent/
├── bin/cortexagent            # launcher + server lifecycle
├── memory/                    # SQLite memory core + MCP server
│   ├── db.py
│   ├── manager.py
│   └── mcp_server.py
├── lib/                       # Python helpers (grammar proxy, MCP wrappers, etc.)
├── config/                    # CLAUDE.md, AGENT.md, settings/templates
├── hooks/                     # SessionStart, UserPromptSubmit, Stop
├── extension/                 # optional Chromium sidebar source
├── install.sh
└── README.md
```

## Dependencies

The core package is **stdlib-only Python**. Nothing is installed from PyPI.

- **Required externally:** `llama-server` (llama.cpp build), `claude` CLI.
- **Optional:** Brave/Chrome browser, `npx` + Firecrawl API key.

## Workflow

<p align="center">
  <img src="assets/workflow.png" alt="CortexAgent workflow" width="800">
</p>

## TODO

- [ ] **OpenClaw integration** — re-integrate the OpenClaw agent framework as a module within CortexAgent
- [ ] **Benchmarks** — run controlled token-per-second benchmarks across context sizes (4K, 32K, 64K, 128K) and publish results
- [ ] **Token usage metrics** — measure per-turn token tax (system prompts, tool descriptions, memory injection) and compare to baseline Claude Code

## License

MIT — see [LICENSE](LICENSE).
