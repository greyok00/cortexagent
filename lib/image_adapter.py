#!/usr/bin/env python3
"""lib/image_adapter.py — Moondream 2 (0.5B) captioning/VQA/pointing, CPU.

Converts image input to plain text so the text-only overseer model can reason
about it. Lazy singleton: the model loads on first use (one-time ~1.7GB
download to ~/.cache/huggingface/), never at import time. CPU forced via
device_map={"": "cpu"} — torch must not grab CUDA (GPU stays reserved for
the big model).

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

_model = None  # lazy singleton


def _get_model():
    """Load (once) the Moondream 2 model on CPU. Returns the model."""
    global _model
    if _model is None:
        from transformers import AutoModelForCausalLM
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=REVISION, trust_remote_code=True,
            device_map={"": "cpu"})
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
        # CPU assertion — model must be on CPU even though CUDA exists
        import torch
        if torch.cuda.is_available():
            if next(_get_model().parameters()).is_cuda:
                print("❌ model on CUDA (must be CPU)")
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
