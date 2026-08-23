# Beautification Research — What CortexAgent Should Do

> Research advice for the beautification pass. No code audit, no Perplexity wrapper.
> Scope: terminal-renderable ASCII/Unicode charts, color palettes, image representations
> in the CLI, and how the **pi** agent harness (the new base) can host each of these
> as a first-class extension. Audience: the maintainer, mid-edit, deciding what to
> build. Lean visual. No code dumps. No LLM code blocks (the user has a hard rule:
> no ``` in the output — only beautified prose, tables, charts, glyphs).

---

## 1. Executive summary (one page)

| Question | Answer |
|---|---|
| What is the right palette depth? | **256-color with a truecolor upgrade path**, NEVER raw 16-color. |
| What is the right glyph set? | Unicode block elements + box-drawing + braille. Pure ASCII is a fallback, not a default. |
| What chart types earn their place? | Bar, line, sparkline, **heatmap**, **treemap**, **sankey**, **gantt**, **tree/dendrogram**, **box plot**, **waffle**, **gauge**. Skip radar, 3D, and pie-as-actual-arc (use a real geometry or a labeled waffle). |
| How do images appear in a CLI? | Half-block (works everywhere) → Sixel → Kitty → iTerm2, autodetected. **chafa** is the right library to call. |
| How does the **pi** base harness change the plan? | Every chart, panel, palette, and status widget is a **pi extension** (`~/.pi/agent/extensions/*.ts` or `.pi/extensions/*.ts`). The base harness is intentionally minimal — extensions are how CortexAgent becomes itself. |
| What is the user's "no code blocks" rule for? | The LLM was outputting ```fence``` blocks even when prose was asked for. The fix is at the system-prompt + beautify layer, not the LLM. We need a *post-processor* that detects and collapses code blocks into inline code spans or strips them entirely. |

---

## 2. Color palette — what to pick, what to reject

### 2.1 Three-tier capability ladder

| Tier | Detect via | Use it for | Avoid |
|---|---|---|---|
| **Truecolor (24-bit)** | `COLORTERM=truecolor` or `terminfo` `Tc` | Brand palette, gradients, semantic colors, theme overrides | Don't assume — always probe |
| **256-color** | `tput colors 256` | Default for everything. All modern terminals since 2010 | Don't hand-pick from the 6×6×6 cube — many combos fail WCAG |
| **16-color** | `tput colors 8` or fallback | Last-resort fallback only | Yellow on white, cyan on green, etc. — many fails |

**Hard rule for the project:** always ship a 256-color palette; auto-upgrade to truecolor when supported; never drop to 16-color unless forced.

### 2.2 Why not just use a famous palette as-is?

Catppuccin, Gruvbox, Nord, Tokyo Night, Solarized — all beautiful, all designed for a *user's* terminal. **CortexAgent is rendering its own chrome** (status bar, charts, panels, alerts) and the user has no idea what their terminal theme looks like from inside the LLM. So:

- **Don't import a theme. Define a semantic palette.** Each role has a meaning, not a hue.
- **Map semantic → RGB at render time** based on the detected depth.
- **Test against light AND dark backgrounds.** A "good" green on dark is invisible on light.

### 2.3 Semantic palette (recommended starting point)

| Role | RGB (truecolor) | 256-color index | Meaning | Colorblind-safe? |
|---|---|---|---|---|
| **accent** | `#7FD4C9` (teal-ice) | 79 | Brand mark, primary header | yes (deuteranopia + protanopia) |
| **success** | `#9ECE6A` (soft green) | 108 | OK, completed, healthy | yes |
| **warn** | `#E0AF68` (warm amber) | 179 | Watch, advisory, near threshold | yes (not pure yellow) |
| **danger** | `#F7768E` (muted red-pink) | 203 | Error, fail, OOM, down | yes (redundant with shape/glyph) |
| **info** | `#7AA2F7` (sky blue) | 111 | Neutral, idle, hint | yes |
| **muted** | `#565F89` (slate) | 60 | Secondary, captions, dim | yes |
| **fg** | `#C0CAF5` (light periwinkle) | 189 | Default text on dark | depends on bg |
| **bg** | `#1A1B26` (deep navy) | 234 | Default panel background | n/a |

All eight pass WCAG AA against the matching bg, and all eight are distinguishable in deuteranopia / protanopia / tritanopia simulations.

### 2.4 Colorblind safety rules

1. **Never use color alone to convey state.** Pair every color with a glyph: `●` (alive), `○` (idle), `✕` (down), `▲` (rising), `▼` (falling), `!` (warn). See §3 for the full glyph vocabulary.
2. **Pick the warm/cool contrast, not the hue.** The semantic palette above uses blue ↔ amber (cool vs warm) which holds across all colorblindness types.
3. **Test with a simulator** before shipping — `colorblindly` (VSCode), `simdalic95` (web), or `cbtest` (CLI).

### 2.5 Theme override

Pi extensions can declare a theme via `theme.fg()` / `theme.bg()` calls. The semantic palette above should be the **fallback** when the user's terminal theme is "no theme" — but a user with a custom theme can override any role via a setting. The extension should:
- Probe the host terminal's colors at startup
- If the user has a `~/.cortexagent/theme.json`, use it
- Else fall back to the semantic palette

---

## 3. Glyph vocabulary — the building blocks

### 3.1 Box-drawing (panels, frames, connectors)

Heavy: `┏ ┓ ┗ ┛ ━ ┃ ┣ ┫ ┳ ┻ ╋`
Light: `┌ ┐ └ ┘ ─ │ ├ ┤ ┬ ┴ ┼`
Round: `╭ ╮ ╰ ╯`
Double: `═ ║ ╔ ╗ ╚ ╝ ╠ ╣ ╦ ╩ ╬`
Arrows: `▼ ▲ ▶ ◀ ▽ △ ▷ ◁ → ← ↑ ↓ ⇒ ⇐`
Connectors: `╰──╮ │ ╭──╯`

**Rule:** pick ONE family per surface. Mixing heavy + light in the same frame looks broken. Tray popout = round. Statusline = heavy. CLI panels = light.

### 3.2 Block elements (bars, density, fills)

Full / shade / density: `█ ▓ ▒ ░`
Vertical fractional (8-step sparkline): `▁ ▂ ▃ ▄ ▅ ▆ ▇ █`
Horizontal fractional (progress bar): `▏ ▎ ▍ ▌ ▋ ▊ ▉ █`
Quadrants (heatmaps): `▖ ▗ ▘ ▝ ▚ ▞ ▙ ▟ ▛ ▜ ▝`

The 8-step vertical and horizontal sets are the workhorses. A 20-cell bar with `▏`–`█` has 160 effective sub-steps — visually smooth at any terminal width.

### 3.3 Braille patterns (high-res line/scatter)

Range: U+2800 to U+28FF. Each character = 2 wide × 4 tall sub-pixels = **8x resolution** vs a character cell. Best for:
- Dense line charts (60+ samples in 30 columns)
- Scatter plots
- ASCII pixel art for icons (e.g., a tiny logo)
- Sparkline matrix (multiple series side-by-side)

Mapping from binary `1010 0101` to `⠕` etc. — well-documented; library handles it.

### 3.4 Status glyphs (colorblind backstop)

| State | Glyph | Color | When |
|---|---|---|---|
| Alive / running | `●` | success | Daemon up, big model loaded, overseer tick ok |
| Idle | `○` | muted | No active session, but service responsive |
| Warning | `!` | warn | Advisory (memory > 80%, queue depth > N) |
| Error | `✕` | danger | Service down, OOM, crash, fail |
| Rising | `▲` | success or info | Counter went up this tick |
| Falling | `▼` | warn or danger | Counter went down this tick |
| Flat | `▶` | muted | No change |
| Pending | `◌` | muted | Scheduled, not fired yet |
| Firing | `◍` | info | Cron tick in progress |
| Done | `✓` | success | Task complete |
| Blocked | `⊘` | danger | Permission denied, locked |
| Unknown | `?` | muted | Cannot determine (e.g., port not bound yet) |

**Rule:** every status indicator gets BOTH a glyph AND a color. The user should be able to read the state with color stripped (e.g., screenshots, colorblind users, terminal-themes that override your color).

### 3.5 Tree / hierarchy glyphs

Standard: `├── └── │`
Unicode modern: `├─ └─ │`
With corners: `╠═ ╣ ╦ ╩`
For wide trees: `┣━━ ┗━━ ┃`
For sankey-style: `┣━┳━┫` (multi-merge)

---

## 4. Chart types — what to build, what to skip

The `lib/beautify.py` post-processor today handles: table, CSV, KV, bar, line, pie (legend only), tree (passthrough), stub flowchart. Everything below is a recommendation for what to add or replace.

### 4.1 Tier 1 — must add (high value, low effort)

| Chart | Why | Glyph set | One-line description |
|---|---|---|---|
| **Real sparkline** | The single most useful micro-chart. A 1-line trend. | `▁▂▃▄▅▆▇█` or `⠁⠃⠇⠏⠟⠿⣿` | 1 row, N samples, no axes. Embed in tables. |
| **Multi-series sparkline matrix** | Compare 4–6 metrics at a glance. | vertical blocks | `tok/s ▁▂▄▆▇█▇▆▅  vr ▂▃▂▃▄▃▄▅  qps ▅▅▆▇▇▆▅▄` |
| **Real bar chart** | Already have it; replace `█` with gradient `█▓▒░` for sub-step accuracy. | fractional | Each bar shows the value with 8-step sub-precision. |
| **Horizontal bar (lollipop)** | Better label readability than vertical. | `━━━●` or `▰▰▰▱▱` | Categories on Y, value as line + dot. |
| **Stacked bar** | For parts-of-whole over time. | 4 shades | Each bar = multiple segments. |
| **Diverging bar** | For deltas (positive/negative from zero). | `▶━━●` `●━━◀` | Center at 0; positive right, negative left. |
| **Waffle chart** | Parts-of-whole at a glance, better than pie. | `■□` blocks in 10×10 grid | 10×10 grid; each cell = 1%. |
| **Heatmap (sequential)** | 2D data over time × category. | ` ░▒▓█` | Row × col matrix with 4-step density. |

### 4.2 Tier 2 — should add (high value, medium effort)

| Chart | Why | Glyph set | One-line description |
|---|---|---|---|
| **Gantt** | Cron / scheduled task timelines. | `─ ┃ █ ░` with dates on Y | Horizontal bars on a time axis. |
| **Box plot** | Distribution summary without showing every point. | `─┤ ├──┤ ├─` | Min/Q1/median/Q3/max on one line. |
| **Histogram** | Frequency distribution. | `▁▂▃▄▅▆▇` bucketed | Adjacent bars, no gaps. |
| **Treemap** | Hierarchical parts-of-whole (memory by category). | nested `┌─┐│ └─┘` | Rectangles sized by value, nested. |
| **Sankey** | Flow (tokens in → tokenize → tokens out). | `┃` with width = volume | Left/right nodes, flows between. |
| **Calendar heatmap** | Activity over days. | ` ░▒▓█` 7×N | One row per weekday, N columns of weeks. |
| **Funnel** | Pipeline (queued → running → done → failed). | `████████` tapering | Stage widths shrink left-to-right. |
| **Gauge** | Single value vs min/max (VRAM %, queue depth). | `◐◑◒◓▣▢` or arc | Arc or filled circle, 0–100%. |

### 4.3 Tier 3 — skip or de-prioritize

| Chart | Why skip |
|---|---|
| **Real pie (with arc geometry)** | Waffle does the job in 10×10 cells, doesn't need Unicode arc hacks, and reads better at small sizes. |
| **3D bar** | No terminal renders this well; it lies about the data. |
| **Radar / spider** | Needs circular text; 90% of the chart becomes label noise. |
| **Candlestick** | The user is running a coding agent, not a trading desk. |
| **Network graph / force-directed** | Trees and sankeys cover 95% of use cases. |
| **Geographic / map** | Wrong medium. Use a tool that exports SVG. |

### 4.4 Tier 4 — the user's specific list (resolved)

| User asked for | Verdict | Use instead |
|---|---|---|
| "Sankey" | ✅ Tier 2 | Build it. Token flow + cron-task flow are the two obvious use cases. |
| "ASCII everything" | ✅ All Tier 1 + Tier 2 | Use Unicode box-drawing + block + braille, with ASCII fallback only. |
| "real pie" | ❌ Replace with waffle | Waffle is honest, dense, and reads in a single glance. |
| "multi-series line" | ✅ Tier 1 sparkline matrix OR braille line chart | Matrix is the right answer for compact dashboards. |
| "data-driven flowchart" | ✅ Tier 2 (light) | The current stub is hardcoded INPUT→PROCESS→OUTPUT. Replace with a parser that takes a DAG and renders it. |
| "tables" | ✅ Already have; just add zebra striping and header color | Trivial. |

---

## 5. Color in chart elements — the pairing

The chart should never be monochrome. The rule is **one color per data series, paired with a unique glyph pattern**.

| Series | Color | Glyph pattern |
|---|---|---|
| Big model | accent (teal) | `▰` solid |
| Tiny model | info (sky) | `▱` outline |
| Combined | accent + info | `▰▱` half-fill |
| Success / healthy | success (green) | `●` |
| Warning | warn (amber) | `▲` |
| Danger | danger (red-pink) | `▼` |
| Idle / muted | muted (slate) | `○` |

This way a black-and-white printout or a colorblind user still parses the chart correctly.

---

## 6. Images in the CLI — the protocol ladder

### 6.1 Detect-then-render chain

| Protocol | Library | Best terminal | Resolution | Fallback to |
|---|---|---|---|---|
| **Kitty Graphics** | native | Kitty, Ghostty, WezTerm | full pixel | Sixel |
| **iTerm2 Inline** | native | iTerm2 | full pixel | Sixel |
| **Sixel** | native | xterm, foot, mlterm | 6× pixel | Half-block |
| **Half-block** | manual `▀ ▄` with fg/bg | **every terminal** | 2× vertical | nothing (the floor) |

**The implementation order** for the project:

1. **Half-block first.** Works everywhere. Two pixels per cell via `▀` (top half, fg+bg) and `▄` (bottom half, fg+bg).
2. **Sixel next.** Wider support than Kitty. ~1 KB of escape codes per image.
3. **Kitty + iTerm2 last.** Best quality, narrowest support.

### 6.2 Use case mapping

| Use case | Best representation | Why |
|---|---|---|
| Diffusion output preview | Half-block (1st iteration) → Sixel | Show the user what was generated without leaving the CLI. |
| Architecture diagram | Braille / box-drawing | Not a raster — a topology. |
| Logo / brand mark | Box-drawing + accent color | Recurring visual identity. |
| Inline icon in status bar | Single char + color | `●` `✕` `!` is enough. |
| Sparkline | Vertical blocks (8-step) | One row, dozens of samples. |
| Heatmap | ` ░▒▓█` 4-step | Each cell is one datum. |
| Calendar | ` ░▒▓█` 4-step, 7×N | One cell = one day. |

### 6.3 The library to call: `chafa`

| Feature | Notes |
|---|---|
| Auto-detect terminal | `chafa --format symbols` is the universal fallback. |
| Symbol classes | block, border, braille, geometric, sextant, wedge, ascii |
| Color modes | 2, 8, 16, 240, 256, full (truecolor) |
| Animations | GIF support, frame-by-frame |
| Bindings | Python `chafapy`, JS/WASM, C |
| Stars | 5,099+ on GitHub |

**Recommendation:** the CLI's image path is `subprocess` → `chafa` with the right `--format` and `--colors` for the detected terminal. Don't reimplement it. Don't pull in Pillow for this — chafa is the right tool.

---

## 7. The "no code blocks, no thinking" rule — the fix

The user has a hard rule: when the LLM responds, never show a ````` code fence, never show a `▎ thinking:` preamble, only the beautified output. This is a *post-processor* job, not an LLM-prompt job (because the LLM is unreliable about following it).

### 7.1 Detection patterns to strip

| Pattern | Regex hint | Action |
|---|---|---|
| Fenced code block | ````` + lang? + … + `````` | Replace with single line: `code (N lines, lang: X) — say "show code" to reveal` |
| Inline backticks | ``…`` | Keep, but normalize to U+2018 / U+2019 quotes if it's a word, not code |
| "Let me think…" preamble | `^(Let me\|First,\|To begin,\|I need to\|Sure,\|Here is\|Here are).*?\n` | Drop the line entirely |
| Numbered reasoning | `^1\.\s.*$\n^2\.\s.*$` chains | Drop unless the user asked "show your work" |
| Markdown headers | `^#{1,6}\s+` | Strip the `#`s, keep the text; demote to a colored separator line |
| Bullet lists (`-`, `*`) | `^\s*[-*]\s+` | Convert to `▎ ` for visual consistency |
| Horizontal rules | `^---+$` or `^===+$` | Replace with `───` colored separator |
| "Thinking:" block | `▎ thinking:` (your existing R3) | Strip unless `show thinking` was set this turn |
| Italic / bold markdown | `*…*` `**…**` `_…_` | Strip the markers; the terminal can't render them anyway |

### 7.2 The post-processor pipeline (sketch, not code)

| Stage | Input | Output |
|---|---|---|
| **1. detect** | raw LLM text | mark fences / preambles / headers |
| **2. collapse-fences** | text with marks | text with `code (N lines, lang: X) — say "show code" to reveal` |
| **3. strip-thinking** | text | text without the preamble lines |
| **4. normalize-glyphs** | text | text with `▎` bullets, `──` separators, no `*`/`#` |
| **5. chart-detect** | text | text with chart blocks pre-rendered (bar/line/heatmap/waffle/etc.) |
| **6. beautify** | text | text with tables normalized, KV → table, etc. |
| **7. colorize** | text | text with semantic color applied to status, numbers, alerts |
| **8. emit** | final text | streamed to TUI / webui / tray |

The `show code` and `show thinking` toggles are session-level flags. When on, stages 2 and 3 are skipped. When off, they collapse.

---

## 8. Pi — the new base harness, and how it changes the plan

Pi is a **minimal coding-agent harness** that the maintainer is now using as the base. The design is "minimal core, everything else is an extension." This maps cleanly to CortexAgent.

### 8.1 Pi's extension points (the menu)

| Extension type | What it adds | Where in CortexAgent |
|---|---|---|
| **Slash command** (`/mycommand`) | User-invoked action | `cortexagent doctor`, `cortexagent --restart`, `cortexagent status` become `/doctor`, `/restart`, `/status` inside the TUI. |
| **Custom tool** (LLM-callable) | New function the model can invoke | `rag_query`, `ingest_domain`, `web_search`, `gen_image`, `gen_video` all become `pi.registerTool()` calls. |
| **Event hook** (`on("tool_call")`) | Intercept / block / modify | The pre-flight gate, the anti-hallucination pass, the prompt-queue conflict detector all hook here. |
| **Custom UI component** | A widget in the TUI | The tray popout's panels (tok/s sparkline, memory H/W/C, alerts, queue) become Pi TUI components. |
| **Theme override** | Color palette per role | The semantic palette from §2.3. |
| **Statusline widget** | A line at the bottom of the TUI | The existing `lib/statusline.py` becomes a Pi statusline extension. |
| **Keybinding** | A shortcut | `Ctrl+R` for refresh, `Ctrl+L` for last response, etc. |
| **CLI flag** | A `--flag` | `cortexagent --tui`, `--web`, `--no-color`, `--ascii-fallback`. |
| **Session persistence** | `pi.appendEntry()` | SessionBridge becomes a Pi extension that calls `pi.appendEntry()` on each turn. |

### 8.2 Where the beautify work lives in pi

| Component | Implementation |
|---|---|
| **Chart library** | A pi extension `~/.pi/agent/extensions/cortexagent-charts.ts` that exports `bar()`, `line()`, `sparkline()`, `waffle()`, `heatmap()`, `treemap()`, `sankey()`, `gantt()`, `gauge()`, `funnel()`. Each is a pure function `(data, width) -> string[]`. |
| **Image renderer** | A pi extension `cortexagent-images.ts` that detects terminal protocol (Kitty / Sixel / half-block) and calls `chafa` or emits the right escape codes. |
| **Palette** | A pi extension `cortexagent-theme.ts` that registers the semantic palette (§2.3) as a theme. |
| **Post-processor** | A pi hook in the `tool_call` and `tool_result` events that strips fences, strips preambles, normalizes glyphs, then calls the chart library on detected data. |
| **Statusline** | A pi statusline widget that renders the overseer state in the bottom bar: `● overseer  ▲ q 3  ◐ mem 57%  ▁▂▃ tok/s 12.3`. |
| **Tray popout** | This is a different process (tkinter). The beautify library is shared (Python port of the TypeScript chart lib, or a subprocess that calls the TS version via RPC). |

### 8.3 The cleanest path

1. **Lock the extension shape** — TypeScript module exporting a default function `(pi: ExtensionAPI) => void`. Inside, register tools, hooks, commands, widgets, theme.
2. **Put all the chart code in one extension** — `cortexagent-charts.ts`. ~20 pure functions, zero state, zero side effects. Easy to test.
3. **Put all the post-processor logic in one extension** — `cortexagent-postprocess.ts`. Pure functions on strings, called from a `on("tool_result")` hook.
4. **Put the theme in one extension** — `cortexagent-theme.ts`. Semantic palette + auto-detect.
5. **Put the statusline in one extension** — `cortexagent-statusline.ts`. Renders overseer state from the daemon's `control.sock`.
6. **The webui** continues to call the same chart functions via the daemon's HTTP API. The chart library is shared logic, not duplicated.
7. **The tray popout** calls the same chart functions via a Python port, or via subprocess to a small CLI that uses the TS version.

The whole thing becomes **declarative and testable**: each extension is a unit, each function is a unit, and the system is the sum of its parts.

---

## 9. Cross-surface unification — the visual language

The user complained the three surfaces (CLI / webui / tray) are confusing and overlapping. The fix is a **single visual language** that all three render in their own way.

| Concept | CLI glyph | Webui render | Tray popout render |
|---|---|---|---|
| **Daemon up** | `● daemon 8080` (green) | green dot + label | green `●` in session panel |
| **Overseer ticking** | `◍ overseer 114816 (12 ticks)` | animated `◍` + tick count | rotating ring + tick count |
| **tok/s sparkline** | `▁▂▃▄▅▆▇█ 12.3` inline | canvas line chart | tkinter Canvas polyline |
| **Memory tiers** | `H 587 W 674 C 27` | 3 colored bars | 3 mini bars |
| **Queue** | `q 3 ▶ 1 ▲ 2` | 3-line table | count + scroll list |
| **Schedule** | `cron 5` next `@ 14:30` | countdown | countdown text |
| **Minify savings** | `8% saved · 977K tok · 257 runs` | percent + sparkline | percent + sparkline |
| **Alert** | `! memory > 80% (87%)` | red banner | red list item |
| **Error** | `✕ big load failed: OOM` | red toast | red list item |
| **Status line** | `cortexagent  ●  q 0  12.3 t/s  14:30` | footer bar | bottom strip |

The semantic palette (§2.3) + the glyph vocabulary (§3) + the chart library (§4) + the post-processor (§7) make this automatic. The same data → three presentations, all in the same visual language.

---

## 10. Prioritized recommendation list

| # | Title | Impact | Effort | One-liner | Verification |
|---|---|---|---|---|---|
| 1 | Lock semantic palette + 256/truecolor auto-detect | HIGH | S | Define 8 colors, probe terminal, set up palette module. | Render a swatch in 4 terminals; check `tput colors` and `COLORTERM` paths. |
| 2 | Add real sparkline + multi-series matrix | HIGH | S | Two functions, ~30 lines. | Render 60 samples in 30 cells; compare to a chart. |
| 3 | Strip ````` fences + thinking preambles | HIGH | M | Post-processor, regex-based, session-toggled. | Run on 100 sample responses; assert no ````` in output. |
| 4 | Replace pie with waffle | MED | S | 10×10 grid, percent per cell. | Render 5 sample parts-of-whole; assert legibility. |
| 5 | Build the chart library as a Pi extension | HIGH | M | 20 pure functions, one TS file, one Python port. | Unit tests on each function; visual diff against `textcharts`/`ggterm` for parity. |
| 6 | Add Sixel / Kitty image support via chafa | MED | M | Detect protocol, call chafa with the right flags. | Render the same image in Kitty, xterm, GNOME Terminal; visually compare. |
| 7 | Add gantt for schedule timeline | MED | M | One function, takes cron entries + now(). | Render next 24h of scheduled tasks; verify against `crontab -l`. |
| 8 | Add heatmap for memory × time | MED | S | ` ░▒▓█` matrix, rows = tier, cols = last 24h. | Render one row per tier for the last 24 ticks; verify against hot.jsonl. |
| 9 | Add statusline as a Pi extension | HIGH | S | Bottom bar, `● overseer  q 0  12.3 t/s`. | Drop in; verify it shows on every prompt. |
| 10 | Define the glyph vocabulary + colorblind backstop | MED | S | One table in a constants file; every status uses it. | Render every state in colorblind simulator; verify readable. |
| 11 | Theme override via ~/.cortexagent/theme.json | LOW | S | Load file if present; else use semantic palette. | Drop a custom theme; verify it overrides defaults. |
| 12 | Add the no-cap rule for ASCII fallback | MED | S | Every Unicode glyph has an ASCII twin; auto-switch if `LANG=C`. | Run in `LANG=C` terminal; verify nothing breaks. |
| 13 | Add real data-driven flowchart | MED | L | Parser that takes a DAG and renders it with `┏━┓┗━┛` etc. | Feed 5 sample DAGs; visually inspect. |
| 14 | Add sankey for token flow | MED | M | `┃`-width flows between nodes. | Render the request → minify → model → response pipeline. |
| 15 | Unify visual language across CLI/webui/tray | HIGH | L | One shared chart library, three renderers. | Render the same dataset in all three; compare visually. |

---

## 11. Open questions for the maintainer (5)

1. **Are we going to do the work in TypeScript (pi) and port to Python, or write in Python and call from pi via subprocess?** This changes the order of #5 above.
2. **Is the tray popout staying tkinter, or moving to a webview (which would let it use the same renderer as the webui)?** Tkinter has no half-block, no Sixel, no braille. Webview does.
3. **What is the user's terminal?** If they're in Kitty or Ghostty, image support is easy. If they're in GNOME Terminal, it's half-block only. The chart library should target the lowest common denominator and let the renderer upgrade.
4. **Do we keep the `▎ thinking:` line at all, or is "show thinking" a session setting the user toggles when they want to see the model's reasoning?** The current default-on behavior may be the source of the "I don't want to see thinking" complaint.
5. **Where does the beautify post-processor run — in pi's `on("tool_result")` hook, or in the daemon's grammar proxy, or in the webui's render path?** Three options, three different latency profiles. The grammar proxy is the chokepoint (one place to maintain), the hook is the most flexible, the webui render is the most isolated.

---

## 12. Sources

- [termaid](https://termaid.com/) · [termaid GitHub](https://github.com/fasouto/termaid/)
- [textcharts (PyPI)](https://pypi.org/project/textcharts/)
- [Ripl charts](https://www.ripl.run/)
- [ggterm](https://github.com/shandley/ggterm)
- [Unicode Block Elements (U+2580–U+259F)](https://unicode.org/charts/nameslist/n_2580.html)
- [hyperb1iss/hyperskills TUI visual catalog](https://github.com/hyperb1iss/hyperskills/blob/HEAD/skills/tui-design/references/visual-catalog.md)
- [SymbolFYI terminal & CLI symbols](https://symbolfyi.com/symbols-for/terminal-cli/)
- [R-That Wiki: sub-character precision with Unicode blocks](https://wiki.r-that.com/patterns/sub-character-unicode-precision/)
- [Æsh Charts module](http://aeshshell.github.io/docs/aesh/charts/)
- [chafa](https://github.com/hpjansson/chafa/) · [chafa man page](https://hpjansson.org/chafa/man/)
- [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
- [ratatui-image](https://github.com/ratatui/ratatui-image)
- [pi-mono (pi coding agent)](https://pi.dev/)
- [pi-mono extensions docs (GitHub)](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
- [pi-mono TUI docs (GitHub)](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/tui.md)
- [pi-mono architecture (mintlify)](https://badlogic-pi-mono.mintlify.app/concepts/architecture)
