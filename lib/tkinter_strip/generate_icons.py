
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_DIR = Path(__file__).parent / "icons"
ICON_DIR.mkdir(exist_ok=True)

SIZE = 28
BG = (15, 17, 21, 0)

FACE_TOP = (62, 66, 72, 255)
FACE_BOTTOM = (28, 30, 34, 255)
BEZEL_LIGHT = (140, 144, 150, 255)
BEZEL_DARK = (10, 11, 13, 255)
TEXT_COLOR = (255, 255, 255, 255)
DOT_COLOR = (255, 176, 0, 255)


def _find_font(size: int) -> ImageFont.FreeTypeFont:

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

    img = Image.new("RGBA", (SIZE, SIZE), BG)


    bezel = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(bezel).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=5, fill=BEZEL_DARK
    )


    ImageDraw.Draw(bezel).line(
        [(2, SIZE - 3), (2, 2), (SIZE - 3, 2)], fill=BEZEL_LIGHT, width=1
    )


    face = Image.new("RGBA", (SIZE - 4, SIZE - 4), FACE_TOP)
    face_draw = ImageDraw.Draw(face)
    for y in range(SIZE - 4):

        t = y / max(1, SIZE - 5)
        r = int(FACE_TOP[0] * (1 - t) + FACE_BOTTOM[0] * t)
        g = int(FACE_TOP[1] * (1 - t) + FACE_BOTTOM[1] * t)
        b = int(FACE_TOP[2] * (1 - t) + FACE_BOTTOM[2] * t)
        face_draw.line([(0, y), (SIZE - 4, y)], fill=(r, g, b, 255))

    img.paste(bezel, (0, 0), bezel)
    img.paste(face, (2, 2), face)


    draw = ImageDraw.Draw(img)

    if len(label) <= 4:
        font_size = 10
    elif len(label) <= 5:
        font_size = 9
    else:
        font_size = 8
    font = _find_font(font_size)


    text_color_main = TEXT_COLOR
    if accent_dot and label.endswith("."):
        main = label[:-1]
        dot = "."

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

    icons = [
        ("Esc.",  "esc.png",    True),
        ("C+C",   "ctrl_c.png", False),
        ("📎",    "clip.png",   False),
        ("↵",    "enter.png",  False),
    ]
    for label, fname, accent in icons:
        out = ICON_DIR / fname
        render_key(label, out, accent_dot=accent)
        print(f"  ✅ {out}  ({SIZE}×{SIZE}, label={label!r})")


if __name__ == "__main__":
    main()