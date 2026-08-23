# Popup Redesign — 2026-08-20

## Context

`lib/browser_console.py` is the GTK3 popup that hosts the embedded VTE
terminal (PTY of `bin/cortexagent`), the BROWSER / TASKS / PAGE sidebar,
and the right-side ESC. + ↵ button cluster. The popup has been
iteratively patched through ~15 sessions of user feedback; the current
state has three concrete problems and one latent one:

1. **Top bar is too thick.** The `Gtk.HeaderBar` carries the only
   close X and is ~36 px tall with a dark, rounded background. The user
   wants it replaced with a thin (~24 px) draggable strip like the STT
   panel, with both minimize (_) and close (X) inline.
2. **The PAGE panel is useless.** It just shows the focused CDP tab's
   title + URL — duplicate of what's already in BROWSER. The user
   wants it replaced with a **Settings** panel for resolution, theme,
   and TUI layout.
3. **TUI width / layout knobs are not exposed.** The user wants the
   TUI to be the dominant surface (70% width), sidebar 27%, right
   strip 3%. Currently these widths are hard-coded constants.
4. **BROWSER tab clicks still don't open the tab reliably.** The
   prior `_focus_tab` rewrite tried multiple `xdotool search` patterns,
   but the user reports it still fails. Need a debug print to find
   which path succeeds/fails before more guessing.
5. **The popup + STT panel share no theme system.** The user wants
   both to switch themes from Settings.

## Goals (one-line each)

- Replace thick HeaderBar with thin, draggable strip.
- Replace PAGE panel with Settings (resolution + theme + TUI width).
- Wire Settings' Apply button to live-resize the popup and re-style
  both popup + STT.
- Make BROWSER list show the active task above the tab rows.
- Add debug print to `_focus_tab` so we can find why clicks fail.
- Expose TUI widths (70/27/3) and feed them to the left-strip component.

## Non-Goals

- No new daemon / IPC surface.
- No rewrite of the VTE wiring.
- No replacing the popup with Tauri.
- No adding a third tray icon.

## Decisions (locked with user)

| Q | Decision |
|---|----------|
| Resolution presets | `1500×300`, `1500×600`, `1000×400`, `800×300` |
| Theme source | Both: theme picker (amber / slate / nord / rose / mono) AND layout dials |
| Apply | Apply button commits all changes at once |
| Active task in BROWSER | One-line header above the tab rows; falls back to "✓ idle" |
| Tab-click debugging | Add a `print(...)` log inside `_focus_tab` showing candidates / WIDs / activate rc |

## Design

### 1. Thin draggable top bar

Replace `Gtk.HeaderBar()` with a 24-px Gtk.Box that holds:

```
┌─────────────────────────────────────────┐
│ ⠿  CortexAgent Console          _  ✕   │  ← 24 px, click-drag moves
├─────────────────────────────────────────┤
```

- Left glyph (⠿) is the drag handle.
- Window drag: `Gtk.Window.begin_move_drag(button, root_x, root_y, timestamp)` on button-press-event for the strip's EventBox (button=1).
- Minimize `_`: `Gtk.Window.iconify()`.
- Close `✕`: keep the existing belt-and-suspenders close (record_close → main_quit → destroy).
- Set `win.set_titlebar(None)` so the WM doesn't draw its own chrome.

### 2. Settings panel (replaces PAGE)

Layout (vertical list, sidebar width 280):

```
SETTINGS
  ┌────────────────────────────────────┐
  │ Resolution  [▼ 1500x600        ]   │
  │ Theme       [▼ amber           ]   │
  │ TUI width   ─ 70% ─               │
  │ Sidebar     ─ 27% ─               │
  │ Right       ─  3% ─               │
  │                                    │
  │ [            Apply             ]   │
  └────────────────────────────────────┘
```

- Resolution dropdown: 4 fixed entries.
- Theme dropdown: 5 fixed entries (amber = current, slate, nord, rose, mono).
- Three sliders (Gtk.Scale) — sum is informational, not enforced.
- Apply button: calls `_apply_settings()` which:
  1. Resizes window via `win.resize(w, h)`.
  2. Reloads the CSS provider with the chosen theme's palette.
  3. Writes `~/.cortexagent/popup_settings.json` for persistence.
  4. Sends the new widths to the STT panel via the existing TUI
     settings file (the left-strip component already reads from
     `~/.cortexagent/popup_settings.json` in the same shape — see
     `interactive-mode.ts` left-strip wiring).

