#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


def detect_color_depth() -> str:

    colorterm = os.environ.get("COLORTERM", "")
    if colorterm in ("truecolor", "24bit"):
        return "truecolor"

    try:
        result = subprocess.run(
            ["tput", "colors"],
            capture_output=True, text=True, timeout=5
        )
        colors = int(result.stdout.strip())
        if colors >= 256:
            return "256"
        elif colors >= 16:
            return "16"
    except Exception:
        pass

    return "256"


def get_truecolor_index(r: int, g: int, b: int) -> int:

    return f"\033[38;2;{r};{g};{b}m"


def get_256color_index(r: int, g: int, b: int) -> int:







    mapping = {
        0: 0,
        95: 1,
        134: 2,
        173: 3,
        211: 4,
        255: 5,
    }

    r_idx = next((v for k, v in mapping.items() if r <= k), 5)
    g_idx = next((v for k, v in mapping.items() if g <= k), 5)
    b_idx = next((v for k, v in mapping.items() if b <= k), 5)

    return 16 + r_idx * 36 + g_idx * 6 + b_idx


def get_ansi_color(r: int, g: int, b: int, depth: str = "truecolor") -> str:

    if depth == "truecolor":
        return get_truecolor_index(r, g, b)
    elif depth == "256":
        idx = get_256color_index(r, g, b)
        return f"\033[38;5;{idx}m"
    else:


        avg = (r + g + b) // 3
        if avg < 85:
            return "\033[30m"
        elif avg < 170:
            return "\033[90m"
        else:
            return "\033[37m"







SEMANTIC_ROLES = {
    "accent": (127, 212, 201),
    "success": (158, 206, 106),
    "warn": (224, 175, 104),
    "danger": (247, 118, 142),
    "info": (122, 162, 247),
    "muted": (86, 95, 137),
    "fg": (192, 202, 245),
    "bg": (26, 27, 38),
}


class Palette:


    def __init__(self, theme_path: Optional[str] = None):

        self.depth = detect_color_depth()
        self.colors: Dict[str, str] = {}


        theme_file = theme_path or os.environ.get(
            "CORTEXAGENT_THEME",
            str(Path.home() / ".cortexagent" / "theme.json"),
        )
        theme = self._load_theme(theme_file)


        if theme:
            for role, rgb in theme.items():
                if role in SEMANTIC_ROLES:
                    SEMANTIC_ROLES[role] = tuple(rgb)


        for role, (r, g, b) in SEMANTIC_ROLES.items():
            self.colors[role] = get_ansi_color(r, g, b, self.depth)

        self.reset = "\033[0m"
        self.bold = "\033[1m"

    def _load_theme(self, theme_path: str) -> Optional[Dict]:

        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def __getattr__(self, name: str) -> str:

        if name in self.colors:
            return self.colors[name]
        raise AttributeError(f"Palette has no role '{name}'")

    def color(self, role: str, text: str) -> str:

        if role in self.colors:
            return f"{self.colors[role]}{text}{self.reset}"
        return text

    def status_glyph(self, state: str, text: str) -> str:

        glyphs = {
            "alive": ("●", "success"),
            "idle": ("○", "muted"),
            "warn": ("!", "warn"),
            "error": ("✕", "danger"),
            "rising": ("▲", "success"),
            "falling": ("▼", "warn"),
            "flat": ("▶", "muted"),
            "pending": ("◌", "muted"),
            "firing": ("◍", "info"),
            "done": ("✓", "success"),
            "blocked": ("⊘", "danger"),
            "unknown": ("?", "muted"),
        }

        glyph, role = glyphs.get(state, ("?", "muted"))
        color = self.colors.get(role, self.colors["muted"])
        return f"{color}{glyph} {text}{self.reset}"

    def theme_info(self) -> str:

        theme_path = os.environ.get(
            "CORTEXAGENT_THEME",
            str(Path.home() / ".cortexagent" / "theme.json"),
        )
        return f"Depth: {self.depth}, Theme: {theme_path}"




_palette = None

def get_palette() -> Palette:

    global _palette
    if _palette is None:
        _palette = Palette()
    return _palette


def color_text(role: str, text: str) -> str:

    pal = get_palette()
    return pal.color(role, text)


def status_glyph(state: str, text: str) -> str:

    pal = get_palette()
    return pal.status_glyph(state, text)


def main():

    pal = Palette()
    print(f"Palette: {pal.theme_info()}")
    print(f"Reset: {pal.reset}")
    print()
    for role in SEMANTIC_ROLES:
        print(f"  {role:10s}: {pal.color(role, 'Hello World')}")
    print()
    print("Status glyphs:")
    for state in ["alive", "idle", "warn", "error", "done"]:
        print(f"  {state:10s}: {pal.status_glyph(state, 'Status text')}")


if __name__ == "__main__":
    main()
