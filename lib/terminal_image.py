#!/usr/bin/env python3

import os
import shutil
import subprocess
from typing import Optional


def detect_protocol() -> str:

    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    colorterm = os.environ.get("COLORTERM", "")


    if term_program.lower() == "kitty" or "kitty" in term.lower():
        return "kitty"

    if term_program.lower() == "iterm.app" or "iterm" in term.lower():
        return "iterm"

    if "sixel" in term.lower() or "sixel" in colorterm.lower():
        return "sixel"

    if "256color" in term or "truecolor" in colorterm.lower():
        return "ansi"
    return ""


def render_image(path: str, width: int = 60, height: Optional[int] = None) -> str:

    if not path or not os.path.exists(path):
        return ""
    chafa = shutil.which("chafa")
    if not chafa:
        return ""

    protocol = detect_protocol()


    size = f"{width}x{height}" if height else str(width)
    cmd = [chafa, "--format=symbols", "--size", size]
    if protocol == "sixel":
        cmd = [chafa, "--format=sixel", "--size", size]
    elif protocol == "kitty":
        cmd = [chafa, "--format=kitty", "--size", size]
    elif protocol == "iterm":
        cmd = [chafa, "--format=iterm", "--size", size]
    cmd.append(path)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def render_image_available() -> bool:

    return bool(shutil.which("chafa")) and bool(detect_protocol())
