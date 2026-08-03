#!/usr/bin/env python3
"""cortexagent banner — branded startup banner + in-place boot animation.

Replaces the suppressed Claude Code welcome chrome (`IS_DEMO=1` in
``bin/cortexagent``) with a CortexAgent banner. Uses ANSI cursor control so
the boot animation overwrites itself in place — NO ``clear`` / ``\\033[2J``
(that strobes/flickers). Cursor is sent home with ``\\033[H`` between frames
and hidden during the animation (``\\033[?25l`` → ``\\033[?25h``); every line
ends with ``\\033[K`` (clear-to-EOL) so a shorter frame never leaves the
previous frame's trailing characters visible.

Non-interactive / piped runs (no TTY, or ``CORTEXAGENT_BOOT_ANIM=0``) get the
static banner — one compact block, no cursor codes — so smoke tests and logs
stay clean.

Usage:
  python3 lib/banner.py --model <name>            # TTY → animate, else static
  python3 lib/banner.py --model <name> --no-anim  # force static
  python3 lib/banner.py smoke                      # self-test
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib.config import CFG  # author tag is configurable (CORTEXAGENT_AUTHOR)

# ── ANSI ────────────────────────────────────────────────────────────────────
ICE = "\033[38;2;150;220;255m"   # truecolor ice-blue (logo)
DIM = "\033[2m"
RST = "\033[0m"
HOME = "\033[H"                   # cursor → top-left (replaces `clear`)
CLEAR_EOL = "\033[K"              # clear from cursor to end-of-line
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

# ── Logo ────────────────────────────────────────────────────────────────────
# Frame-uniform: every frame has the same line count (LOGO + 2 tagline rows),
# so \033[H overwrites cleanly. Each rendered line is padded to LOGO_W and gets
# a trailing \033[K so a shorter glyph never leaks the prior frame's tail.
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
TAG_H = 2  # "CORTEXAGENT by <author>" + "Model: <name>"


def _pad(ln: str) -> str:
    """Pad a logo line to LOGO_W with spaces (uniform frame width)."""
    return ln.ljust(LOGO_W)


def _frames() -> list[str]:
    """Progressive-reveal boot frames (top-down), each a full-height block.

    Frame i lights the first i logo rows; the rest are blank. The two
    tagline rows appear only on the final frame (blank before). Every line
    carries \\033[K so overwrite leaves no residue. Returns N+1 frames
    (N = LOGO_H), each prefixed with \\033[H.
    """
    frames: list[str] = []
    for i in range(LOGO_H + 1):
        rows: list[str] = []
        for j in range(LOGO_H):
            if j < i:
                rows.append(f"{ICE}{_pad(LOGO[j])}{RST}{CLEAR_EOL}")
            else:
                rows.append(f"{' ' * LOGO_W}{CLEAR_EOL}")
        if i == LOGO_H:
            rows.append(f"{DIM}CORTEXAGENT by {CFG.author}{RST}{CLEAR_EOL}")
            rows.append(f"{DIM}Model: {_model_placeholder}{RST}{CLEAR_EOL}")
        else:
            rows.append(f"{' ' * (len(CFG.author) + 18)}{CLEAR_EOL}")
            rows.append(f"{' ' * 16}{CLEAR_EOL}")
        frames.append(HOME + "\n".join(rows))
    return frames


# _model_placeholder is swapped per-run in boot()/print_banner(); the static
# frame list above is rebuilt with the real model so the width is stable.
_model_placeholder = ""


def _frames_for(model: str) -> list[str]:
    global _model_placeholder
    _model_placeholder = model or ""
    return _frames()


def print_banner(model: str = "", stream=None) -> None:
    """Emit the static banner once (no cursor codes). For non-TTY / logs."""
    stream = stream or sys.stdout
    stream.write("\n")
    for ln in LOGO:
        stream.write(f"  {ICE}{ln}{RST}\n")
    stream.write(f"  {DIM}CORTEXAGENT by {CFG.author}{RST}\n")
    stream.write(f"  {DIM}Model: {model or '?'}{RST}\n")
    stream.write("\n")
    stream.flush()


def boot(model: str = "", stream=None, delay: float = 0.06) -> None:
    """In-place animated reveal. TTY-only. No ``clear`` — uses \\033[H."""
    stream = stream or sys.stdout
    frames = _frames_for(model)
    stream.write(HIDE_CURSOR)
    stream.flush()
    try:
        for f in frames:
            stream.write(f)
            stream.flush()
            time.sleep(delay)
        # Hold the finished banner briefly before the agent takes over.
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
    # Static banner has the brand + model line.
    import io
    buf = io.StringIO()
    print_banner("Qwen-test", stream=buf)
    out = buf.getvalue()
    assert "CORTEXAGENT" in out, "brand missing"
    assert "Model: Qwen-test" in out, "model line missing"
    assert "\033[?25" not in out, "static banner must not use cursor codes"
    print(f"  static: brand+model present, no cursor codes ({len(out.splitlines())} lines)")

    # Frames: uniform line count, no clear-screen, EOL clear on every line.
    frames = _frames_for("Qwen-test")
    assert len(frames) == LOGO_H + 1, f"frame count {len(frames)} != {LOGO_H + 1}"
    h = [len(f.split("\n")) for f in frames]
    assert len(set(h)) == 1, f"frames not uniform: {h}"
    assert len(set(h)) == 1
    for f in frames:
        assert "\033[2J" not in f, "frame uses clear-screen (forbidden)"
        assert "\033[H" in f, "frame missing cursor-home"
        assert CLEAR_EOL in f, "frame missing EOL clear (residue risk)"
    # Final frame lights every logo row + tagline.
    final = frames[-1]
    assert ICE in final and "CORTEXAGENT by" in final, "final frame missing lit logo/tagline"
    # First frame is all blank rows (nothing lit yet).
    assert ICE not in frames[0], "first frame should light nothing"
    print(f"  frames: {len(frames)} uniform ({h[0]} lines each), no clear, EOL-cleared, lit-final")
    print("banner: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    sys.exit(main())