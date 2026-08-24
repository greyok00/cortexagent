#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib.config import CFG


ICE = "\033[38;2;150;220;255m"
RED = "\033[38;2;224;88;74m"
DIM = "\033[2m"
RST = "\033[0m"
HOME = "\033[H"
CLEAR_EOL = "\033[K"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"









LOGO = [
    "█▄        ▄█",
    "███▄▄▄▄▄▄███",
    " ██ ▀██▀ ██",
    " ███▀▀▀▀███",
    "▄██████████▄",
    "██▀██████▀██",
    "   ██████",
    "  ▄█▀  ▀█▄",
]
LOGO_H = len(LOGO)
LOGO_W = max(len(ln) for ln in LOGO)
TAG_H = 2


def _pad(ln: str) -> str:

    return ln.ljust(LOGO_W)


def _color_for(line_idx: int) -> str:

    return RED


def _frames() -> list[str]:

    frames: list[str] = []
    for i in range(LOGO_H + 1):
        rows: list[str] = []
        for j in range(LOGO_H):
            if j < i:
                color = _color_for(j)
                rows.append(f"{color}{_pad(LOGO[j])}{RST}{CLEAR_EOL}")
            else:
                rows.append(f"{' ' * LOGO_W}{CLEAR_EOL}")
        if i == LOGO_H:
            rows.append(f"{ICE}CORTEXAGENT · by {CFG.author}{RST}{CLEAR_EOL}")
            rows.append(f"{DIM}Model: {_model_placeholder}{RST}{CLEAR_EOL}")
        else:
            rows.append(f"{' ' * (len(CFG.author) + 24)}{CLEAR_EOL}")
            rows.append(f"{' ' * 16}{CLEAR_EOL}")
        frames.append(HOME + "\n".join(rows))
    return frames




_model_placeholder = ""


def _frames_for(model: str) -> list[str]:
    global _model_placeholder
    _model_placeholder = model or ""
    return _frames()


def print_banner(model: str = "", stream=None) -> None:

    stream = stream or sys.stdout
    stream.write("\n")
    for idx, ln in enumerate(LOGO):
        stream.write(f"  {_color_for(idx)}{ln}{RST}\n")
    stream.write(f"  {ICE}CORTEXAGENT · by {CFG.author}{RST}\n")
    stream.write(f"  {DIM}Model: {model or '?'}{RST}\n")
    stream.write("\n")
    stream.flush()




DEVIL_LINES = LOGO


def render_devil_plain() -> str:

    return "\n".join(LOGO)


def boot(model: str = "", stream=None, delay: float = 0.06) -> None:

    stream = stream or sys.stdout
    frames = _frames_for(model)
    stream.write(HIDE_CURSOR)
    stream.flush()
    try:
        for f in frames:
            stream.write(f)
            stream.flush()
            time.sleep(delay)

        time.sleep(0.15)
    finally:
        stream.write(SHOW_CURSOR)
        stream.flush()


def _is_tty() -> bool:
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "").lower()
    if not term or term in ("dumb", "emacs", "vt100"):
        return False
    return True


def main() -> int:
    args = sys.argv[1:]
    no_anim = "--no-anim" in args or os.environ.get("CORTEXAGENT_BOOT_ANIM", "1") == "0"
    model = ""
    for a in args:
        if a.startswith("--model="):
            model = a.split("=", 1)[1]
        elif a == "--model" and args.index(a) + 1 < len(args):
            model = args[args.index(a) + 1]
    if _is_tty() and not no_anim:
        boot(model)
    else:
        print_banner(model)
    return 0


def _smoke() -> int:

    import io
    buf = io.StringIO()
    print_banner("Qwen-test", stream=buf)
    out = buf.getvalue()
    assert "CORTEXAGENT" in out, "brand missing"
    assert "Model: Qwen-test" in out, "model line missing"
    assert "\033[?25" not in out, "static banner must not use cursor codes"
    assert RED in out, "devil brand red missing"
    assert "█▄        ▄█" in out, "devil horns missing"
    print(f"  static: brand+model present, devil glyph + red "
          f"({len(out.splitlines())} lines)")


    frames = _frames_for("Qwen-test")
    assert len(frames) == LOGO_H + 1, f"frame count {len(frames)} != {LOGO_H + 1}"
    h = [len(f.split("\n")) for f in frames]
    assert len(set(h)) == 1, f"frames not uniform: {h}"
    for f in frames:
        assert "\033[2J" not in f, "frame uses clear-screen (forbidden)"
        assert "\033[H" in f, "frame missing cursor-home"
        assert CLEAR_EOL in f, "frame missing EOL clear (residue risk)"

    final = frames[-1]
    assert RED in final and ICE in final, "final frame missing lit glyph/brand"
    assert "CORTEXAGENT" in final, "brand wordmark missing"

    assert RED not in frames[0], "first frame should light nothing"
    print(f"  frames: {len(frames)} uniform ({h[0]} lines each), no clear, EOL-cleared, lit-final")

    plain = render_devil_plain()
    assert plain.count("\n") == LOGO_H - 1, "plain devil lines count mismatch"
    assert "▀██▀" in plain, "devil eyes missing from plain"
    print(f"  plain: {LOGO_H} rows, eyes + horns intact")
    print("banner: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    sys.exit(main())