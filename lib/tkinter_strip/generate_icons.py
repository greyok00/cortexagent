"""lib/tkinter_strip/generate_icons.py — render the 4 keyboard-key icons.

2026-08-21 user feedback:
- "Each should be half the size and click in so they look like real
  keyboard keys when clicked."
- "Make it say Esc. instead of ESC."

Each icon is a small (28×28) PNG of a 3D-beveled keyboard key cap with the
key's label baked in. The bevel uses two gradient rings (lighter top-left,
darker bottom-right) to read as a depressable physical key. Run this
script to regenerate:

  python3 lib/tkinter_strip/generate_icons.py
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_DIR = Path(__file__).parent / "icons"
ICON_DIR.mkdir(exist_ok=True)

SIZE = 28  # 2026-08-21: half the prior 56px size (user "half the size")
BG = (15, 17, 21, 0)  # transparent
# Key face colors (agent-pulse dark theme)
FACE_TOP = (62, 66, 72, 255)   # light top face
FACE_BOTTOM = (28, 30, 34, 255) # darker bottom face (for gradient)
BEZEL_LIGHT = (140, 144, 150, 255)   # upper-left highlight
BEZEL_DARK = (10, 11, 13, 255)        # lower-right shadow
TEXT_COLOR = (255, 255, 255, 255)      # white label
DOT_COLOR = (255, 176, 0, 255)         # amber accent dot (Esc.)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """Try a few common fonts that ship with most Linux distros."""
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_key(
    label: str,
    out_path: Path,
    accent_dot: bool = False,
) -> None:
    """Render a single keyboard key icon.

    - Outer 1px rounded square = bezel (gradient via two stacked quads).
    - Inner 2px inset = the key face (also gradient).
    - Centered label in white bold.
    - If accent_dot: trailing period rendered in amber (Esc. look).
    """
    img = Image.new("RGBA", (SIZE, SIZE), BG)

    # ── Bezel (outer rounded rect, dark frame) ────────────────────────────
    bezel = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(bezel).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=5, fill=BEZEL_DARK
    )

    # Upper-left highlight (lighter bevel)
    ImageDraw.Draw(bezel).line(
        [(2, SIZE - 3), (2, 2), (SIZE - 3, 2)], fill=BEZEL_LIGHT, width=1
    )

    # ── Key face (inset by 2px) with vertical gradient ────────────────────
    face = Image.new("RGBA", (SIZE - 4, SIZE - 4), FACE_TOP)
    face_draw = ImageDraw.Draw(face)
    for y in range(SIZE - 4):
        # interpolate FACE_TOP → FACE_BOTTOM
        t = y / max(1, SIZE - 5)
        r = int(FACE_TOP[0] * (1 - t) + FACE_BOTTOM[0] * t)
        g = int(FACE_TOP[1] * (1 - t) + FACE_BOTTOM[1] * t)
        b = int(FACE_TOP[2] * (1 - t) + FACE_BOTTOM[2] * t)
        face_draw.line([(0, y), (SIZE - 4, y)], fill=(r, g, b, 255))

    img.paste(bezel, (0, 0), bezel)
    img.paste(face, (2, 2), face)

    # ── Label (centered) ──────────────────────────────────────────────────
    draw = ImageDraw.Draw(img)
    # Auto-fit font size to the label length so "Esc." and "ATTACH" both fit
    if len(label) <= 4:
        font_size = 10
    elif len(label) <= 5:
        font_size = 9
    else:
        font_size = 8
    font = _find_font(font_size)

    # If accent_dot mode, split label on '.' and color the period amber
    text_color_main = TEXT_COLOR
    if accent_dot and label.endswith("."):
        main = label[:-1]
        dot = "."
        # Measure widths to center the combined string
        w_main = draw.textlength(main, font=font)
        w_dot = draw.textlength(dot, font=font)
        total_w = w_main + w_dot
        x = (SIZE - total_w) / 2
        y = (SIZE - font_size) / 2 - 1
        draw.text((x, y), main, fill=text_color_main, font=font)
        draw.text((x + w_main, y), dot, fill=DOT_COLOR, font=font)
    else:
        bbox = draw.textbbox((0, 0), label, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (SIZE - w) / 2 - bbox[0]
        y = (SIZE - h) / 2 - bbox[1] - 1
        draw.text((x, y), label, fill=text_color_main, font=font)

    img.save(out_path, "PNG")


def main() -> None:
    # 2026-08-21: "Esc." casing (was "ESC"), Ctrl+C token stays compact
    icons = [
        ("Esc.",  "esc.png",    True),   # accent_dot=True → amber period
        ("C+C",   "ctrl_c.png", False),
        ("📎",    "clip.png",   False),  # paperclip emoji (acts as attach)
        ("↵",    "enter.png",  False),
    ]
    for label, fname, accent in icons:
        out = ICON_DIR / fname
        render_key(label, out, accent_dot=accent)
        print(f"  ✅ {out}  ({SIZE}×{SIZE}, label={label!r})")


if __name__ == "__main__":
    main()