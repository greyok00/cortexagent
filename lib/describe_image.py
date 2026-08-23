#!/usr/bin/env python3
"""lib/describe_image.py — Local vision fallback for image requests.

The main model (Claude) is NOT multimodal in this setup, so any image it needs
to understand would 400. This script routes the image to a LOCAL vision model
(qwen3-vl:fixed via ollama), which produces a large, detailed text description.
That description is printed to stdout so the main model can consume it as text.

Usage:
    python3 lib/describe_image.py /path/to/image.png
    python3 lib/describe_image.py /path/to/image.png "focus on the left panel"
    cat /path/to/image.png | python3 lib/describe_image.py -   # read from stdin

Exit code 0 on success (description on stdout), 1 on failure (error on stderr).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.environ.get("CORTEXAGENT_VISION_MODEL", "qwen3-vl:fixed")

# Ask for a thorough description — the main model needs enough detail to act on
# the image without ever seeing it.
_DEFAULT_PROMPT = (
    "Describe this image in exhaustive detail. Cover: layout and position of "
    "every element, all visible text (verbatim), colors, sizes, spacing, any "
    "icons or symbols, and the overall purpose of the screen. Be specific and "
    "complete — the reader cannot see the image, only your words."
)


MAX_SIDE = int(os.environ.get("CORTEXAGENT_VISION_MAX_SIDE", "1024"))


def _read_image(path: str) -> bytes:
    """Read the image, downscaling to MAX_SIDE so the vision model isn't
    choked by huge screenshots (vision models process pixels — a 4K capture
    is far more work than the model needs to describe it)."""
    raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(raw))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        if longest > MAX_SIDE:
            scale = MAX_SIDE / longest
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # No PIL or decode failure — send the original bytes.
        return raw


def describe(image_path: str, prompt: str = _DEFAULT_PROMPT) -> str:
    """Send the image to the local vision model and return its description."""
    img_b64 = base64.b64encode(_read_image(image_path)).decode("ascii")
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [img_b64],
        }],
        "stream": False,
        "options": {"num_predict": 600, "temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return (resp.get("message") or {}).get("content", "").strip()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: describe_image.py <image.png|-> [prompt]", file=sys.stderr)
        return 1
    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_PROMPT
    try:
        print(describe(image_path, prompt))
        return 0
    except Exception as e:
        print(f"describe_image failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
