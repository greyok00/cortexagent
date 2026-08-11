# CortexAgent

Local coding agent running entirely on a single llama.cpp model. One daemon,
one overseer, one big model on `:8080`, one tiny LLM on `:8082` for the
overseer's minifier, in-process `diffusers` for image and video. No cloud, no
API key, no fallback swap path — the big model is the only model on `:8080`,
and if it can't load the port goes down.

## Stack at a glance

| Component | Port | Process | Purpose |
|---|---|---|---|
| Big LLM | `:8080` | `llama-server` | Qwen3.6-35B-A3B IQ3_S (~13.6 GB, 128K context) |
| Tiny LLM | `:8082` | `llama-server` | LFM2.5-1.2B Q4_K_M (~728 MB) — overseer only |
| Grammar proxy | `:8081` | `lib/grammar_proxy.py` | Minify + tool-call routing for every chat request |
| Daemon | AF_UNIX `~/.cortexagent/control.sock` | `lib/daemon.py run` | Owns `:8080` / `:8081`, session lifecycle, idle-unload |
| Overseer | always-on systemd service | `lib/overseer.py start` | Scheduler, warm→cold distillation, tiny keepalive |
| Webui | `:8090` | `lib/webui.py serve` | 3D chat + live dashboard, shared session with CLI |
| Diffusion | in-process | `lib/diffusion_backend.py` | SDXL / SD1.5 image, LTX-Video (group-offloaded) |

Two systemd user services run the whole stack independent of any CLI session:

- `cortexagent.service` — daemon + proxy + big-model slot
- `cortexagent-overseer.service` — overseer + tiny keepalive

## Install

```bash
git clone https://github.com/greyok00/cortexagent ~/cortexagent
cd ~/cortexagent
bash install.sh        # installs the two systemd services + creates ~/.cortexagent/
```

Drop a GGUF at the default path, or override:

```bash
export CORTEXAGENT_MODEL=/home/grey/models/your-model.gguf
```

`cortexagent.conf` (`~/.cortexagent/cortexagent.conf`) accepts the same keys in
`[backend]` and `[daemon]` sections.

## Run

```bash
cortexagent                     # interactive CLI (default — talks to the daemon)
cortexagent -p "fix this bug"   # one-shot
cortexagent --restart           # restart both services, reload big
cortexagent doctor              # repair drift, validate config
cortexagent status              # print daemon / overseer / proxy state
```

Open `http://127.0.0.1:8090/` for the webui. CLI and webui share the same
session through the proxy — typing in either window sees the same context.

## How it works

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  CLI (you)   │────▶│  Proxy :8081  │────▶│  Big :8080   │
│  Webui :8090 │     │ (minify+rout) │     │  35B-A3B     │
└──────────────┘     └───────────────┘     └──────────────┘
       ▲                    │
       │                    ▼
       │             ┌──────────────┐
       └─────SSE─────│  Daemon     │──── owns /sock, idle timer, status
                     └──────────────┘
                            ▲
                            │
                     ┌──────────────┐
                     │  Overseer    │──── tiny :8082 (minifier) + scheduler
                     └──────────────┘
