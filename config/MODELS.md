# CortexAgent Model Stack

## VRAM Budget (16GB Total)

```
┌────────────────────────────────────────────────────────────┐
│                    VRAM MAP (16 GB total)                    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌──────────────────────────────────────────────────┐      │
│  │  🧠  Qwen3.6-35B (IQ3_S)                        │      │
│  │  ┌──────────────────────┬───────────────────────┐ │      │
│  │  │ Weights: 13.0 GB    │ KV Cache: 1.3 GB      │ │      │
│  │  │                     │ (256k ctx, q4_0)       │ │      │
│  │  └──────────────────────┴───────────────────────┘ │      │
│  │  Total: 14.3 GB                                  │      │
│  └──────────────────────────────────────────────────┘      │
│                                                            │
│  ┌── 1.7 GB reserved for system / GPU ops ──────────┐      │
│  └──────────────────────────────────────────────────┘      │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**The LLM owns the VRAM by default; diffusion runs in-process on the same GPU.**
**v0.3.x** — big stays loaded at all times (`big_idle_unload_sec=0` by default;
user pref: keep it loaded). Big is multimodal (Qwen3-VL family / Qwen3.6 35B),
so a separate vision server is no longer needed. The big model handles vision
natively and orchestrates image/video gen via diffusers in-process.

The shipped default `big_model` is **empty** — users MUST configure their own
via `CORTEXAGENT_MODEL=/path/to.gguf` or `[backend] big_model = /path/to.gguf`
in `cortexagent.conf`. The shipped `tiny_model` (LFM2.5-1.2B, ~728 MB, tool-call
native) and `fallback_model` (LFM2.5-8B-A1B, MoE+Mamba-2 hybrid, ~6.7 GB) are
kept as defaults. Image/video generation
loads HuggingFace `diffusers` **in-process** (`lib/diffusion_backend.py`, #33)
— it does NOT swap into the LLM slot (that was the broken #28 path: llama-server
can't host diffusion). For a heavy video gen the LLM idle-unloads first.

```
┌─────────────┬────────────┬──────────┬─────────────────────────┐
│ Model       │ VRAM Used  │ When     │ Used For                │
├─────────────┼────────────┼──────────┼─────────────────────────┤
│ 🧠 Qwen3.6  │ 14.3 GB    │ Default  │ Reasoning, code, chat    │
│ 🎨 SD 1.5   │ ~3.7 GB    │ gen-image│ Image generation (def.) │
│ 🎨 SDXL     │ ~8 GB      │ gen-image│ Image generation (opt.)  │
│ 🎬 LTX-Video│ ~10 GB     │ gen-video│ Short video clips        │
└─────────────┴────────────┴──────────┴─────────────────────────┘
```

## Model Details

### 🧠 Qwen3.6-35B-A3B (Default LLM)
| Property | Value |
|----------|-------|
| **File** | `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` |
| **Size** | 13 GB |
| **Arch** | Hybrid SSM/Attention (35B params, ~10 layers full-attention) |
| **Context** | 262,144 tokens native |
| **KV Cache** | ~5 KB/token at q4_0 → ~335 MB at 65K, ~1.3 GB at 256K |
| **Why this model** | Tiny KV cache (hybrid SSM) means it fits 256K context in VRAM alongside weights. Pure attention models of this size need 2-3× more KV memory. |
| **Backend** | llama-server on :8080 (proxy :8081); idle-unloads to free VRAM |

### 🎨 Stable Diffusion 1.5 / SDXL (Image Generation)
| Property | Value |
|----------|-------|
| **Files** | `v1-5-pruned-emaonly.safetensors` (SD 1.5, ~4 GB, default), `sd_xl_base_1.0.safetensors` (SDXL, ~6.6 GB) |
| **Loader** | `StableDiffusionPipeline.from_single_file` / `StableDiffusionXLPipeline.from_single_file` (diffusers, fp16) |
| **Output** | **4K UHD 3840×2160** (default; native gen ~1024×576 → cv2 LANCZOS4 upscale, or `CORTEXAGENT_UPSCALER=realesrgan`) |
| **Native gen** | SD 1.5 ~1024×576; SDXL ~1920×1088 (`NATIVE_MP` caps, /32) |
| **VRAM** | SD 1.5 peak ~3.7 GB gen; SDXL ~8–14 GB; upscale is light |
| **Use** | Generate 4K images from text prompts (SDXL preferred when complete; SD 1.5 fallback) |

### 🎬 LTX-Video (Video Generation)
| Property | Value |
|----------|-------|
| **Source** | HF repo `Lightricks/LTX-Video` (downloaded to the HF cache on first `gen-video`, or set `CORTEXAGENT_VIDEO_MODEL` to a local path) |
| **Loader** | `LTXPipeline.from_pretrained` (diffusers, bf16, group-offloaded to fit 16 GB) |
| **Output** | **4K UHD 3840×2160** (default; native ~1024×576 ×161 frames → frame-upscale to 4K) |
| **VRAM** | ~10 GB with group offloading |
| **Use** | Generate short 4K video clips from text prompts |

> **cuDNN:** on this GPU/driver (cuDNN 9.2 / driver 550) a standard SD 1.5 conv
> raises `CUDNN_STATUS_NOT_INITIALIZED`, so cuDNN is **disabled by default**
> (`CORTEXAGENT_DIFFUSION_CUDNN=0`); native conv runs at ~8 it/s @512².

## How Generation Works

Diffusion runs **in-process** — no LLM slot swap, no second server. The main
LLM stays loaded; when VRAM is tight (e.g. LTX video), the LLM idle-unloads
first, diffusion runs, then the LLM reloads on the next chat request (the
reload-aware proxy buffers the request so the CLI never sees a 502).

```
Task Flow:                                    VRAM State:
┌─────────────────────┐                     ┌──────────────┐
│ LLM Reasoning (T-01) │──► Generate prompts │ 🧠 Qwen3.6   │
│ LLM Code (T-02)     │──► Write code        │   loaded     │
└─────────────────────┘                     └──────────────┘
           │
           ▼  gen-image / gen-video (in-process diffusers)
┌─────────────────────┐                     ┌──────────────┐
│ Image Gen (T-04)    │──► Generate 12 imgs │ 🎨 SD 1.5    │
│ Image Gen (T-05)    │──► Generate assets  │   in-process │
└─────────────────────┘                     └──────────────┘
           │
           ▼  next chat request → LLM still loaded (or reloads if it idle-unloaded)
┌─────────────────────┐                     ┌──────────────┐
│ Docker (T-06)       │──► Deploy          │ 🧠 Qwen3.6   │
│ System Exec (T-07)  │──► Verify          │   resident   │
└─────────────────────┘                     └──────────────┘
```

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **VRAM** | 12 GB (Qwen only) | 16 GB (Qwen + diffusion) |
| **RAM** | 32 GB | 64 GB |
| **Disk** | 30 GB for models | 50 GB+ (incl. LTX-Video cache) |
| **llama.cpp** | Latest build with GGUF support | With flash-attention |
| **diffusers** | torch + diffusers + transformers + accelerate | CUDA build of torch |
