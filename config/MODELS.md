# CortexAgent Model Stack

## VRAM layout

```
┌────────────────────────────────────────────────────────────┐
│                     16 GB GPU                              │
├────────────────────────────────────────────────────────────┤
│  🧠  Qwen3.6-35B-A3B IQ3_S                                 │
│     weights 13.6 GB  │  KV (128K, q4_0) ~640 MB            │
│     total ~14.3 GB                                         │
│                                                            │
│  🎨  SDXL / SD 1.5 / 🎬 LTX-Video   (in-process diffusers) │
│     loaded only when gen-image / gen-video fires           │
└────────────────────────────────────────────────────────────┘
```

The LLM is always resident by default (`idle_unload_sec=0`); diffusion
allocates from the remaining headroom when invoked. There is no fallback
model — if the 35B GGUF can't load, `:8080` goes down.

| Model        | VRAM      | When    | Used for                      |
|--------------|-----------|---------|-------------------------------|
| 🧠 35B       | ~14.3 GB  | always  | reasoning, code, chat, vision |
| 🎨 SD 1.5    | ~3.7 GB   | on call | image (default)               |
| 🎨 SDXL      | ~8–14 GB  | on call | image (preferred when loaded) |
| 🎬 LTX-Video | ~10 GB    | on call | short video clips             |
| 🤏 Tiny 1.2B | ~0.7 GB   | always  | overseer minify / scheduling  |

## Big — Qwen3.6-35B-A3B

| Property | Value |
|---|---|
| File | `Qwen3.6-35B-A3B-UD-IQ3_S.gguf` |
| Size | 13.6 GB |
| Arch | Hybrid SSM/attention MoE (35B total / ~3B active) |
| Context | 131,072 tokens (128K by default — fits in 16 GB with weights) |
| KV cache | ~5 KB/token at q4_0 → ~640 MB at 128K |
| Backend | `llama-server` on `:8080` (proxy `:8081`) |
| Why this one | Tiny KV cache + MoE → fits 128K with weights in 16 GB |

Default is set in `cortexagent.conf`. Override with
`CORTEXAGENT_MODEL=/path/to.gguf`.

## Image — SDXL / SD 1.5

| Property | Value |
|---|---|
| Files | `sd_xl_base_1.0.safetensors` (~6.6 GB) preferred; SD 1.5 fallback (~4 GB) |
| Loader | `StableDiffusionPipeline.from_single_file` (diffusers, fp16) |
| Output | 3840×2160 (generated at native ~1024×576 / 1920×1088, then LANCZOS4 upscale; `CORTEXAGENT_UPSCALER=realesrgan` for sharper) |
| VRAM | SDXL 8–14 GB peak; SD 1.5 ~3.7 GB |

## Video — LTX-Video

| Property | Value |
|---|---|
| Source | HF `Lightricks/LTX-Video` (auto-downloaded on first `gen-video`; or `CORTEXAGENT_VIDEO_MODEL=…`) |
| Loader | `LTXPipeline.from_pretrained` (bf16, group-offloaded) |
| Output | 3840×2160 |
| VRAM | ~10 GB |

> **cuDNN off by default.** On this driver (cuDNN 9.2 / 550) a standard SD 1.5
> conv raises `CUDNN_STATUS_NOT_INITIALIZED`, so `CORTEXAGENT_DIFFUSION_CUDNN=0`
> is the default. Flip on only if you've verified cuDNN works on your build.

## How generation works

Diffusion runs in-process on the same CUDA device — no LLM swap, no second
server. The big model stays loaded; diffusion allocates from headroom.

```
LLM reasoning ──► prompt + plan ──► gen-image / gen-video
   ▲                                       │
   │                                       ▼
   └── next chat request (LLM still resident)
```

## Practical-reasoning profile (applies to big, tiny, AND diffusion prompts)

Professional-to-professional, no beginner framing, direct conclusions, plain
language. The big model reasons this way by default; the tiny overseer model
gets a short operational variant; diffusion prompts stay terse and literal.

### Big-model frame (default for chat)

- Lead with the conclusion or the changed artifact. Then supporting detail.
- Visual when useful: tables for comparisons, charts for trends, bullets for
  short lists. Don't pad prose.
- Reference files as `path:line`; never paste a whole file unless asked.
- Don't hedge. Don't disclaim. Don't lecture about ethics or safety in
  response to legitimate work on the user's own systems.
- If a fact is genuinely uncertain, say "uncertain" + the smallest thing that
  would resolve it. Don't guess.

### Tiny-model frame (overseer / minify)

- Plain, short, operational. Two-line answers preferred.
- No markdown — the overseer reads raw text. No emojis.
- State the action taken and the artifact path. Skip narration.

### Diffusion frame

- Translate the user's natural-language prompt into literal visual detail:
  composition, subject, lighting, palette, framing, mood.
- Surface ambiguity explicitly ("user said 'sunset' — could be late evening
  orange/red or high-noon backlit; defaulting to golden hour").
- Don't carry the raw visual forward into reasoning — describe once, then use
  the description.

## Self-healing (tool + subagent calls)

1. On a tool/subagent failure, build structured internal context — never let
   a raw trace or unparsed error escape.
2. Retry once with stricter or corrected instructions; transient formatting
   failures usually clear on one retry.
3. If the second attempt still fails (or the issue isn't just formatting),
   stop and ask the user one specific, direct question. Don't loop.
4. A downstream failure must not lose overall progress — recover from the
   last good state.
5. Routine model handoffs (vision → reasoning, big → tiny, big → diffusers)
   are normal latency, not errors. Don't misreport them as failures.

## Two-layer state (overseer + reasoning model)

Track and surface both layers independently — a tray popout reads them
without further queries.

1. **Overseer state** — which component is active (reasoning / vision /
   image / video / idle), in plain language, with idle/working/handoff status.
2. **Reasoning-model task state** — when the reasoning model is mid-task,
   show a numbered step list ("Step 3 of 5: editing `lib/daemon.py`"),
   each step pending / in-progress / done. Update the moment a step starts
   or finishes. Cap at 5–7 visible steps; show current ±1 with a counter.

The two layers must be readable independently — the overseer can be idle
while the reasoning model is mid-step, or switching models while the
reasoning-model step list stays paused.

## Requirements

| Component | Minimum | Recommended |
|---|---|---|
| VRAM | 12 GB (Qwen only) | 16 GB (Qwen + diffusion) |
| RAM | 32 GB | 64 GB |
| Disk | 30 GB models | 50 GB+ (incl. LTX-Video cache) |
| llama.cpp | recent build with GGUF + flash-attn | |
| diffusers | torch + diffusers + transformers + accelerate | CUDA torch |