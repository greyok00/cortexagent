"""lib/popup_themes.py — Greyok UI framework theme bridge for the popup + STT.

Reads the same themes.css the HTML demos use (`ui-mockups/_elements/
themes.css`) and exposes the 12 framework themes to the GTK popup +
Tkinter STT panel via a flat dict mapping framework tokens
(`--el-bg`, `--el-accent`, ...) to CSS colors that GTK CSSProvider +
Tkinter can consume.

Adding a theme = adding a `[data-theme="<slug>"]` block to themes.css.
This module auto-discovers them at import time.

Fallback: when themes.css can't be found, falls back to a minimal
"cockpit" mapping (aviation HMI dark + amber — closest to the
original popup default).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

# ── Locate themes.css ───────────────────────────────────────────────────────
# Walk up from this file to find ui-mockups/_elements/themes.css. The
# repo layout: this file lives at lib/popup_themes.py; the framework
# CSS lives at ui-mockups/_elements/themes.css. Also support the
# standalone ~/ui-framework dir for users who only have the framework
# checked out (not the cortexagent repo).

_THEMES_CSS_REL = Path("ui-mockups/_elements/themes.css")
_FALLBACK_CSS_REL = Path("ui-framework/themes")
_HOME_FALLBACK = Path.home() / "ui-framework" / "themes"


def _find_themes_css() -> Path | None:
    """Locate the framework's themes.css. Returns None when no source
    is reachable so the caller can fall back to the hardcoded cockpit
    palette.
    """
    candidates = []
    # 1. Repo-relative (cortexagent layout).
    here = Path(__file__).resolve().parent.parent  # lib/../
    candidates.append(here / _THEMES_CSS_REL)
    # 2. ~/ui-framework standalone dir — read any *.md for token hints
    #    if themes.css isn't shipped there.
    candidates.append(_HOME_FALLBACK / "themes.css")
    candidates.append(Path("/home/grey/cortexagent/ui-mockups/_elements/themes.css"))
    for p in candidates:
        if p.exists():
            return p
    return None


# ── Theme catalog ──────────────────────────────────────────────────────────

# Each entry is a flat dict of named CSS colors that the popup's
# Gtk.CssProvider rebuilds when Apply is pressed, and the STT panel
# reads from ~/.cortexagent/popup_settings.json on its heartbeat refresh.
#
# Mapped from the 12 framework themes in themes.css. Each theme picks:
#   bg, bg_alt  → window bg + secondary panel
#   fg, fg_dim  → text + dim text
#   accent      → header / button accent
#   border      → hairline dividers
#   success, warning, danger → semantic state colors
#   hover_bg, hover_fg → button hover surface
#   on_accent   → text on accent (kept for completeness)
DEFAULT_THEMES: Dict[str, Dict[str, str]] = {
    "polaroid": {
        "label":    "polaroid",
        "bg":       "#faf3e3", "bg_alt":   "#f1e8d0",
        "fg":       "#3a2e22", "fg_dim":   "#7a6952",
        "accent":   "#b8693c", "border":   "#d4c69b",
        "success":  "#5a7a4a", "warning":  "#c18a2c", "danger":   "#a83232",
        "hover_bg": "#e8dec2", "hover_fg": "#3a2e22", "on_accent": "#faf3e3",
    },
    "cockpit": {
        "label":    "cockpit",
        "bg":       "#0a1218", "bg_alt":   "#14242e",
        "fg":       "#dde6f0", "fg_dim":   "#6b8497",
        "accent":   "#ffb000", "border":   "#1c2a36",
        "success":  "#5fe09a", "warning":  "#ffd166", "danger":   "#ff5a52",
        "hover_bg": "#1a2e3a", "hover_fg": "#dde6f0", "on_accent": "#0a1218",
    },
    "cockpit-paper": {
        "label":    "cockpit-paper",
        "bg":       "#1a1814", "bg_alt":   "#252118",
        "fg":       "#f0e8d8", "fg_dim":   "#a39479",
        "accent":   "#d4a85a", "border":   "#3d3628",
        "success":  "#8aa66b", "warning":  "#e6c060", "danger":   "#e06c5a",
        "hover_bg": "#38331f", "hover_fg": "#f0e8d8", "on_accent": "#1a1814",
    },
    "console": {
        "label":    "console",
        "bg":       "#0e1117", "bg_alt":   "#161b22",
        "fg":       "#c9d1d9", "fg_dim":   "#8b949e",
        "accent":   "#58a6ff", "border":   "#30363d",
        "success":  "#3fb950", "warning":  "#d29922", "danger":   "#f85149",
        "hover_bg": "#252c36", "hover_fg": "#c9d1d9", "on_accent": "#0e1117",
    },
    "compact": {
        "label":    "compact",
        "bg":       "#1a1a1a", "bg_alt":   "#252525",
        "fg":       "#e8e8e8", "fg_dim":   "#999999",
        "accent":   "#ff8c42", "border":   "#3a3a3a",
        "success":  "#7fbf7f", "warning":  "#e6c060", "danger":   "#e06c5a",
        "hover_bg": "#2e2e2e", "hover_fg": "#e8e8e8", "on_accent": "#1a1a1a",
    },
    "casebook": {
        "label":    "casebook",
        "bg":       "#f5efe0", "bg_alt":   "#ebe2c8",
        "fg":       "#3a3424", "fg_dim":   "#6e6248",
        "accent":   "#8b5e34", "border":   "#c9b985",
        "success":  "#5a7a4a", "warning":  "#b88a2c", "danger":   "#a64b2a",
        "hover_bg": "#e0d5b0", "hover_fg": "#3a3424", "on_accent": "#f5efe0",
    },
    "agent-paper": {
        "label":    "agent-paper",
        "bg":       "#ffffff", "bg_alt":   "#f8fafc",
        "fg":       "#0a1929", "fg_dim":   "#1f3045",
        "accent":   "#0e7c86", "border":   "#cdd8e0",
        "success":  "#5b8a51", "warning":  "#b88a2c", "danger":   "#b85a2c",
        "hover_bg": "#e8eef2", "hover_fg": "#0a1929", "on_accent": "#ffffff",
    },
    "agent-pulse": {
        "label":    "agent-pulse",
        "bg":       "#0a0d12", "bg_alt":   "#11161e",
        "fg":       "#d6dde8", "fg_dim":   "#6b7888",
        "accent":   "#ffb000", "border":   "#1d2530",
        "success":  "#4ec5b9", "warning":  "#ffd166", "danger":   "#ff5a52",
        "hover_bg": "#1d2530", "hover_fg": "#d6dde8", "on_accent": "#0a0d12",
    },
    "agent-history": {
        "label":    "agent-history",
        "bg":       "#fafaf7", "bg_alt":   "#f5efe3",
        "fg":       "#0a1929", "fg_dim":   "#1f3045",
        "accent":   "#0e7c86", "border":   "#ddd0a8",
        "success":  "#5b8a51", "warning":  "#b88a2c", "danger":   "#b85a2c",
        "hover_bg": "#ebe3d1", "hover_fg": "#0a1929", "on_accent": "#fafaf7",
    },
    "terminal": {
        "label":    "terminal",
        "bg":       "#000000", "bg_alt":   "#0a0a0a",
        "fg":       "#00ff66", "fg_dim":   "#00cc52",
        "accent":   "#00ff66", "border":   "#1e3a1e",
        "success":  "#00ff66", "warning":  "#ffcc00", "danger":   "#ff3300",
        "hover_bg": "#1e1e1e", "hover_fg": "#00ff66", "on_accent": "#000000",
    },
    "swiss": {
        "label":    "swiss",
        "bg":       "#fafafa", "bg_alt":   "#ffffff",
        "fg":       "#0a0a0a", "fg_dim":   "#404040",
        "accent":   "#d62828", "border":   "#d4d4d4",
        "success":  "#2a7a2a", "warning":  "#c47a00", "danger":   "#d62828",
        "hover_bg": "#f0f0f0", "hover_fg": "#0a0a0a", "on_accent": "#fafafa",
    },
}

# Track the original order from themes.css (the framework's intended
# dropdown ordering). If themes.css can't be loaded we fall back to
# alphabetic so the picker still works.
THEMES_ORDER: Tuple[str, ...] = tuple(DEFAULT_THEMES.keys())


# ── Live theme reloading from themes.css ────────────────────────────────────

_VAR_RE = re.compile(r"--el-([a-z0-9-]+)\s*:\s*([^;]+);")
_BLOCK_RE = re.compile(
    r'\[data-theme="(?P<slug>[a-z0-9-]+)"\]\s*\{(?P<body>[^}]*)\}',
    re.DOTALL,
)


def _reload_from_css() -> Dict[str, Dict[str, str]]:
    """Re-parse themes.css and merge into DEFAULT_THEMES.

    Returns a NEW dict (does not mutate DEFAULT_THEMES) so callers can
    decide whether to use it. The token → palette field mapping:
        bg        → --el-bg
        bg_alt    → --el-panel
        fg        → --el-ink
        fg_dim    → --el-ink-soft
        accent    → --el-accent
        border    → --el-line
        success   → --el-ok
        warning   → --el-warn
        danger    → --el-fail
        hover_bg  → --el-panel-2
        hover_fg  → --el-ink
        on_accent → --el-on-accent
    """
    src = _find_themes_css()
    if src is None:
        return dict(DEFAULT_THEMES)
    out: Dict[str, Dict[str, str]] = {}
    try:
        text = src.read_text(encoding="utf-8")
    except Exception:
        return dict(DEFAULT_THEMES)
    # Track the order the framework uses (matches the picker UX).
    order: List[str] = []
    for m in _BLOCK_RE.finditer(text):
        slug = m.group("slug")
        body = m.group("body")
        tokens = {k: v.strip() for k, v in _VAR_RE.findall(body)}
        if not tokens:
            continue
        order.append(slug)
        out[slug] = {
            "label":     slug,
            "bg":        tokens.get("bg",        DEFAULT_THEMES.get(slug, {}).get("bg", "#0a1218")),
            "bg_alt":    tokens.get("panel",     tokens.get("bg", "#0a1218")),
            "fg":        tokens.get("ink",       "#dde6f0"),
            "fg_dim":    tokens.get("ink-soft",  "#6b8497"),
            "accent":    tokens.get("accent",    "#ffb000"),
            "border":    tokens.get("line",      "#1c2a36"),
            "success":   tokens.get("ok",        "#5fe09a"),
            "warning":   tokens.get("warn",      "#ffd166"),
            "danger":    tokens.get("fail",      "#ff5a52"),
            "hover_bg":  tokens.get("panel-2",   tokens.get("panel", "#14242e")),
            "hover_fg":  tokens.get("ink",       "#dde6f0"),
            "on_accent": tokens.get("on-accent", "#0a1218"),
        }
    # Preserve only the discovered themes — the static defaults act as
    # a fallback if the framework CSS disappears at runtime.
    if order:
        globals()["THEMES_ORDER"] = tuple(order)
    return out or dict(DEFAULT_THEMES)


def get_themes() -> Dict[str, Dict[str, str]]:
    """Return the live theme catalog, reloading from themes.css.

    The picker dropdown reads from this so theme additions in
    themes.css propagate without a Python edit. Returns the static
    DEFAULT_THEMES if the CSS is unreachable.
    """
    return _reload_from_css()


THEMES = get_themes()


# ── Resolutions ────────────────────────────────────────────────────────────

RESOLUTIONS: Tuple[Tuple[int, int], ...] = (
    (1500, 300),
    (1500, 600),
    (1000, 400),
    (800,  300),
)


# ── Persistence ────────────────────────────────────────────────────────────

POPUP_SETTINGS = Path.home() / ".cortexagent" / "popup_settings.json"

DEFAULT_SETTINGS = {
    "resolution":  [1500, 600],
    "theme":       "cockpit",
    "tui_pct":     70,
    "sidebar_pct": 27,
    "right_pct":   3,
}


def load_settings() -> Dict:
    """Read ~/.cortexagent/popup_settings.json with defaults applied."""
    import json
    out = dict(DEFAULT_SETTINGS)
    try:
        if POPUP_SETTINGS.exists():
            raw = json.loads(POPUP_SETTINGS.read_text())
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in out and v is not None:
                        out[k] = v
    except Exception:
        pass
    return out


def save_settings(settings: Dict) -> None:
    """Persist the picked settings for the next launch + STT panel."""
    import json
    try:
        POPUP_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = POPUP_SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2))
        tmp.replace(POPUP_SETTINGS)
    except Exception:
        pass


def get_palette(name: str) -> Dict[str, str]:
    """Resolve a palette by name; falls back to cockpit on miss."""
    themes = get_themes()
    return themes.get(name, themes.get("cockpit", DEFAULT_THEMES["cockpit"]))