### 3. Live metrics in Settings (compact row)

Above the resolution picker, one row of live numbers (re-read every
`REFRESH_SECS=3`):

```
● big :8080   ● proxy :8081   ● ovsr :8082
compress 58% (12 runs)   mem 14 hot / 88 cold
```

Reads the same sources as the TUI's API Health section — no new
modules.

### 4. BROWSER section gets an active-task header

```
BROWSER
  ▶ build cortex-hud
  ───────────────────────────────
  • Some Tab Title
    https://example…
  • Another Tab
    https://other…
```

- Active task row reads from the same `tasks.events.jsonl` source
  the TUI's left strip uses (function duplicated here as
  `_read_active_task_for_popup()` — small, no shared module).
- Falls back to `✓ idle` when no events.
- Refreshed on the same `REFRESH_SECS=3` tick.

### 5. `_focus_tab` debug logging

Wrap each candidate search with a `print()`:

```python
print(f"[focus_tab] title='{decoded[:30]}…' candidates={candidates}", file=sys.stderr)
for cand in candidates:
    r = subprocess.run(["xdotool", "search", "--name", cand], ...)
    wids = ...
    print(f"[focus_tab]   search {cand!r} → {wids}", file=sys.stderr)
    if wids: ...
print(f"[focus_tab]   → activate {best} rc={rc}", file=sys.stderr)
```

Run the popup once, click a tab, copy the stderr output. Diagnose
based on which path returned empty.

### 6. TUI layout dials

Add 3 constants in `cortex/packages/coding-agent/src/modes/interactive/
components/left-strip.ts`:

```ts
export const STRIP_PCT_LEFT = 27;   // user-configurable later
export const STRIP_PCT_RIGHT = 3;   // (right strip = collapsed/empty)
```

The interactive-mode.ts layout reads these from
`~/.cortexagent/popup_settings.json` if present, otherwise falls back
to current values (left strip expanded at 18 cols / no right strip).

### 7. Theme system

Add `lib/popup_themes.py` — pure data:

```python
THEMES = {
    "amber": {"bg": "#0d0a07", "fg": "#e8e0d0", "accent": "#d4a050", ...},
    "slate": {"bg": "#1e222a", "fg": "#c5c8c6", "accent": "#80cbc4", ...},
    "nord":  {"bg": "#2e3440", "fg": "#eceff4", "accent": "#88c0d0", ...},
    "rose":  {"bg": "#1a1419", "fg": "#f5e1e8", "accent": "#e07c9c", ...},
    "mono":  {"bg": "#000000", "fg": "#e0e0e0", "accent": "#a0a0a0", ...},
}
```

CSS provider re-builds the existing `css` string from the picked
palette when Apply is pressed.

### 8. STT panel sync

`lib/tkinter_strip/strip.py` reads from the same
`~/.cortexagent/popup_settings.json` and applies the theme's `bg`
and `accent` to its `bg=` constructor args. The strip already
re-reads config on a heartbeat — no new IPC needed.

## Files Touched

- `lib/browser_console.py` — top bar, Settings panel, BROWSER header,
  `_focus_tab` logging, theme CSS rebuild.
- `lib/popup_themes.py` *(new)* — palette dict.
- `lib/tkinter_strip/strip.py` — theme read on init/refresh.
- `cortex/packages/coding-agent/src/modes/interactive/
  components/left-strip.ts` — read widths from settings JSON.
- `cortex/packages/coding-agent/src/modes/interactive/
  interactive-mode.ts` — wire settings file path.

## Verification

1. `python3 -m lib.browser_console` — popup launches, new thin strip
   visible, drag works, both buttons functional.
2. Pick `1000x400` from Settings, click Apply — window resizes
   immediately.
3. Pick `nord` theme, Apply — colors swap in popup AND STT panel.
4. Start a scheduled task, watch the BROWSER header show "▶
   <title>".
5. Click a CDP tab row, check stderr for `[focus_tab]` lines.
6. Run `bin/verify` (if it covers these files) — feature catalog
   delta for the new Settings panel.

## Out of Scope (deferred)

- Per-tab favicons in BROWSER list.
- Drag-to-reorder of BROWSER rows.
- Persistent multi-monitor positioning.
- New tray submenu for theme switching (Settings only).
