# Three-Project UI Mockup Sprint — Design

**Date:** 2026-08-20
**Status:** Draft → user review
**Author:** Manager session
**Scope:** Build 12 UI mockups + 1 shared element library to compare layout options
across three independent projects.

---

## Why

User feedback 2026-08-20: existing `cortexagent-console.html` was a "weird console mix
of all three" — there are three separate projects (popup / OSINT / security-UI), and a
"console" never existed. Archived in `88cd253`.

User wants to see **multiple mockups per project** showing **different UI elements**
(graphs, dropdowns, input sections, panels, etc.) — not just theme variants. Each
project's mockups use the same data but emphasize a different hero element, so the
user can pick the layout that fits how they want to use the tool.

---

## Three locked-in projects

| # | Project | Real code | Mockup folder | Population |
|---|---|---|---|---|
| 1 | **Tray popup** (Tk, monitor + Focus Brave) | `lib/sec_tray.py` + `lib/sec_controls.py` | `ui-mockups/popup/` | 4 variants |
| 2 | **OSINT** (Flask+SQLCipher on :9999) | `lib/adapters/searxng_adapter.py` + existing :9999 webapp | `ui-mockups/osint/` | 4 variants |
| 3 | **Security-UI / SIEM+SOAR** (cockpit HMI) | `sec-1/2/3.html` are existing baseline variants | `ui-mockups/security/` | 4 variants |

A 4th project (Legal tool) is deferred — no work until the user opens a new tab.

---

## Feature list per project

### Project 1 — Popup
| # | Feature | Data |
|---|---|---|
| a | 9-check status strip (severity-colored) | 4 fail / 1 warn / 4 ok today |
| b | 3 most-recent SOAR runs | mock data, 0.8s / 5m / 3.4s |
| c | "Focus Brave window" raise action | button → alert() in mockup |
| d | Cross-status: read-only OSINT + security-UI status | 2 status pills |

**Strict: monitor-only.** No actions from the popup besides raising Brave.

### Project 2 — OSINT
| # | Feature | Data |
|---|---|---|
| a | Inline search + LLM extract layer | existing `osint-casebook-search.html` |
| b | Case file manager (open / edit / close) | CASE-01 active + 2 others |
| c | Re-extract-on-demand button per row | per-result inline action |
| d | Drag-to-case save with drop zone | existing drag handlers |

### Project 3 — Security / SIEM+SOAR
| # | Feature | Data |
|---|---|---|
| a | Timeline-first SIEM feed (newest-first, click-to-expand) | 7 events, mixed severity |
| b | SOAR rules table (run / edit / disable) | 6 rules |
| c | Pending-approval queue (per-rule approve/reject) | 2 staged rules |
| d | Run history with diff per run | 5 runs |

---

## File layout

```
ui-mockups/
├── _elements/
│   ├── elements.css            # shared element classes (~600 lines)
│   ├── elements-demo.html      # one demo page: every element in isolation + label
│   └── elements.js             # shared JS for drag, palette, accordion
├── popup/
│   ├── popup-1-timeline.html   # hero: horizontal timeline
│   ├── popup-2-gauges.html     # hero: 3×3 gauge grid
│   ├── popup-3-palette.html    # hero: ⌘K command palette
│   └── popup-4-cards.html      # hero: hover-expand cards
├── osint/
│   ├── osint-1-stack.html      # hero: stacked cards + drawer
│   ├── osint-2-graph.html      # hero: entity graph (fallback: tree-map)
│   ├── osint-3-table.html      # hero: comparison table
│   └── osint-4-command.html    # hero: ⌘K search
├── security/
│   ├── sec-1-split.html        # hero: timeline+pane tabs
│   ├── sec-2-grid.html         # hero: bento grid (fallback: split-pane)
│   ├── sec-3-accordion.html    # hero: vertical accordion
│   └── sec-4-stack.html        # hero: stacked rows (timeline first, scroll for more)
├── three-projects.html         # new index: 3 cards (popup / OSINT / security) + library demo link
└── v2-index.html               # existing (theme picker) — preserved
```

