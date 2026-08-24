
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple








_THEMES_CSS_REL = Path("lib/themes/themes.css")
_FALLBACK_CSS_REL = Path("ui-framework/themes")
_HOME_FALLBACK = Path.home() / "ui-framework" / "themes"


def _find_themes_css() -> Path | None:

    candidates = []

    here = Path(__file__).resolve().parent.parent
    candidates.append(here / _THEMES_CSS_REL)


    candidates.append(_HOME_FALLBACK / "themes.css")
    for p in candidates:
        if p.exists():
            return p
    return None
















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




THEMES_ORDER: Tuple[str, ...] = tuple(DEFAULT_THEMES.keys())




_VAR_RE = re.compile(r"--el-([a-z0-9-]+)\s*:\s*([^;]+);")
_BLOCK_RE = re.compile(
    r'\[data-theme="(?P<slug>[a-z0-9-]+)"\]\s*\{(?P<body>[^}]*)\}',
    re.DOTALL,
)


def _reload_from_css() -> Dict[str, Dict[str, str]]:

    src = _find_themes_css()
    if src is None:
        return dict(DEFAULT_THEMES)
    out: Dict[str, Dict[str, str]] = {}
    try:
        text = src.read_text(encoding="utf-8")
    except Exception:
        return dict(DEFAULT_THEMES)

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


    if order:
        globals()["THEMES_ORDER"] = tuple(order)
    return out or dict(DEFAULT_THEMES)


def get_themes() -> Dict[str, Dict[str, str]]:

    return _reload_from_css()


THEMES = get_themes()




RESOLUTIONS: Tuple[Tuple[int, int], ...] = (
    (1500, 300),
    (1500, 600),
    (1000, 400),
    (800,  300),
)




POPUP_SETTINGS = Path.home() / ".cortexagent" / "popup_settings.json"

DEFAULT_SETTINGS = {
    "resolution":  [1500, 600],
    "theme":       "cockpit",
    "tui_pct":     70,
    "sidebar_pct": 27,
    "right_pct":   3,
}


def load_settings() -> Dict:

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

    import json
    try:
        POPUP_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = POPUP_SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2))
        tmp.replace(POPUP_SETTINGS)
    except Exception:
        pass


def get_palette(name: str) -> Dict[str, str]:

    themes = get_themes()
    return themes.get(name, themes.get("cockpit", DEFAULT_THEMES["cockpit"]))