```

Every CLI/webui message flows through the proxy. The proxy minifies the prompt,
forwards to `:8080`, and returns the stream. The daemon's only job is to own
the big model and report state; it doesn't sit in the request path.

## Configuration

| Key (`cortexagent.conf [backend]`) | Env | Default | Notes |
|---|---|---|---|
| `big_model` | `CORTEXAGENT_MODEL` | `~/models/qwen3.6-35b-iq3s/Qwen3.6-35B-A3B-UD-IQ3_S.gguf` | Big GGUF |
| `big_model_port` | `CORTEXAGENT_PORT` | `8080` | |
| `big_ctx` | `CORTEXAGENT_CTX` | `131072` | 128K — KV q4_0 ≈ 640 MB |
| `big_alias` | `CORTEXAGENT_ALIAS` | `cortexagent` | OpenAI `model` field |
| `tiny_model` | `CORTEXAGENT_TINY_MODEL` | `~/models/lfm2.5-1.2b/LFM2.5-1.2B-Instruct-Q4_K_M.gguf` | Overseer only |
| `tiny_model_port` | `CORTEXAGENT_TINY_PORT` | `8082` | **Isolate in tests** — see CLAUDE.md |

| Key (`[daemon]`) | Default | Meaning |
|---|---|---|
| `idle_unload_sec` | `0` | 0 = keep big loaded always. >0 = unload big N seconds after the last session ends. |

Diffusion env (optional): `CORTEXAGENT_VIDEO_MODEL`, `CORTEXAGENT_UPSCALER`
(`lanczos` \| `realesrgan`), `CORTEXAGENT_DIFFUSION_CUDNN` (default `0` — see
`lib/diffusion_backend.py` for why).

## Memory (three tiers, stdlib SQLite)

| Tier | Cap | What |
|---|---|---|
| Hot | 300 entries | FIFO; inlined into every prompt |
| Warm | 2000 entries | 70% recent + 30% curated; dedup + prune on save |
| Cold | unlimited | Distilled facts the overseer extracts from warm |

The overseer distills warm→cold every 30 s and only kicks in when the system
is otherwise idle.

## Diffusion

In-process `diffusers`, no second port, no second process. The big LLM stays
loaded the whole time; diffusion runs on the same CUDA device with its own
VRAM budget.

- **Image:** SDXL preferred (best 4K quality), SD1.5 fallback
- **Video:** LTX-Video, group-offloaded to fit 16 GB
- **4K output:** generated at model-native res, upscaled to 3840×2160 with
  LANCZOS4 (or Real-ESRGAN if installed)
- **cuDNN:** disabled by default (`CORTEXAGENT_DIFFUSION_CUDNN=0`) — the
  shipped NVIDIA driver raises `CUDNN_STATUS_NOT_INITIALIZED` for SD 1.5

```bash
python3 lib/diffusion_backend.py gen-image "a cat in a hat" --output cat.png
python3 lib/diffusion_backend.py gen-video "a dog running"   --output dog.mp4
```

## CLI rules (R1–R7)

The CLI runs in plain mode by default. The dashboard lives in the webui, not
in a TUI panel.

| | |
|---|---|
| R1 | Plain CLI; the dashboard is the 8090 webui. |
| R2 | Code hidden by default. Say `show code` or `with code` to reveal. |
| R3 | After every response: `_` divider + `▎ thinking: …` line. |
| R4 | Output-side minify via `lib/grammar_proxy.minify_response()`. |
| R5 | Visual output always on — tables → box-drawn, numeric → `█`, lists → `▎`. |
| R6 | Ambiguous prompts trigger a clarifying question instead of being routed. |
| R7 | Big stays loaded (`idle_unload_sec=0`). Big is multimodal. |

## What's intentionally NOT here

- **No fallback model.** If the big GGUF can't load, `:8080` goes down.
  Re-add a fallback path by reverting `lib/daemon.py` `_start_big`.
- **No separate flux/LTX GGUF into the LLM slot.** Diffusers is the only
  diffusion path; llama-server can't host SDXL/LTX (unknown architecture).
- **No openclaw integration.** Was an experimental module; removed.
- **No remote `/api/chat` auth beyond `CORTEXAGENT_WEBUI_TOKEN`.** Localhost only.

## Project layout

```
cortexagent/
├── bin/cortexagent                 # CLI launcher
├── engine/cli.py                   # argparse → daemon control socket
├── lib/
│   ├── daemon.py                   # owns :8080/:8081 + AF_UNIX sock
│   ├── overseer.py                 # scheduler + tiny keepalive
│   ├── grammar_proxy.py            # :8081 chokepoint (minify + tool routing)
│   ├── model_backend.py            # llama-server wrapper
│   ├── diffusion_backend.py        # in-process SDXL/SD1.5/LTX
│   ├── tiny_llm.py                 # LFM2.5-1.2B client
│   ├── prompt_queue.py             # decompose/conflict/supersede
│   ├── webui.py                    # :8090 server
│   ├── tray_dashboard.py           # tray popout overseer view
│   ├── statusline.py               # brand bar (CLI bottom)
│   └── ...
├── assets/webui_template.html      # 3D webui
├── config/templates/*.service      # systemd unit templates
├── install.sh
└── tests/run_smoke.py              # gate (29/29 must pass before commit)
```

## Dependencies

The core is stdlib-only Python.

- **Required:** `llama-server` (llama.cpp build), the GGUF you want to serve,
  an NVIDIA GPU with enough VRAM for the model (defaults tuned for 16 GB).
- **Optional:** `claude` CLI (for interactive mode), Brave/Chrome (browser
  tools), `diffusers` + `torch` (image/video — only needed if you call
  diffusion endpoints).

## License

MIT.