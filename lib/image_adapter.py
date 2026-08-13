#!/usr/bin/env python3
"""lib/image_adapter.py — Moondream 2 (0.5B) captioning/VQA/pointing.

Converts image input to plain text so the text-only overseer model can reason
about it. Lazy singleton: the model loads on first use (one-time ~1.7GB
download to ~/.cache/huggingface/), never at import time. GPU when the VRAM
budget allows (lib/vram.can_fit), else CPU — the big model, overseer, and
faster-whisper are required residents and are never evicted; Moondream uses
only the free VRAM minus the locked buffer.

Usage:
  python3 lib/image_adapter.py --smoke
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MODEL_ID = "vikhyatk/moondream2"
REVISION = "2025-06-21"
DEFAULT_PROMPT = "Describe this image in detail."
# fp32 weights + activations. The plan estimated 2048 (fp16 ~1.9GB), but the
# patched hf_moondream.py loads fp32 (bf16-on-CPU was NaN), so the real
# footprint is ~4x larger: measured 7.6GB loaded, 8.7GB at inference peak.
# 9216 only fits when the big model is down (budget ~12.7GB).
MOONDREAM_VRAM_MB = 9216

_model = None  # lazy singleton


def _get_model():
    """Load (once) the Moondream 2 model. GPU when the VRAM budget allows,
    else CPU (never evicts the big model / overseer / whisper)."""
    global _model
    if _model is None:
        from transformers import AutoModelForCausalLM
        from lib import vram
        device = "cuda" if vram.can_fit(MOONDREAM_VRAM_MB) else "cpu"
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=REVISION, trust_remote_code=True,
            device_map={"": device})
        # Defensive: transformers 5.13 corrupts persistent=False buffers
        # (attn_mask, freqs_cis) during from_pretrained. The cache's
        # hf_moondream.py patches this, but rebuild here too so the adapter
        # works even if the HF cache is cleared.
        if hasattr(_model, "_rebuild_buffers"):
            _model._rebuild_buffers()
    return _model


def describe(image_path: str, prompt: str = DEFAULT_PROMPT) -> str:
    """Caption or answer a VQA prompt about the image. Returns text."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    from PIL import Image
    model = _get_model()
    image = Image.open(path).convert("RGB")
    if prompt == DEFAULT_PROMPT:
        return model.caption(image, length="normal")["caption"]
    return model.query(image, prompt)["answer"]


def point(image_path: str, object: str) -> str:
    """Return normalized coordinates of an object (Moondream pointing)."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    from PIL import Image
    model = _get_model()
    image = Image.open(path).convert("RGB")
    points = model.point(image, object)["points"]
    if not points:
        return "not found"
    return ", ".join(
        f"({p['x_min']:.3f},{p['y_min']:.3f})-({p['x_max']:.3f},{p['y_max']:.3f})"
        for p in points)


def _smoke() -> int:
    fails = 0
    import shutil
    import tempfile
    from pathlib import Path
    import torch
    from lib import vram
    # Decide the expected device BEFORE any model load — once Moondream is on
    # GPU it consumes ~7.5GB, so a post-load can_fit() would wrongly say "no".
    want_cuda = vram.can_fit(MOONDREAM_VRAM_MB) if torch.cuda.is_available() else False
    tmp = Path(tempfile.mkdtemp())
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (320, 240), "white")
        ImageDraw.Draw(img).ellipse((120, 80, 200, 160), fill="red")
        img.save(tmp / "sample.png")
        cap = describe(str(tmp / "sample.png"))
        if not cap or not cap.strip():
            print("❌ describe empty")
            fails += 1
        else:
            print(f"✅ caption: {cap[:80]}")
        # device assertion — model must be on the device the VRAM budget chose
        if torch.cuda.is_available():
            if next(_get_model().parameters()).is_cuda != want_cuda:
                print(f"❌ model on wrong device (expected {'cuda' if want_cuda else 'cpu'})")
                fails += 1
        # missing file → clean error, no model load
        try:
            describe(str(tmp / "nope.png"))
            print("❌ missing file did not raise")
            fails += 1
        except FileNotFoundError:
            pass
    except Exception as e:
        print(f"❌ image_adapter smoke: {e}")
        fails += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("image_adapter smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/image_adapter.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
