from __future__ import annotations

import os

SH = ["#101010", "#262626", "#3c3c3c", "#545454",
      "#6e6e6e", "#8c8c8c", "#acacac", "#cccccc"]

# 2026-11-06 owner: the splash used to hardcode "qwen3.8-27B" and kept
# advertising the previous model after the upgrade. The launcher exports
# CORTEXENGINE_SPLASH_MODEL; the fallback stays in step with server.py's active
# profile so the banner can never drift silently again.
_MODEL_LABEL = os.environ.get("CORTEXENGINE_SPLASH_MODEL", "stock MoE (VRAM card)")

SHADES = [232, 234, 236, 240, 244, 248, 252, 255]

def shade(i: int) -> str:
    return "\033[38;5;%dm" % SHADES[i % 8]

# 2026-11-10 owner: splash stays GREYSCALE like the old agent, but the brain
# art is shades of red — the mark of the new build.
# 2026-11-10 owner: brain LIGHT PURPLE (no red, no white)
# 2026-11-10 owner: "16-bit shaded" — a 16-step purple ramp, smooth rows x
# texture gradient instead of 8 hard tones. Dark (0) -> brightest (15).
RAMP = [54, 61, 97, 98, 62, 99, 104, 105, 135, 140, 141, 141, 147, 141, 141, 141, 141, 141]  # violet-band xterm steps (hue 250-292)

def shade_red(i: int) -> str:
    return "\033[38;5;%dm" % RAMP[i % len(RAMP)]
# per-character brain shading (owner 11-10: "not shaded line by line"):
# mass █ bright purple, texture ▓ mid purple, sulci borders ▐▌ brighter,
# thin edges ▀▄ deepest purple — all PURPLE8, nothing red, nothing white.
def colorize_red(line: str, row: int) -> str:
    out, cur = [], None
    mod = 6 - min(6, max(0, row))
    M = len(RAMP) - 1
    for ch in line:
        if row < 2 and ch == "▄":
            r = max(0, M - 2)
        elif ch == "█":
            r = max(0, M - 3 + mod // 2)
        elif ch == "▓":
            r = max(0, M - 8 + mod // 2)
        elif ch in "▐▌":
            r = max(0, M - 5 + mod // 2)
        elif ch in "▀▄":
            r = max(0, M - 16 + mod // 2)
        elif ch in "╔╗╚╝═║":
            r = 13 + mod   # letter strokes get purple depth too, not solid
        else:
            r = None
        if r != cur:
            if r is not None:
                out.append("\033[38;5;%dm" % RAMP[max(0, min(len(RAMP) - 1, r))])
            elif cur is not None:
                out.append("\033[0m")
            cur = r
        out.append(ch)
    if cur is not None:
        out.append("\033[0m")
    return "".join(out)


_D = [
    # brain v5 (owner approved): scalloped crown, gyri/sulci channels, taper —
    # light-purple shaded; layout untouched (CORTEX above, AGENT below).
    "      ▄▄█▄▄▄▄▄█▄▄  ",
    "  ▄▄████▓▓▓█████▄ ",
    " ▐████▓▌▐▓▓▌▐▓▓██▄",
    " ████▓▌██▓▌██▓▌███",
    " ██▓▌███▓▌███▓▌██▀",
    " ██▓▌███▓▌███▓▌██ ",
    " ▀███▓▓███▓████▀  ",
    "   ▀▀▓▀▓▀▓▀▓▀▀    ",
]

def banner_rows() -> list:
    return _D

def _grey_banner() -> list:
    C = [" ██████╗ ", "██╔════╝ ", "██║      ", "██║      ", "██║      ", "╚██████╔╝"]
    O = [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "██║   ██║", "╚██████╔╝"]
    R = ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"]
    T = ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "]
    E = ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"]
    X = ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ",
        " ██╔██╗ ", "██╔╝ ╚██╗", "╚═╝   ╚═╝"]
    return ["".join(g[k] for g in [C, O, R, T, E, X]) for k in range(6)]

def _agent_banner() -> list:
    A = [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"]
    G = [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "]
    E = ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"]
    N = ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"]
    T = ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "]
    return ["    " + "".join(g[k] for g in [A, G, E, N, T]) for k in range(6)]

def splash_rows() -> list:
    CX = _grey_banner()
    AG = _agent_banner()
    rows = []
    for i in range(14):
        d = _D[i] if i < 8 else ""
        seg = d.ljust(19)
        if 1 <= i <= 6:
            seg = seg + CX[i - 1]
        elif 7 <= i <= 12:
            seg = d.ljust(19) + AG[i - 7]
        rows.append(seg)
    return rows

def splash_lines() -> list:
    out = []
    for i, seg in enumerate(splash_rows()):
        if i < 7 and seg.strip():
            out.append(colorize_red(seg + " ", i) + "\033[0m")
            continue
        if 1 <= i <= 6:
            out.append(colorize_red(seg[:19], i) + "\033[0m"
                       + "\033[38;5;%dm" % RAMP[max(0, len(RAMP)-4)] + seg[19:] + "\033[0m")
            continue
        if 7 <= i <= 12:
            art = (colorize_red(seg[:19], 7) + "\033[0m") if i == 7 else shade(2) + seg[:19]
            out.append(art + "\033[38;5;240m" + seg[19:].lstrip() + "\033[0m")
            continue
        if seg.strip():
            out.append(shade(6) + seg)
            continue
        out.append("")
    out.append("")
    for line in ["MODEL: %s" % _MODEL_LABEL,
                 "LIBRARY: /library → http://127.0.0.1:8792/library.html (◐ theme)",
                 "AUTHOR: greyok00",
                 "PROMPT: ~/.cortex-agent/agent/APPEND_SYSTEM.md"]:
        out.append(shade(6) + line)
    out.append("")
    out.append(shade(2) + "ctrl+c quit | ctrl+n new | ctrl+k sched | ctrl+f mem")
    return out

def SPLASH_MIN_W() -> int:
    return max(len(r) for r in splash_rows())

SPLASH_MIN_WIDTH = SPLASH_MIN_W()
SPLASH_MIN_HEIGHT = 15
SPLASH_TEXT = "\n".join(splash_lines())

DIGITS = {
    "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": [" █ ", "██ ", " █ ", " █ ", "███"],
    "2": ["███", "  █", "███", "█  ", "███"],
    "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"],
    "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"],
    "9": ["███", "█ █", "███", "  █", "███"],
    ".": ["   ", "   ", "   ", "   ", "  █"],
    " ": ["   ", "   ", "   ", "   ", "   "],
}

def big_number(value) -> str:
    text = ("%.1f" % value) if isinstance(value, (int, float)) else str(value)
    glyphs = [DIGITS.get(c, DIGITS[" "]) if len(c) == 1 else DIGITS[" "]
              for c in text]
    return "\n".join("    ".join(g[i] for g in glyphs) for i in range(5))

def compact_splash_lines() -> list:
    dev = _D[1]
    w = SPLASH_MIN_W()
    return [shade(5) + dev.rjust((w + len(dev)) // 2), "", shade(7) + "CORTEXAGENT",
            shade(5) + "MODEL: %s" % _MODEL_LABEL,
            shade(5) + "LIBRARY: /library → http://127.0.0.1:8792/library.html (◐ theme)",
            shade(5) + "AUTHOR: greyok00",
            shade(5) + "PROMPT: ~/.cortex-agent/agent/APPEND_SYSTEM.md", "",
            shade(2) + "ctrl+c quit | ctrl+n new | ctrl+k sched | ctrl+f mem"]

def compact_splash() -> str:
    return "\n".join(compact_splash_lines())
