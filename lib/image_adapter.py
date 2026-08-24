#!/usr/bin/env python3

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




MOONDREAM_VRAM_MB = 9216

_model = None


def _get_model():

    global _model
    if _model is None:
        import torch
        from transformers import AutoModelForCausalLM
        from lib import vram
        want_cuda = vram.can_fit(MOONDREAM_VRAM_MB) if torch.cuda.is_available() else False
        device = "cuda" if want_cuda else "cpu"


        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=REVISION, trust_remote_code=True,
        ).to(device)




        if hasattr(_model, "_rebuild_buffers"):
            _model._rebuild_buffers()
    return _model


def describe(image_path: str, prompt: str = DEFAULT_PROMPT) -> str:

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

        if torch.cuda.is_available():
            if next(_get_model().parameters()).is_cuda != want_cuda:
                print(f"❌ model on wrong device (expected {'cuda' if want_cuda else 'cpu'})")
                fails += 1

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
