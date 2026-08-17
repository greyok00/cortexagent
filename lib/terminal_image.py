#!/usr/bin/env python3
"""terminal_image.py — render images in the terminal via chafa.

BEAUTIFY-207: detects the terminal's image protocol (Sixel, Kitty, iTerm2,
or ANSI half-block fallback) and renders an image file in-place using chafa.

Pure helper — no server, no side effects beyond spawning chafa.

Usage:
  from lib.terminal_image import render_image, detect_protocol
  print(render_image("out.png", width=60))
"""
import os
import shutil
import subprocess
from typing import Optional


def detect_protocol() -> str:
    """Detect the best image protocol for the current terminal.

    Returns one of: "kitty", "sixel", "iterm", "ansi", or "" (unsupported).
    """
    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    colorterm = os.environ.get("COLORTERM", "")

    # Kitty protocol: TERM_PROGRAM=kitty or TERM contains kitty.
    if term_program.lower() == "kitty" or "kitty" in term.lower():
        return "kitty"
    # iTerm2.
    if term_program.lower() == "iterm.app" or "iterm" in term.lower():
        return "iterm"
    # Sixel: TERM mentions sixel, or COLORTERM hints at it.
    if "sixel" in term.lower() or "sixel" in colorterm.lower():
        return "sixel"
    # ANSI half-block fallback works in most 256-color terminals.
    if "256color" in term or "truecolor" in colorterm.lower():
        return "ansi"
    return ""


def render_image(path: str, width: int = 60, height: Optional[int] = None) -> str:
    """Render an image file in the terminal via chafa.

    Args:
        path: Path to the image file
        width: Target width in cells
        height: Optional target height in cells

    Returns: The terminal escape sequence (or ANSI art) to display, or an
             empty string if chafa is unavailable or the file is missing.
    """
    if not path or not os.path.exists(path):
        return ""
    chafa = shutil.which("chafa")
    if not chafa:
        return ""

    protocol = detect_protocol()
    cmd = [chafa, "--format=symbols", "--size", f"{width}x{height or 0}"]
    if protocol == "sixel":
        cmd = [chafa, "--format=sixel", "--size", f"{width}x{height or 0}"]
    elif protocol == "kitty":
        cmd = [chafa, "--format=kitty", "--size", f"{width}x{height or 0}"]
    elif protocol == "iterm":
        cmd = [chafa, "--format=iterm", "--size", f"{width}x{height or 0}"]
    cmd.append(path)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def render_image_available() -> bool:
    """Return True if chafa is installed and a protocol is detected."""
    return bool(shutil.which("chafa")) and bool(detect_protocol())
