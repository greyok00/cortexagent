#!/usr/bin/env python3
"""img2img — DEPRECATED shim over ``lib.diffusion_backend``.

Historical note: this module tried to run GGUF image models (FLUX.2) via
``llama-cpp-python``'s ``create_completion`` (a *text* API) and a nonexistent
``img2img`` CLI binary. That path never produced images — llama.cpp has no
diffusion inference. Image generation now goes through HuggingFace diffusers (in-process) via
``lib.diffusion_backend``.

This shim keeps the old ``GGUFImageGenerator`` class + CLI so existing callers
(``media_pipeline``) and scripts keep importing. The class delegates to
``diffusion_backend.gen_image``.

Usage:
    python3 lib/img2img.py generate --prompt "a zebra" --output out.png
    python3 lib/img2img.py info
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# Map legacy model-path env onto the diffusion_backend checkpoint-name env.
_legacy = os.environ.get("CORTEXAGENT_FLUX_MODEL", "")
if _legacy and not os.environ.get("CORTEXAGENT_IMAGE_MODEL"):
    base = os.path.basename(_legacy)
    if base.lower().endswith(".safetensors"):
        os.environ["CORTEXAGENT_IMAGE_MODEL"] = base

from lib import diffusion_backend as _db  # noqa: E402


class GGUFImageGenerator:
    """Deprecated image generator — delegates to the diffusers backend.

    Kept for import compatibility. The ``model_path`` arg is accepted but
    ignored if it points at a GGUF (diffusers needs a .safetensors checkpoint
    filename, resolved by the backend from CORTEXAGENT_IMAGE_MODEL).
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._loaded = False

    def load(self) -> bool:
        # Local load is lazy — diffusers owns the model. "Loaded" == backend ready.
        self._loaded = _db.is_running()
        return self._loaded

    def generate(self, prompt: str, size: Tuple[int, int] = (512, 512),
                 num_steps: int = 20, guidance: float = 8.0,
                 seed: Optional[int] = None,
                 output: Optional[str] = None) -> Optional[str]:
        width, height = size
        out = output or str(Path.home() / "media" / "images" /
                            f"img_{int(_db.time.time())}.png")
        ok = _db.gen_image(prompt, output=out, width=width, height=height,
                           steps=num_steps, cfg=guidance, seed=seed)
        return out if ok else None

    def info(self) -> dict:
        s = _db.status()
        return {
            "backend": "diffusers (diffusion_backend)",
            "diffusers_ready": s["diffusers_ready"],
            "image_model": s["image_model"],
            "note": ("GGUF image models are not supported; image gen routes "
                     "through HuggingFace diffusers via lib.diffusion_backend."),
        }

    def unload(self):
        self._loaded = False


def main():
    parser = argparse.ArgumentParser(description="Image generation (diffusers)")
    sub = parser.add_subparsers(dest="command")
    gen = sub.add_parser("generate", help="Generate an image")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--model", default=None)
    gen.add_argument("--size", default="512x512")
    gen.add_argument("--steps", type=int, default=20)
    gen.add_argument("--guidance", type=float, default=8.0)
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--output", default=None)
    info = sub.add_parser("info")
    args = parser.parse_args()
    if args.command == "generate":
        w, h = map(int, args.size.split("x"))
        g = GGUFImageGenerator(args.model)
        out = g.generate(args.prompt, (w, h), args.steps, args.guidance,
                         args.seed, args.output)
        if out:
            print(f"\nImage saved to: {out}")
            return 0
        print("\nGeneration failed (see stderr)", file=sys.stderr)
        return 1
    if args.command == "info":
        print(json.dumps(GGUFImageGenerator().info(), indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())