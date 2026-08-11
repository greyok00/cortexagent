#!/usr/bin/env python3
"""model_switcher — image/video generation for CortexAgent.

Historical note (pre-#28): this module killed the main LLM, loaded
flux/ltx GGUFs into llama-server, generated, then restored the LLM. That was
**broken by design** — llama-server cannot host diffusion models
(``unknown model architecture: 'flux'``). Image/video now route through
``lib/diffusion_backend``, which loads **HuggingFace diffusers in-process**
(no ComfyUI app, no second process). The daemon's LLM hot-swap (#28) stays
LLM-only; diffusion never touches the big model's slot.

The public surface (``gen_image`` / ``gen_video`` / ``status``) is preserved
so existing callers (``orchestrator``, ``media_pipeline``) keep working.

Usage:
  python3 model_switcher.py gen-image "prompt" --output output.png
  python3 model_switcher.py gen-video "prompt" --output output.mp4
  python3 model_switcher.py status
"""
from __future__ import annotations

import os
import sys

# Backward-compat env shim: old callers may set CORTEXAGENT_FLUX_MODEL /
# CORTEXAGENT_LTX_MODEL. Map them onto the diffusion_backend env vars (the
# backend ignores GGUF paths, honoring only .safetensors checkpoints / HF ids).
_legacy_image = os.environ.get("CORTEXAGENT_FLUX_MODEL", "")
if _legacy_image and not os.environ.get("CORTEXAGENT_IMAGE_MODEL"):
    os.environ["CORTEXAGENT_IMAGE_MODEL"] = os.path.basename(_legacy_image)
_legacy_video = os.environ.get("CORTEXAGENT_LTX_MODEL", "")
if _legacy_video and not os.environ.get("CORTEXAGENT_VIDEO_MODEL"):
    os.environ["CORTEXAGENT_VIDEO_MODEL"] = os.path.basename(_legacy_video)

from lib import diffusion_backend as _db  # noqa: E402


def gen_image(prompt: str, output: str = "output.png") -> bool:
    """Generate an image via diffusers (defaults: SD 1.5, VRAM-safe)."""
    return _db.gen_image(prompt, output=output)


def gen_video(prompt: str, output: str = "output.mp4") -> bool:
    """Generate a video via LTX-Video (diffusers, in-process)."""
    return _db.gen_video(prompt, output=output)


def status() -> dict:
    """CortexAgent + diffusers state."""
    s = _db.status()
    return {
        "main_model": _port_alive(8080),
        "gen_model": s["diffusers_ready"],   # diffusion runs in-process
        "heartbeat": _port_alive(8082),       # tiny 0.5b on llama-server
        "diffusion": s,
    }


def _port_alive(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2):
            return True
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "gen-image":
        if len(sys.argv) < 3:
            print("Usage: model_switcher.py gen-image 'prompt' [--output f.png]")
            return 1
        prompt = sys.argv[2]
        out = "output.png"
        if "--output" in sys.argv:
            i = sys.argv.index("--output")
            if i + 1 < len(sys.argv):
                out = sys.argv[i + 1]
        return 0 if gen_image(prompt, out) else 1
    if cmd == "gen-video":
        if len(sys.argv) < 3:
            print("Usage: model_switcher.py gen-video 'prompt' [--output f.mp4]")
            return 1
        prompt = sys.argv[2]
        out = "output.mp4"
        if "--output" in sys.argv:
            i = sys.argv.index("--output")
            if i + 1 < len(sys.argv):
                out = sys.argv[i + 1]
        return 0 if gen_video(prompt, out) else 1
    if cmd == "status":
        s = status()
        print(f"Main model:  {'RUNNING' if s['main_model'] else 'STOPPED'}")
        print(f"Diffusion:   {'READY' if s['gen_model'] else 'STOPPED'}")
        print(f"Heartbeat:   {'RUNNING' if s['heartbeat'] else 'STOPPED'}")
        print(f"Image model: {s['diffusion']['image_model']} "
              f"({s['diffusion']['image_kind']})")
        return 0
    print(f"Unknown command: {cmd}\n{__doc__}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())