"""
el-framework — Python/Tkinter bridge
====================================

Reads the CSS token files (`tokens.css` + `themes.css`) and converts them
into tkinter-friendly configuration. Use as a theme source for any tkinter
project — the same themes you see in the HTML demos work in desktop apps.

Usage
-----

    from el_framework import ElTheme, apply_theme, ElWidget

    # Option A: full theme object
    theme = ElTheme("cockpit")
    root.configure(bg=theme.bg)
    btn = tk.Button(root, text="Run", **theme.btn_kwargs())
    btn.pack()

    # Option B: apply to entire root window
    apply_theme(root, "cockpit")

    # Option C: theme-aware widget helpers
    pill = ElWidget(root, "pill", text="OK", variant="ok")
    pill.pack()

Requires
--------
- tkinter (stdlib)
- re (stdlib)

No external deps. Drop into any Python project.

Adding new themes
-----------------
Themes are read from `themes.css`. Add a new `[data-theme="<slug>"]` block
and it will appear automatically.

License: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ── Token parsing ───────────────────────────────────────────────────────

_VAR_RE = re.compile(r"--([a-z0-9\-]+)\s*:\s*([^;]+?)\s*;")


def _parse_vars(css_text: str) -> Dict[str, str]:
    """Extract all `--name: value;` declarations from CSS text."""
    return {m.group(1): m.group(2).strip() for m in _VAR_RE.finditer(css_text)}


def _resolve(value: str, all_vars: Dict[str, str]) -> str:
    """Resolve `var(--foo)` references inside a token value."""
    seen = set()

    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name in seen:
            return match.group(0)
        seen.add(name)
        return all_vars.get(name, match.group(0))

    out = value
    for _ in range(8):  # bounded — avoid infinite recursion
        new = re.sub(r"var\(\s*--([a-z0-9\-]+)\s*(?:,[^)]*)?\)", sub, out)
        if new == out:
            break
        out = new
    return out


def _hex_to_rgb(value: str) -> Optional[tuple]:
    """Convert #rrggbb or #rgb to (r, g, b). Returns None if not a color."""
    m = re.match(r"#([0-9a-fA-F]{6})$", value)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"#([0-9a-fA-F]{3})$", value)
    if m:
        h = m.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    return None


# ── Theme model ─────────────────────────────────────────────────────────

@dataclass
class ElTheme:
    """Parsed CSS theme. All tokens resolved to concrete values."""

    slug: str
    tokens: Dict[str, str] = field(default_factory=dict)

    @property
    def bg(self) -> str:
        return self.tokens.get("bg", "#000000")

    @property
    def panel(self) -> str:
        return self.tokens.get("panel", self.bg)

    @property
    def panel_2(self) -> str:
        return self.tokens.get("panel-2", self.panel)

    @property
    def ink(self) -> str:
        return self.tokens.get("ink", "#ffffff")

    @property
    def ink_soft(self) -> str:
        return self.tokens.get("ink-soft", self.ink)

    @property
    def accent(self) -> str:
        return self.tokens.get("accent", "#ffb000")

    @property
    def on_accent(self) -> str:
        return self.tokens.get("on-accent", "#000000")

    @property
    def ok(self) -> str:
        return self.tokens.get("ok", "#5fe09a")

    @property
    def warn(self) -> str:
        return self.tokens.get("warn", "#ffd166")

    @property
    def fail(self) -> str:
        return self.tokens.get("fail", "#ff5a52")

    @property
    def live(self) -> str:
        return self.tokens.get("live", "#00e0d4")

    @property
    def info(self) -> str:
        return self.tokens.get("info", "#58a6ff")

    @property
    def line(self) -> str:
        return self.tokens.get("line", self.panel_2)

    @property
    def mute(self) -> str:
        return self.tokens.get("mute", self.ink_soft)

    @property
    def font_body(self) -> str:
        return self.tokens.get("font-body", "TkDefaultFont")

    @property
    def font_mono(self) -> str:
        return self.tokens.get("font-mono", "TkFixedFont")

    # ── tkinter-friendly kwargs ──

    def btn_kwargs(self, variant: str = "") -> Dict[str, Any]:
        """Return kwargs for `tk.Button(**kwargs)`."""
        return {
            "bg": self.accent,
            "fg": self.on_accent,
            "activebackground": self.tokens.get("accent-hover", self.accent),
            "activeforeground": self.on_accent,
            "relief": "flat",
            "borderwidth": 0,
            "padx": 12,
            "pady": 6,
            "font": (self._first_font_family(), 10, "bold"),
            "cursor": "hand2",
        }

    def label_kwargs(self, soft: bool = False) -> Dict[str, Any]:
        return {
            "bg": self.bg,
            "fg": self.ink_soft if soft else self.ink,
            "font": (self._first_font_family(), 10),
        }

    def frame_kwargs(self, level: int = 0) -> Dict[str, Any]:
        levels = [self.bg, self.panel, self.panel_2, self.tokens.get("panel-3", self.panel_2)]
        return {
            "bg": levels[min(level, len(levels) - 1)],
        }

    def pill_kwargs(self, variant: str = "ok") -> Dict[str, Any]:
        color = {
            "ok": self.ok,
            "warn": self.warn,
            "fail": self.fail,
            "info": self.tokens.get("info", self.accent),
            "live": self.tokens.get("live", self.fail),
        }.get(variant, self.ink)
        return {
            "bg": self.panel_2,
            "fg": color,
            "font": (self._first_font_family(), 9, "bold"),
            "padx": 8,
            "pady": 2,
        }

    def _first_font_family(self) -> str:
        """Strip quoted font names; return the first usable family."""
        s = self.font_body
        m = re.match(r"'([^']+)'", s)
        return m.group(1) if m else "TkDefaultFont"