### File-naming convention
- Existing mockups: `sec-1.html`, `osint-1.html`, `popup-1.html` — keep simple
- New mockups in subdirectories: `popup/popup-1.html`, not `popup/1.html`
- File name = hero element key: `timeline`, `gauges`, `palette`, `cards`, `stack`,
  `graph`, `table`, `command`, `split`, `grid`, `accordion`, `stack` (last 4 share
  `stack` for security — distinguish with prefix)

### Why subdirectories
- Prevents re-conflation. The popup folder never imports the security folder.
- The `_elements/` underscore prefix is a namespace marker; nothing in any project
  folder can be confused for an element-library file.

---

## Element library (`_elements/elements.css`)

| Category | Elements (CSS class) |
|---|---|
| **Display** | `.gauge` (vertical + radial), `.sparkline`, `.big-number`, `.status-pill`, `.dot` |
| **Lists** | `.timeline` (h/v), `.accordion`, `.kanban`, `.table`, `.card`, `.hover-card`, `.chip` |
| **Controls** | `.dropdown`, `.checkbox`, `.radio`, `.toggle`, `.search-input`, `.command-palette` |
| **Data viz** | `.mini-bar`, `.mini-line`, `.entity-graph`, `.tree-map`, `.barograph` |
| **Containers** | `.panel`, `.tab-pane`, `.modal`, `.drawer`, `.bento-grid` |
| **Inputs** | `.text-input`, `.textarea`, `.inline-prompt`, `.search-bar` |
| **Interactions** | `[data-draggable]`, `[data-hover-detail]`, `[data-expand]` (JS via `elements.js`) |

Each element:
- Self-contained (own padding/margin/colors via CSS vars)
- One JS hook (if interactive) referenced by class, not by inline JS in the consuming mockup
- Demo'd in `elements-demo.html` with a 2-line label

### Aesthetic for the library

**One neutral palette** (graphite + amber) for the library + the index `three-projects.html`.
Then each project's 4 mockups can be themed differently if they want, but the
**hero-element showdown** is what's being compared, not aesthetics.

---

## Per-project mockup details

### Project 1 — Popup (4 variants)

| File | Hero element | Other elements | Aesthetic |
|---|---|---|---|
| `popup-1-timeline.html` | horizontal timeline (stacked events left→right, severity as lane color) | gauges, dropdown filter | Polaroid Wall (warm paper) |
| `popup-2-gauges.html` | 3×3 mini-gauge grid (aviation instruments) | numeric readouts | Cockpit Panel |
| `popup-3-palette.html` | `⌘K` command palette (type to focus) | search input, action rows | Console-Log (Plex Mono) |
| `popup-4-cards.html` | hover-expand detail cards | sparklines, tooltip | Compact Stat Block |

**Strict no-launch:** popup never opens another project's UI. Status pills for
OSINT + security are read-only.

### Project 2 — OSINT (4 variants)

| File | Hero element | Other elements | Aesthetic |
|---|---|---|---|
| `osint-1-stack.html` | cards + right-side drawer | chips, gallery, save checkbox | Casebook Notebook |
| `osint-2-graph.html` | entity graph (results as nodes; click a node to expand into a result) | mini-timeline, filter panel | Polaroid Wall |
| `osint-3-table.html` | sortable comparison table | checkboxes per row, dropdown filters | Compact Stat Block |
| `osint-4-command.html` | `⌘K` live search (results appear inline, with extract) | input at top, summary-card stream | Console-Log |

**Fallback:** if entity graph layout proves too noisy, replace with a tree-map
(same data, hierarchical boxes by entity type).

### Project 3 — Security / SIEM+SOAR (4 variants)

