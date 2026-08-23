<p align="center">
  <img src="assets/wordmark.svg" alt="greyok-ui-framework" width="320">
</p>

<p align="center">
  <strong>CSS + JS framework — ~100 UI primitives, 12 themes, 6 size buckets.</strong>
  <br><br>
  Drop in the CSS files, pick a theme, ship. Works in HTML, TypeScript, and Python/Tkinter.
  <br><br>
  <a href="https://greyok00.github.io/greyok-ui-framework/demo/"><img src="https://img.shields.io/badge/demo-LIVE-success?style=for-the-badge" alt="Live Demo"></a>
  <a href="https://github.com/greyok00/greyok-ui-framework"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
  <a href="https://github.com/greyok00/greyok-ui-framework"><img src="https://img.shields.io/badge/version-0.1.0-orange.svg" alt="v0.1.0"></a>
  <a href="https://github.com/greyok00/greyok-ui-framework"><img src="https://img.shields.io/badge/greyok-00d4aa.svg" alt="greyok"></a>
</p>

---

## 👀 See it live

**[→ greyok00.github.io/greyok-ui-framework/demo/](https://greyok00.github.io/greyok-ui-framework/demo/)**

Every theme, every element, every category — running live in your browser. No install, no build. Click any theme in the picker to re-skin the whole page instantly.

| | |
|---|---|
| 🪟 Landing page | [demo/index.html](https://greyok00.github.io/greyok-ui-framework/demo/) — wordmark hero, 7 category cards, install tabs, 12 theme preview cards |
| ✦ Display | [demo/display.html](https://greyok00.github.io/greyok-ui-framework/demo/display.html) |
| ≡ Lists | [demo/lists.html](https://greyok00.github.io/greyok-ui-framework/demo/lists.html) |
| ⚙ Controls | [demo/controls.html](https://greyok00.github.io/greyok-ui-framework/demo/controls.html) |
| ⎘ Inputs | [demo/inputs.html](https://greyok00.github.io/greyok-ui-framework/demo/inputs.html) |
| 📊 Data viz | [demo/dataviz.html](https://greyok00.github.io/greyok-ui-framework/demo/dataviz.html) |
| ▤ Containers | [demo/containers.html](https://greyok00.github.io/greyok-ui-framework/demo/containers.html) |
| ↔ Interactions | [demo/interactions.html](https://greyok00.github.io/greyok-ui-framework/demo/interactions.html) |
| 🎨 Themes grid | [demo/themes.html](https://greyok00.github.io/greyok-ui-framework/demo/themes.html) |
| 📐 Sizes grid | [demo/sizes.html](https://greyok00.github.io/greyok-ui-framework/demo/sizes.html) |

---

## Overview

---

## Overview

A drop-in CSS framework that ships with **12 ready-made themes** (`cockpit`, `polaroid`, `console`, `terminal`, `swiss` …) and **~100 primitives** spanning display, lists, controls, data viz, containers, inputs, and interactions. Each theme declares the full token set so `live` and `fail` always read distinct, no `:root` overrides, and the same theme surface works across HTML, TypeScript, and a Python/Tkinter bridge.

```
┌──────────────────────────────────────────────────────────────┐
│  100 elements · 12 themes · 6 sizes · 0 build  │
└──────────────────────────────────────────────────────────────┘
```

<table>
  <thead>
    <tr>
      <th align="center">Elements</th>
      <th align="center">Themes</th>
      <th align="center">Sizes</th>
      <th align="center">Tokens</th>
      <th align="center">Languages</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="center"><strong>~100</strong></td>
      <td align="center"><strong>12</strong></td>
      <td align="center"><strong>6</strong></td>
      <td align="center"><strong>~55 CSS vars</strong></td>
      <td align="center"><strong>HTML · TS · Python</strong></td>
    </tr>
    <tr>
      <td align="center">7 categories</td>
      <td align="center">[data-theme="…"]</td>
      <td align="center">xs → tray</td>
      <td align="center">color · type · space</td>
      <td align="center">no build step</td>
    </tr>
  </tbody>
</table>

## Themes at a glance

Every theme applies through `[data-theme="<slug>"]`. The pill bar shows the bg + accent of each:

<table>
  <thead>
    <tr>
      <th>Slug</th>
      <th>Aesthetic</th>
      <th>Bg</th>
      <th>Accent</th>
      <th>Live</th>
      <th>Fail</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>neutral</code></td>
      <td>graphite + amber</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0d1015;border:1px solid #333"></span> <code>#0d1015</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ffb000"></span> <code>#ffb000</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00d4aa"></span> <code>#00d4aa</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ff5a52"></span> <code>#ff5a52</code></td>
    </tr>
    <tr>
      <td><code>polaroid</code></td>
      <td>warm paper</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#faf3e3;border:1px solid #ccc"></span> <code>#faf3e3</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#b8693c"></span> <code>#b8693c</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#2d8a8e"></span> <code>#2d8a8e</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#a83232"></span> <code>#a83232</code></td>
    </tr>
    <tr>
      <td><code>cockpit</code></td>
      <td>aviation HMI</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0a1218;border:1px solid #333"></span> <code>#0a1218</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ffb000"></span> <code>#ffb000</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00e0d4"></span> <code>#00e0d4</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ff5a52"></span> <code>#ff5a52</code></td>
    </tr>
    <tr>
      <td><code>cockpit-paper</code></td>
      <td>warm cockpit</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#1a1814;border:1px solid #333"></span> <code>#1a1814</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#d4a85a"></span> <code>#d4a85a</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#1a8a8e"></span> <code>#1a8a8e</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#c44a3a"></span> <code>#c44a3a</code></td>
    </tr>
    <tr>
      <td><code>console</code></td>
      <td>GitHub Dark</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0e1117;border:1px solid #333"></span> <code>#0e1117</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#58a6ff"></span> <code>#58a6ff</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00d4aa"></span> <code>#00d4aa</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#f85149"></span> <code>#f85149</code></td>
    </tr>
    <tr>
      <td><code>compact</code></td>
      <td>dark grey + orange</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#1a1a1a;border:1px solid #333"></span> <code>#1a1a1a</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ff8c42"></span> <code>#ff8c42</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00d4aa"></span> <code>#00d4aa</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#e06c5a"></span> <code>#e06c5a</code></td>
    </tr>
    <tr>
      <td><code>casebook</code></td>
      <td>cream paper</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#f5efe0;border:1px solid #ccc"></span> <code>#f5efe0</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#8b5e34"></span> <code>#8b5e34</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#2a7a8e"></span> <code>#2a7a8e</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#a83232"></span> <code>#a83232</code></td>
    </tr>
    <tr>
      <td><code>agent-paper</code></td>
      <td>textbook figure</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ffffff;border:1px solid #ccc"></span> <code>#ffffff</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0e7c86"></span> <code>#0e7c86</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#d68a3c"></span> <code>#d68a3c</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#a83232"></span> <code>#a83232</code></td>
    </tr>
    <tr>
      <td><code>agent-pulse</code></td>
      <td>breathing pulse</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0a0d12;border:1px solid #333"></span> <code>#0a0d12</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ffb000"></span> <code>#ffb000</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#d68a3c"></span> <code>#d68a3c</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#a83232"></span> <code>#a83232</code></td>
    </tr>
    <tr>
      <td><code>agent-history</code></td>
      <td>git-log on warm</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#fafaf7;border:1px solid #ccc"></span> <code>#fafaf7</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#0e7c86"></span> <code>#0e7c86</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#b85a2c"></span> <code>#b85a2c</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#a83232"></span> <code>#a83232</code></td>
    </tr>
    <tr>
      <td><code>terminal</code></td>
      <td>CRT green-on-black</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#000000;border:1px solid #333"></span> <code>#000000</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00ff66"></span> <code>#00ff66</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00ffaa"></span> <code>#00ffaa</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#ff3300"></span> <code>#ff3300</code></td>
    </tr>
    <tr>
      <td><code>swiss</code></td>
      <td>editorial B/W + red</td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#fafafa;border:1px solid #ccc"></span> <code>#fafafa</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#d62828"></span> <code>#d62828</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#00b8a9"></span> <code>#00b8a9</code></td>
      <td><span style="display:inline-block;width:60px;height:18px;border-radius:3px;background:#d62828"></span> <code>#d62828</code></td>
    </tr>
  </tbody>
</table>

## Install

<details>
<summary><strong>HTML / CSS</strong> — zero config</summary>

```html
<link rel="stylesheet" href="greyok-ui-framework/tokens.css">
<link rel="stylesheet" href="greyok-ui-framework/themes.css">
<link rel="stylesheet" href="greyok-ui-framework/base.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-display.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-lists.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-controls.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-dataviz.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-containers.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-inputs.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-interactions.css">
<link rel="stylesheet" href="greyok-ui-framework/elements-size.css">
<script src="greyok-ui-framework/theme-switcher.js" defer></script>
<script src="greyok-ui-framework/elements.js" defer></script>
```

Pick a theme by setting `<html data-theme="cockpit">` — that's the whole API.
</details>

<details>
<summary><strong>npm</strong></summary>

```bash
npm install greyok-ui-framework
```

Then import the CSS by name (`greyok-ui-framework/tokens.css`, etc.) — the package.json `exports` map covers every file.
</details>

<details>
<summary><strong>Python / Tkinter</strong></summary>

```python
from greyok_ui_framework import ElTheme, ElWidget, get_theme

theme = get_theme("cockpit")            # any of 12 themes
btn = ElWidget(parent, "btn", theme=theme, text="Run", command=handler)
btn.pack()

# Or rely on the theme dataclass directly
print(f"bg={theme.bg}  accent={theme.accent}  live={theme.live}")
```
</details>

<details>
<summary><strong>TypeScript</strong></summary>

```typescript
import "greyok-ui-framework/typescript/elements.d.ts";

const pill = document.querySelector(".el-pill.ok") as HTMLSpanElement;
const tabs = document.querySelector(".el-tabs-h") as HTMLDivElement;
```
</details>

## Theme switcher

A 25-line IIFE (`theme-switcher.js`) reads `localStorage['el-theme']` first, falls back to URL hash `#theme=cockpit`, then defaults to `neutral`. Add a picker to any page:

```html
<select id="theme-picker">
  <option>neutral</option><option>polaroid</option><option>cockpit</option>
  <option>cockpit-paper</option><option>console</option><option>compact</option>
  <option>casebook</option><option>agent-paper</option><option>agent-pulse</option>
  <option>agent-history</option><option>terminal</option><option>swiss</option>
</select>
<script>
  document.getElementById('theme-picker').addEventListener('change', e => {
    document.documentElement.dataset.theme = e.target.value;
    localStorage.setItem('el-theme', e.target.value);
  });
</script>
```

## Features

| Layer | What you get |
|---|---|
| **Elements** | ~100 primitives across 7 categories — Display, Lists, Controls, Data viz, Containers, Inputs, Interactions |
| **Themes** | 12 swappable themes via `[data-theme="…"]`. Switcher persists to `localStorage` + URL hash. Every theme declares the full token set. |
| **Sizes** | 6 buckets — `xs` (48 px) / `sm` (50 × 200) / `md` / `lg` (1200 × 400) / `full` (1200 × 800) / `tray` (720 × 420) |
| **Tokens** | ~55 CSS variables — color, type, space, radius, shadow, motion |
| **Stubs** | ~40 wire functions in `elements.js` — signature-pad draw, waveform seek/play, file-upload drop, code-block copy, kbd-input capture, palette arrow-nav, tabs keyboard, modal/drawer esc-close, clipboard, … |
| **Bridges** | TypeScript declarations (`.el-*` classes + `data-*` attrs) and Python/Tkinter (`greyok_ui_framework.py` parses CSS → `ElTheme` dataclass) |

## Sizes

| Token | Affordance | Use |
|---|---|---|
| `.el--xs` | 48 px | icon button, status dot |
| `.el--sm` | 50 × 200 | vertical tray popup |
| `.el--md` | fluid | default |
| `.el--lg` | 1200 × 400 | wide-short banner |
| `.el--full` | 1200 × 800 | desktop |
| `.el--tray` | 720 × 420 | popup-shaped wrapper |

Apply directly on any element: `<span class="el-pill el--xs">…</span>`

## Element categories

| Category | Count | Examples |
|---|---|---|
| **Display** | 15 | pill, dot, big-num, gauge, sparkline, barograph, kbd, badge, avatar, progress, skeleton, spinner, rating, swatch, empty |
| **Lists** | 15 | timeline (h/v), accordion, kanban, table, card, hover-card, chip, tree-list, breadcrumb, pagination, def-list, task-list, stepper |
| **Controls** | 15 | dropdown, check, toggle, switch, slider, range, segmented, search, palette, combobox, multi-select, dropdown-menu, context-menu, radio |
| **Data viz** | 10 | mini-bar, mini-line, entity-graph, treemap, sparkline, heatmap, scatter, sankey-stub, diff-view, markdown |
| **Containers** | 12 | panel, tabs (h/v/pill), modal, drawer, bento, split, sticky-*, masonry, scroll-shadow, toast-region |
| **Inputs** | 10 | input, textarea, search-bar, prompt, file-upload, swatch-input, signature-pad, audio-waveform, code-block, kbd-input |
| **Interactions** | 10 | drag/drop, drop-zone, hover-detail, tooltip, popover, context-menu, toast, infinite-trigger, anchor-nav |

## Demo pages

Run `python3 -m http.server 8768 --bind 127.0.0.1` and open `http://127.0.0.1:8768/demo/`. Each category has its own page; the theme switcher is at the top of every page.

```
demo/
├── index.html          ← this landing page (live)
├── display.html        ← pill, dot, gauge, big-num, kbd, avatar, progress…
├── lists.html          ← timeline, accordion, table, kanban, tree, breadcrumb…
├── controls.html       ← dropdown, toggle, switch, slider, segmented, palette…
├── dataviz.html        ← mini-bar, mini-line, entity-graph, heatmap, diff-view…
├── containers.html     ← panel, tabs, modal, drawer, bento, split-pane…
├── inputs.html         ← input, textarea, search-bar, prompt, file-upload…
├── interactions.html   ← drag/drop, tooltip, popover, context-menu, toast…
├── themes.html         ← 4×3 grid of theme cards (every theme × 8 elements)
└── sizes.html          ← same element in all 6 size buckets × 2 themes
```

## Project layout

```
greyok-ui-framework/
├── tokens.css               # ~55 CSS vars (neutral defaults)
├── themes.css               # 12 [data-theme="..."] blocks
├── base.css                 # reset, focus ring, scrollbar, demo bar
├── elements-display.css     # 15 display primitives
├── elements-lists.css       # 15 list primitives
├── elements-controls.css    # 15 control primitives
├── elements-dataviz.css     # 10 data-viz primitives
├── elements-containers.css  # 12 container primitives
├── elements-inputs.css      # 10 input primitives
├── elements-interactions.css # 10 interaction primitives
├── elements-size.css        # 6 size buckets
├── elements.js              # ~40 wire functions (interactive stubs)
├── theme-switcher.js        # localStorage + URL hash bridge
├── python/
│   └── greyok_ui_framework.py  # Tkinter bridge — CSS → ElTheme dataclass
├── typescript/
│   └── elements.d.ts        # declarations for every el-* class + data-* attr
├── demo/                    # 10 demo HTML files
├── assets/                  # logo.svg, icon.svg, wordmark.svg
├── package.json
├── LICENSE                  # MIT
└── README.md
```

## Conventions

- All element classes prefixed with `.el-*` (or `data-*` for behavior)
- All status colors via `--el-ok`, `--el-warn`, `--el-fail`, `--el-info`, `--el-live` (always distinct)
- All severity via `.CRIT`, `.HIGH`, `.OK` (border-left-color hook)
- Themes declare the **full** token set; never partial overrides
- Demo pages use the theme switcher at the top
- Zero `:root` overrides — themes only inherit through `[data-theme]` selectors

## Run the demo

```bash
cd greyok-ui-framework
python3 -m http.server 8768 --bind 127.0.0.1
# open http://127.0.0.1:8768/demo/
```

## License

MIT © [greyok00](https://github.com/greyok00) — see [LICENSE](LICENSE).