# ── Loader ──────────────────────────────────────────────────────────────

class ElThemeNotFound(KeyError):
    pass


_THEMES_CACHE: Optional[Dict[str, ElTheme]] = None


def _load_themes(
    tokens_path: Optional[Union[str, Path]] = None,
    themes_path: Optional[Union[str, Path]] = None,
) -> Dict[str, ElTheme]:
    """Parse tokens.css + themes.css and return a dict of slug → ElTheme."""
    global _THEMES_CACHE
    if _THEMES_CACHE is not None:
        return _THEMES_CACHE

    here = Path(__file__).resolve().parent.parent
    tokens_path = Path(tokens_path) if tokens_path else here / "tokens.css"
    themes_path = Path(themes_path) if themes_path else here / "themes.css"

    base = _parse_vars(tokens_path.read_text()) if tokens_path.exists() else {}
    # Strip the leading "el-" prefix from token names so properties look up cleanly
    base_norm = {k.removeprefix("el-"): v for k, v in base.items()}
    themes: Dict[str, ElTheme] = {"neutral": ElTheme("neutral", dict(base_norm))}

    if themes_path.exists():
        css = themes_path.read_text()
        # Split by [data-theme="..."] blocks
        for m in re.finditer(
            r'\[data-theme="([^"]+)"\]\s*\{([^}]+)\}', css, re.DOTALL
        ):
            slug = m.group(1)
            block = m.group(2)
            overrides = _parse_vars(block)
            overrides = {k.removeprefix("el-"): v for k, v in overrides.items()}
            merged = {**base_norm, **overrides}
            resolved = {k: _resolve(v, merged) for k, v in merged.items()}
            themes[slug] = ElTheme(slug, resolved)

    _THEMES_CACHE = themes
    return themes


def available_themes() -> List[str]:
    """List all theme slugs."""
    return list(_load_themes().keys())


def get_theme(slug: str = "neutral") -> ElTheme:
    """Return the named theme. Raises ElThemeNotFound if missing."""
    themes = _load_themes()
    if slug not in themes:
        raise ElThemeNotFound(
            f"theme '{slug}' not found; available: {', '.join(themes)}"
        )
    return themes[slug]


# ── Application helpers ─────────────────────────────────────────────────


def apply_theme(widget: Any, slug: str = "neutral") -> ElTheme:
    """Apply a theme to a tk widget (typically `root`).

    Sets background + foreground + fonts on the widget. For full theming
    you'll want to pass `theme.btn_kwargs()` etc. into your widget constructors.
    """
    theme = get_theme(slug)
    try:
        widget.configure(bg=theme.bg)
    except Exception:
        pass
    return theme


# ── Element widgets (Tkinter helpers) ───────────────────────────────────


class ElWidget:
    """Tkinter widget factory matching the HTML el-* primitives.

    Usage:
        ElWidget(parent, "btn", text="Run")
        ElWidget(parent, "pill", text="OK", variant="ok")
        ElWidget(parent, "gauge", text="auditd", variant="fail")
    """

    def __init__(self, parent: Any, kind: str, theme: Optional[ElTheme] = None, **kwargs):
        import tkinter as tk
        from tkinter import ttk

        self.theme = theme or get_theme()
        self.kind = kind

        if kind == "btn":
            self._w = tk.Button(parent, text=kwargs.get("text", ""),
                                command=kwargs.get("command"),
                                **self.theme.btn_kwargs())
        elif kind == "pill":
            self._w = tk.Label(parent, text=kwargs.get("text", ""),
                               **self.theme.pill_kwargs(kwargs.get("variant", "ok")))
        elif kind == "label":
            self._w = tk.Label(parent, text=kwargs.get("text", ""),
                               **self.theme.label_kwargs(kwargs.get("soft", False)))
        elif kind == "frame":
            self._w = tk.Frame(parent, **self.theme.frame_kwargs(kwargs.get("level", 0)))
        elif kind == "gauge":
            text = kwargs.get("text", "")
            variant = kwargs.get("variant", "ok")
            fg = {"ok": self.theme.ok, "warn": self.theme.warn, "fail": self.theme.fail}.get(variant, self.theme.ink)
            inner = tk.Frame(self._make_gauge_outer(parent), bg=self.theme.panel_2, width=60, height=80,
                             highlightthickness=1, highlightbackground=fg)
            tk.Label(inner, text=text, bg=self.theme.panel_2, fg=fg, font=(self.theme._first_font_family(), 9, "bold")).pack(pady=(8, 0))
            tk.Label(inner, text=kwargs.get("val", ""), bg=self.theme.panel_2, fg=fg, font=(self.theme._first_font_family(), 14, "bold")).pack(pady=(4, 8))
            self._w = inner
        else:
            # Fallback to a plain label
            self._w = tk.Label(parent, text=kwargs.get("text", kind),
                               **self.theme.label_kwargs())

    def _make_gauge_outer(self, parent: Any):
        import tkinter as tk
        return tk.Frame(parent, bg=self.theme.bg)

    def pack(self, **kw):
        self._w.pack(**kw)
        return self

    def grid(self, **kw):
        self._w.grid(**kw)
        return self

    @property
    def widget(self):
        return self._w


# ── Self-test ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    # Print all available themes + their key tokens
    print(f"Found {len(available_themes())} themes:\n")
    for slug in available_themes():
        t = get_theme(slug)
        print(f"  [{slug}]")
        print(f"    bg      = {t.bg}")
        print(f"    panel   = {t.panel}")
        print(f"    ink     = {t.ink}")
        print(f"    accent  = {t.accent}")
        print(f"    ok/warn/fail = {t.ok} / {t.warn} / {t.fail}")
        print(f"    font    = {t.font_body}")
        print()