| File | Hero element | Other elements | Aesthetic |
|---|---|---|---|
| `sec-1-split.html` | timeline left, rules-pane right (one tab: rules / approval / history) | gauge strip, dropdown filter | Cockpit Panel |
| `sec-2-grid.html` | bento grid (each feature = a card; click to expand) | gauges, sparklines, command bar | Console-Log |
| `sec-3-accordion.html` | vertical accordion (timeline at top, one section open at a time — Rules/Approval/History) | gauges, dropdown filter | Compact Stat Block |
| `sec-4-stack.html` | stacked rows (full-screen timeline, fold to rules, scroll for approval/history) | gauges, accordion items | Cockpit Panel — paper variant |

**Fallback:** if bento grid feels overwhelming, fall back to split-pane (same data).

---

## Index page (`three-projects.html`)

Three cards up top, each labeled with the project name + open count:

- **Popup** (4 variants) → `popup/`
- **OSINT** (4 variants + existing casebook) → `osint/`
- **Security-UI** (4 variants + existing 1/2/3) → `security/`
- **Element library demo** → `_elements/elements-demo.html`

Each card lists the hero element for each variant. Click any → opens the mockup.

Visual differentiation between projects only by header chip color + project title —
no cross-project UI navigation.

---

## Out of scope / explicit non-goals

- **No cross-project navigation** — popup never opens OSINT, OSINT never opens security.
- **No "console" wrapping** — abandoned per user feedback 2026-08-20.
- **No production code changes** — these are mockups for review only. Existing real
  code (`lib/sec_tray.py`, etc.) is NOT touched.
- **No themes as a differentiator** — the 4 variants per project compare LAYOUTS,
  not aesthetics. Themes can be layered later.
- **No agent-pipeline mockups** — that's a 4th project, deferred.

---

## Build order (suggested, can be re-ordered)

1. `_elements/elements.css` + `elements-demo.html` (~30 min)
2. `popup/` — 4 files (~20 min each, total ~90 min)
3. `osint/` — 4 files (~30 min each, total ~2 hours)
4. `security/` — 4 files (~45 min each, total ~3 hours)
5. `three-projects.html` index (~15 min)

Total estimated effort: ~6.5 hours of drafting time; the user reviews after each phase.

---

## Verification (definition of done)

For each mockup file:
- File created at the path specified above
- Uses `_elements/elements.css` via `<link>` (no inline element CSS)
- Loads at `http://127.0.0.1:8768/{path}` with HTTP 200
- Contains no `console.mockup` cross-links (popup never opens OSINT etc.)
- Aesthetic is the one specified for the file
- Hero element is identifiable within 2 seconds of looking at the page

For the library:
- `elements-demo.html` shows every element class with a label
- Each element class has at least one consumer in the 12 mockups

For the index:
- 3 cards visible
- Each card links to the corresponding folder
- Element library link visible

---

## Risk and mitigations

| Risk | Mitigation |
|---|---|
| All 12 mockups feel samey | Different hero element + aesthetic per file; library demo page is the proof of variety |
| Library gets bloated | Cap at 20 elements; defer new ones until a mockup needs them |
| Entity graph layout too noisy | Fallback to tree-map (same data, different rendering) |
| Bento grid feels overwhelming | Fallback to split-pane (same data) |
| User changes mind on a feature | Mockups are cheap to re-cut; update library first, then 1–4 mockups that use changed element |
| Cross-project drift (e.g., "add OSINT to popup") | Don't. Popup status for OSINT is read-only cross-status, no launching |

---

## Open questions (already asked, locked in)

Q: How many variants per project? **A: 4.**
Q: Shared library or self-contained? **A: Shared library.**
Q: Who defines features? **A: I propose, user confirms.** (All three confirmed.)
Q: Library size? **A: Wide — 15–20 elements.**
Q: Per-project layout style? **A: Same data, different element as hero.**
Q: Themes per variant? **A: Re-skin per project for variety.**
Q: Build all 12? **A: Yes, all 12.**

No open questions remain.
