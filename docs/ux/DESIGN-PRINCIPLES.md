# cortexagent — Design Principles

> Reference document for designing new panels across TUI, Tkinter desktop, web, and mobile.
> Read section-by-section while designing; do not read end-to-end.
> Cite: every recommendation links to its source. Where research is thin, we say so explicitly.

## 0. How to use this document

Each section opens with **principles** (short, normative statements), then **rationale** (why), then **platform specifics** (how Tk vs Web vs Mobile differ). Per-platform checklists at the bottom.

When a principle is **non-negotiable**, it is marked **HARD**. When it's a **convention we follow**, it is marked **STD**. When research is uncertain, it is marked **OPEN** and we defer.

The first platform being built is the **Tkinter desktop console**. Anything Tk-specific is flagged.

---

## 1. Behaviors consistent across all platforms vs platform-specific conventions

### 1.1 Principles (HARD)

| Behavior | All platforms identical? | Rationale |
|----------|--------------------------|-----------|
| Command vocabulary (slash commands: `/clear`, `/compact`, `/model`, `/memory`, `/help`, `/cost`) | **YES — identical** | Vocabulary is brand identity; users carry knowledge between devices. Source: [Claude Code CLI reference](https://docs.claude.com/en/docs/claude-code/cli-reference) |
| Model alias names (opus/sonnet/haiku or equivalent) | **YES — identical** | Same model identity on every surface |
| Cancellation semantics (`Esc` cancels generation; two-stage `Ctrl+C` aborts then clears) | **YES — identical** | The TUI is the reference; web and desktop copy it. Source: [Claude Code interactive mode](https://docs.claude.com/en/docs/claude-code/interactive-mode) |
| Conversation persistence model (one session per chat; resume by ID) | **YES — identical** | Mental model is the same |
| Streaming text appears incrementally, never batched | **YES — identical** | Users have learned to read along with the stream |
| "Stop generating" is always reachable in <2 actions | **YES — identical** | Safety + UX: users must always be able to interrupt |
| Status vocabulary (`streaming`, `waiting`, `error`, `cancelled`) | **YES — identical text labels** | Don't say "thinking" in TUI and "generating" in web |
| Permission model (default ask / accept edits / bypass) | **YES — identical** | Users must understand risk the same way on every surface |

### 1.2 Principles (STD — platform-specific convention)

| Affordance | TUI | Desktop (Tk) | Web | Mobile |
|------------|-----|--------------|-----|--------|
| Settings | Full-screen overlay (`/config`) | Native menu bar OR preferences dialog | Side panel or modal sheet | Full-screen sheet pushed from bottom |
| Help | `/help` overlay (`?` opens) | F1 / menu Help → opens window | `?` icon or `Cmd+/` panel | Info icon → full-screen sheet |
| Conversation list | Left list pane (`Ctrl+B`) | Left tree view in main window | Left sidebar (collapsible) | Top drawer pulled down OR separate "History" tab |
| New chat | `Ctrl+N` or `/new` | Button + `Ctrl+N` | `Cmd/Ctrl+Shift+O` | FAB at bottom-right OR header + |
| Model picker | `/model` command | Dropdown in toolbar | Dropdown in header | Bottom sheet picker |
| Quit/Exit | `Ctrl+D` | Window close OR `Ctrl+Q` | Close tab (browser) | OS back gesture or home |
| Attachments | `@` mention in input | File picker dialog (Ctrl+O) | Paperclip button in composer | Long-press input OR "+" button |
| Confirmation dialog | Inline yes/no | Modal dialog | Modal with focus trap | Bottom sheet with destructive button at top |

Sources:
- [Apple HIG — Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- [Apple HIG — macOS split view pattern](https://developer.apple.com/design/human-interface-guidelines/split-views)
- [Material Design 3 — Navigation components](https://m3.material.io/components/navigation-bar/overview)
- [GNOME HIG — Dialogs](https://developer.gnome.org/hig/patterns/feedback/dialogs.html)
- [GNOME HIG — Keyboard shortcuts](https://developer.gnome.org/hig/patterns/feedback/shortcuts.html)
- [ChatGPT keyboard shortcuts cheat sheet](https://learn.chatgpt.com/docs/reference/commands)
- [Cursor changelog — Cmd+L opens Chat](https://cursor.com/changelog/3-0)

### 1.3 Reference UIs we are drawing from

| Surface | Pattern we adopt |
|---------|------------------|
| **Claude Code TUI** | Slash commands, two-stage Esc/Ctrl+C, permission modes, `Ctrl+L` clear-screen, `Ctrl+R` reverse search |
| **Claude.ai web** | Left sidebar with starred projects + recent chats, Projects grouping |
| **ChatGPT web** | Command palette (`Cmd+K` / `Cmd+Shift+P`), `Cmd+/` shortcut panel, conversation list left |
| **ChatGPT mobile** | Composer anchored bottom, swipe-down drawer for history, single-tap "Stop generating" pill |
| **Cursor IDE** | Right side panel for chat (not left) — we copy this on desktop because the editor metaphor is absent on TUI/web; on web the chat panel stays right of the conversation |
| **Pi (Inflection)** | Calm, voice-first, minimal chrome; "Read Aloud" toggle; minimal status text |

Source: [Interface Patterns in the AI Era: ChatGPT](https://medium.com/@clairevo/interface-patterns-in-the-ai-era-chatgpt-b0e4f0828ce4), [Curio Design Style Guide — Cursor](https://designbycurio.com/learn/cursor-ide), [Inflection AI × ustwo case study](https://ustwo.com/work/inflection-ai/)

### 1.4 Per-platform specifics

**TUI**
- Use Inquire/Prompt-tool style widgets or raw readline; do not invent new keyboard models
- Single screen, no overlapping windows; modals are full-screen overlays
- Always render an input bar at the bottom; the prompt is sacred space

**Tkinter desktop (first build)**
- Use a main window with a left treeview (history), a center message list, and a bottom composer
- Follow [GNOME HIG](https://developer.gnome.org/hig/) on Linux; use the **ttk** themed widgets (not raw Tk) so we get system theme + fontconfig automatically
- Use `ttk::style` to map severity colors to the GNOME palette
- A native menu bar (Tk `Menu`) is required on macOS; on Linux it can be replaced by a window header bar
- Use `tkinter.font.nametofont("TkDefaultFont")` to read and respect system font size

**Web**
- Standard Material 3 / GNOME HIG / Apple HIG rules depending on target
- Composer pinned to bottom; history scrolls independently
- All keyboard shortcuts also accessible from a discoverable `Cmd+/` help panel

**Mobile**
- Native Material 3 on Android, Apple HIG on iOS; no hybrid widgets
- Bottom navigation is the **only** primary nav; never use a hamburger
- Composer at the very bottom; send button bottom-right (right-handed bias acknowledged — see §3) but **also** accept hardware-keyboard Enter

---

## 2. Accessibility as baseline requirement

> Every accessibility rule here is **HARD** unless explicitly tagged otherwise. We are not adding accessibility later; we are designing accessible from frame 1.

### 2.1 Color contrast — HARD

| Element | Minimum ratio | WCAG SC | Source |
|---------|---------------|---------|--------|
| Body text vs background | **4.5:1** | 1.4.3 | [W3C — Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum) |
| Large text (≥18pt or ≥14pt bold) vs background | **3:1** | 1.4.3 | same |
| UI component borders, focus rings, icon strokes | **3:1** | 1.4.11 | [W3C — Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast) |
| Focused vs unfocused component | **3:1** (AAA 2.4.13) | 2.4.13 | [WCAG 2.2 §2.4.13](https://www.w3.org/TR/WCAG22/) |
| Placeholder text | **4.5:1** (text is text) | 1.4.3 | WebAIM — [Contrast and Color Accessibility](https://webaim.org/articles/contrast/) |

**Practical rules**
- Ratios are exact — `4.499:1` fails. Compute with [WebAIM Contrast Checker](https://webaim.org/articles/contrast/) or [TPGi CCA](https://www.tpgi.com/color-contrast-checker/).
- Foreground/background swap preserves ratio.
- Contrast applies to every state (hover, focus, active, disabled).
- Pick palette once. Don't hand-tune per-component.

### 2.2 Semantic widget usage — HARD

| Don't | Do |
|-------|-----|
| `<div onclick=...>` | `<button>` (real element) |
| `<div role="button">` | `<button>` unless styling absolutely prevents it |
| A `<select>` with custom divs | `<select>` with native styling, or `role="combobox"` + ARIA combobox pattern |
| A "tab list" as styled divs | `role="tablist"` with `role="tab"` children + roving tabindex |
| A "chat thread" as `<div>`s | `<ul role="log">` or `<section aria-label="Chat">` with semantic message items |

Source: [WAI-ARIA Authoring Practices — Keyboard Interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)

**TUI specific:** TUI libraries (Textual, py-cui, prompt_toolkit) emit accessibility hints to BRLTTY via the console. Choose a library that surfaces widget roles. `prompt_toolkit` and `textual` are the only Python options with documented a11y work.

**Tkinter specific (HARD):** Standard Tk/Tkinter does **not** expose widget data to AT-SPI on Linux. Screen reader support for Orca/NVDA is essentially absent without [Tka11y](https://pypi.org/project/Tka11y/) (last released 2009, partially broken on modern Python 3) — see [Tk bug 0e294d96](https://core.tcl-lang.org/tk/info/0e294d9604). **Implication:** the Tkinter console is a **secondary** surface; the TUI and web/mobile are primary. We do not pretend Tk will be accessible; we document this and prioritize a11y on the other three surfaces.

### 2.3 Screen reader compatibility — HARD

**Web / Mobile**
- Every interactive control has an accessible name (label, `aria-label`, or visible text)
- Streaming AI output lives in a dedicated `aria-live="polite"` region; status changes use a separate `aria-live="assertive"` region
- **Throttle announcements** during streaming — without throttling, NVDA/VoiceOver queues every word and falls behind the model. Throttle to one announcement per N tokens or per M ms. Source: [LibreChat issue #3570](https://github.com/danny-avila/LibreChat/issues/3570)
- Message list uses semantic `<ul>`/`<li>` so NVDA's `L` shortcut jumps between messages. Source: [Jitsi PR #17716](https://github.com/jitsi/jitsi-meet/pull/17716)
- When a turn ends, clear the live region so the next turn announces fresh. Source: [MDN — Using ARIA live regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- Tool calls are **never silent**. Every tool invocation must produce a visible + spoken description ("Reading file: foo.py", "Running: pytest tests/", "Error: permission denied"). Source: [WAI-ARIA Authoring Practices — Live Regions](https://www.w3.org/WAI/ARIA/apg/practices/landmark-regions/)

**TUI**
- Long output is buffered, not reannounced. BRLTTY users navigate by character/word; the terminal is by definition already accessible text.
- Use OSC sequences for titles (`OSC 0`) so window-list readers announce context.
- Provide a `--no-color` / `--plain` mode for users on dumb terminals.

**Mobile**
- iOS VoiceOver and Android TalkBack both respect platform conventions — use the platform's standard chat list component and you get a11y for free.

### 2.4 Keyboard-only navigation — HARD

| Surface | Requirement |
|---------|-------------|
| Web | Every action reachable by Tab/Shift+Tab; visible focus indicator with ≥3:1 contrast; no keyboard traps (WCAG 2.1.1, 2.1.2, 2.4.7). Source: [W3C — Focus Order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order), [W3C — Focus Visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible) |
| Tk | Tab order must follow visual order; override with `widget.lift()` if needed |
| TUI | Single-character shortcuts (`y/n/q/:`) are fine; provide `?` to list them. **Always provide Tab/arrow equivalents.** |
| Mobile | External Bluetooth keyboard support; visible focus ring on hardware-keyboard focus |

**Focus management rules (web/Tk)**
- Modal opens → focus moves to first interactive element inside → `Esc` closes → focus returns to opener. Source: [WAI-ARIA APG — Dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
- Sidebar opens → focus moves to first item → close → focus returns to trigger
- Closing chat panel in IDEs is famously buggy — Cursor's open bug tracker shows the cost of getting this wrong. Source: [Cursor Forum — focus not restored on chat close](https://forum.cursor.com/t/accessibility-issue-cant-move-cursor-back-to-the-main-editor-from-chat-pane/158570)

### 2.5 Touch target minimums — HARD

| Surface | Minimum | Source |
|---------|---------|--------|
| iOS / iPadOS | **44×44 pt** | [Apple HIG — Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) |
| Android / Web (Material 3) | **48×48 dp** | [Material Design — Touch targets](https://m3.material.io/components/buttons/specs) |
| WCAG 2.2 SC 2.5.8 | **24×24 CSS px** (with exceptions for inline, equivalent, user-controlled) | [W3C — Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) |

**Adopt the strictest: 48×48 dp / 44×44 pt.** The WCAG 24px floor is too small for thumbs in real use.

### 2.6 Automated scanners (axe, Lighthouse) catch ≠ guarantee

Source: [Deque — Automated Accessibility Coverage Report](https://www.deque.com/automated-accessibility-coverage-report/), [axe-core rule descriptions](https://github.com/dequelabs/axe-core/blob/master/doc/rule-descriptions.md), [Rushi's WCAG-to-axe mapping](https://www.rushis.com/wcag-success-criteria-to-axe-core-mapping/)

| What axe catches well | What axe misses |
|-----------------------|-----------------|
| Missing alt text (1.1.1) | Keyboard trap detection in modal flows |
| Form labels (3.3.2) | Focus order correctness across SPAs |
| Color contrast violations (1.4.3) | Live region announcement timing/verbosity |
| ARIA validity (4.1.2) | Reading order in complex grids |
| Landmarks present and unique | Whether landmarks are *meaningful* |
| Image alt presence | Whether alt text is *correct* |

**Coverage:** ~30-57% of WCAG issues are detectable by automation. The remaining 40-70% require manual or assistive-technology testing. **A clean axe run is not a clean a11y ship.**

**What we commit to:**
- axe-core in CI on every PR (web)
- A manual NVDA + VoiceOver pass before each release
- Real user sessions (see §2.7) twice a year

### 2.7 Testing with real users with disabilities — STD

**Recruitment**
- Use specialized panels: [Fable](https://makeitfable.com/), AccessWorks (UW), AbilityNet (UK). Source: [Section508.gov — Conducting User Research with People with Disabilities](https://www.section508.gov/develop/usability-testing-with-people-with-disabilities/)
- Recruit on **functional ability + AT use**, not on medical diagnosis
- Over-recruit 15-25% to absorb no-shows

**Session structure (remote)**
- Pre-session tech check on a separate day (test screen reader, microphone, screen-share)
- 60-75 min per session; fewer tasks than typical research
- Two-person team: moderator + tech support
- Build buffer time between sessions for reset and debrief
- Source: [Deque — Real-Time Remote Usability Testing with Screen Readers](https://www.deque.com/blog/real-time-remote-usability-testing-screen-reader-users-part-1-practical-overview/)

**What to ask**
- Did the screen reader tell you what was happening?
- Where did you get stuck or confused?
- Was anything announced that shouldn't have been?
- Did any tool call happen silently?
- Could you reach the Stop button without hunting?

### 2.8 Particular concerns for AI chat UIs — HARD

1. **Streaming output must be throttled.** A 30-token/sec stream will bury NVDA/VoiceOver; queue announcements at ~1 per second or per message-boundary. Source: [LibreChat PR #3693](https://github.com/danny-avila/LibreChat/pull/3693)
2. **Tool calls must be spoken.** A silent tool execution is the worst possible a11y failure in an AI UI — the user is told nothing while the agent does something.
3. **Code blocks must be navigable.** Use semantic `<pre>`/`<code>`, label language, allow per-line navigation.
4. **Stop generation must be reachable by keyboard alone.** `Esc` on TUI/web; visible button on mobile.
5. **Status must never rely on color alone.** "Error" needs an icon + label, not just red. (W3C SC 1.4.1) Source: [W3C — Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color)
6. **Confidence/uncertainty markers must be announced.** If we ever display a confidence %, it goes in `aria-describedby`, not in a tooltip.

---

## 3. Ergonomics for left- and right-handed users

### 3.1 Principles (HARD)

1. **The "Send" / primary commit button is placed at the END of the user action, not at the screen edge.**
   - Right-handed bias in conventional chat UIs is real but small (~10% of population is left-handed; ~30% of right-handed users reach with left thumb when one hand is busy). Source: [Smashing Magazine — Designing Better UX for Left-Handed People](https://www.smashingmagazine.com/2025/07/designing-better-ux-left-handed-people/)
   - **Desktop rule (Tk + Web):** send button is rightmost in the composer row — but the input field spans the full row so the dominant-hand path is "type → arrow-right or Tab → Enter" — i.e., the keyboard path is symmetric.
   - **Mobile rule:** send button at the bottom-right of the composer is acceptable but the composer is anchored at the bottom so it lives in the thumb zone regardless of which thumb. Provide `Enter` (Bluetooth keyboard) as equivalent.

2. **Side panels: left for navigation, right for inspector/details.** This matches macOS HIG (sidebar leading, inspector trailing), Material 3 NavigationRail (left), and Windows conventions. Source: [Apple HIG — Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars), [Apple HIG — Split Views](https://developer.apple.com/design/human-interface-guidelines/split-views)
   - Reversible via Settings (allow left/right swap) for users with mirror setups

3. **Destructive actions go in the top half, primary actions in the bottom half on mobile.** This is the bottom-up design pattern: the thumb zone is the bottom. Source: [Hoober & Berkman — *Designing Mobile Interfaces*](https://www.oreilly.com/library/view/designing-mobile-interfaces/9781449378905/) (O'Reilly, 2011) — primary observational study of 1,333 users.

4. **Bottom-center is more neutral than bottom-right.** If we have a single floating action, it goes bottom-center, not bottom-right. Bottom-right favors righties. Source: [Smashing Magazine](https://www.smashingmagazine.com/2025/07/designing-better-ux-left-handed-people/), [Designerly — Inclusive Mobile UX for Left-Handed Users](https://designerly.com/left-hand-ux/)

### 3.2 Mobile thumb zones — STD

**Source research:**
- [Hoober (4ourth Mobile)](https://www.uxstackexchange.com/q/48167/) — observational study of 1,333 phone users
- [Yonsei University — Natural thumb zone study](https://yonsei.elsevierpure.com/en/publications/natural-thumb-zone-on-smartphone-with-one-handed-interaction-effe/) — >50% of screen is reachable for large thumbs, ~30% for small thumbs
- [Hanyang University — Investigating Smartphone Touch Area](https://repository.hanyang.ac.kr/handle/20.500.11754/192792)
- [Sage — Defining Thumb Reach Envelopes for Handheld Devices](https://sage.cnpereading.com/doi/10.1177/0018720812470689)

**Headline numbers (one-handed grip, ~49% of usage):**

| Zone | Approximate share of screen | Use for |
|------|------------------------------|---------|
| Bottom-center to bottom-right (right-handed) | ~25% | Primary actions, send, FAB, bottom nav |
| Bottom-left (left-handed natural reach) | ~25% | Secondary but reachable; OK for nav |
| Mid-screen | ~50% | Content, scrolling, reading |
| Top-left (right-handed grip) | <25% | Headers, titles, "back" buttons |
| Top-right (right-handed grip) | <25% | Settings overflow only |

**Diagonal NE-SW reach pattern** is consistent across studies — the thumb arcs from upper-right to lower-left for right-handed users (mirror image for left-handed). Source: [Hanyang 2019](https://repository.hanyang.ac.kr/handle/20.500.11754/192792).

### 3.3 Desktop handedness considerations — STD

- **Taskbar/dock at bottom is symmetric for both hands.** Don't move it.
- **Right-aligned scrollbars are 20-25% slower for left-handed pen users.** Source: [Inkpen et al., 2006 — Left-Handed Scrolling for Pen-Based Devices](https://www.dgp.toronto.edu/~dearman/papers/2006-LeftScrolling-IJHCI.pdf). This is irrelevant to mouse + scrollwheel but relevant to trackpad lefties. **TUI**: we use scrollbars sparingly and they appear right by default (ncurses convention) — fine.
- **Adaptive handedness detection is possible** but adds complexity. Source: [Nelavelli & Ploetz 2018 — Adaptive App Design by Detecting Handedness](https://doi.org/10.48550/arxiv.1805.08367). **OPEN**: do we add detection? Lean no — keyboard shortcuts make handedness moot.

### 3.4 Concrete recommendations

| Platform | Send / primary | Cancel / back | Overflow menu | Destructive confirm |
|----------|----------------|---------------|---------------|--------------------|
| TUI | Enter (keyboard-only) | Esc | `/commands` palette | Type full word (`delete`, not just `d`) |
| Desktop Tk | Enter or button-right of input | Esc | Menu bar / right-click | Modal dialog with explicit "Are you sure" |
| Web | Enter or button-right of input | Esc | `Cmd+K` palette | Modal with destructive button in red, top-right |
| Mobile | Right-edge of composer (thumb zone) | Swipe-back gesture | Bottom sheet | Top-of-sheet destructive button (red), confirm bottom |

**Rules of thumb (pun intended):**
- If a control is reachable only by stretching the **non-dominant** hand, it's mis-placed. Test with both hands.
- If a control requires a **second hand** to reach on mobile, it's mis-placed (unless it's a true desktop-class action like "attach file").
- If the keyboard alternative to a click is not documented, the click is a bug.

### 3.5 What the research actually shows vs conventional wisdom

| Conventional wisdom | What research shows |
|---------------------|---------------------|
| "Right-handed people are 90% of users, design for them." | ~10% left-handed, but ~30% of right-handers use left thumb one-handed — design for both. Source: [Nelavelli & Ploetz 2018](https://doi.org/10.48550/arxiv.1805.08367) |
| "Bottom-right is the natural place for Send." | Bottom-center is more symmetric; bottom-right favors righties. Source: [Smashing Magazine 2025](https://www.smashingmagazine.com/2025/07/designing-better-ux-left-handed-people/) |
| "Hamburger menus save space." | They hurt discoverability and hurt thumb reach. Source: [NN/g](https://www.nngroup.com/articles/mobile-navigation-patterns/) (implicit) |
| "Mirror the layout for RTL languages." | True for text direction; not necessarily for control placement. Source: [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/sidebars) |
| "Left-handed users are a niche." | 10% is not niche; plus right-handed users in one-handed contexts behave like left-handed users. |

---

## 4. Terminal-specific constraints

### 4.1 Keyboard-only navigation is mandatory — HARD

**Established patterns (all of these are valid; pick one set):**

| Style | Tools using it | Notes |
|-------|----------------|-------|
| Vim hjkl + modes | vim, lazygit, tig, delta | Powerful; has a learning curve. Claude Code supports `/vim` mode. Source: [Claude Code interactive mode](https://docs.claude.com/en/docs/claude-code/interactive-mode) |
| Arrow keys + Tab | btop, htop, less, fzf | Universal; boring; safe. fzf popularized Ctrl+R reverse search |
| Mnemonic single letters | ncdu, htop, tig | Discoverable via `?` help screen; fast once learned |
| Slash commands + numbered | Claude Code, OpenAI CLI | Best for AI agents — the command vocabulary is the API |

**Recommendation:** **slash commands + single-letter shortcuts when input is empty + arrow/Tab always works**. This matches Claude Code and is the most accessible for new users.

**Tab order rules (TUI):**
- `Tab` / `Shift+Tab` cycles focus between panels (input → output → sidebar → status)
- Within a panel: arrows or single letters
- `Enter` activates; `Esc` cancels
- `?` always opens help; `q` always means "quit current view" (never the whole app on a single press)

### 4.2 Scrollback for long streaming output — STD

**Claude Code pattern (our reference):**
- Auto-scroll to bottom by default
- User scrolls up → auto-scroll pauses
- `G` jumps to bottom and resumes auto-scroll
- Source: [Claude Code CLI — auto-scroll behavior](https://docs.claude.com/en/docs/claude-code/cli-reference)

**What we adopt:**
- Auto-scroll is the default for streaming
- Manual scroll up pauses auto-scroll (sticky)
- A small `[↓ live]` indicator appears at the bottom when paused
- Pressing `End` or `G` resumes
- We do NOT re-flow history mid-stream — once a line is on screen, it stays put
- Terminal emulator scrollback limit is the user's problem (document in README); we set `LINES` to terminal height

**Lazygit / btop lessons:**
- Use a status line that doesn't scroll; chat output scrolls independently
- A footer key-bar (`^C quit  ^R search  ? help`) is always visible
- Source: [Lazygit design](https://github.com/jesseduffield/lazygit), [btop](https://github.com/aristocratos/btop)

### 4.3 Conveying hierarchy without color — HARD

**Many terminal themes have 8-color or 16-color palettes. Some users run colorblind palettes (deuteranopia, protanopia). Design for the lowest common denominator.**

**Rules:**

| Channel | Use for | Always pair with |
|---------|---------|------------------|
| Color | Secondary signal, never sole signal | Glyph + label |
| Glyph (`● ✓ ✗ ⚠ ℹ ⏵ ⏸ ↻`) | Status, severity | Label |
| Text label (`[error]`, `[ok]`, `[info]`) | Primary signal | Optional color |
| Position (top/bottom, left/right) | Hierarchy | — |
| Case / weight (`**bold**`, `__underline__`) | Emphasis | Color |
| Box-drawing borders | Grouping | Color |

**Source**: [Colorblind.io — Designing for Color Blindness](https://colorblind.io/guides/designing-for-color-blindness), [WDP — Error Presentation Spec](https://wdp.dev/spec/presentation/)

**Status mapping (the canonical severity table):**

| Severity | Glyph | Text label | Color (if available) | Bold? |
|----------|-------|------------|---------------------|-------|
| Error | `✗` | `[error]` | red | yes |
| Critical | `‼` | `[critical]` | yellow | yes |
| Warning | `⚠` | `[warn]` | yellow | no |
| Success | `✓` | `[ok]` | green | yes |
| Info | `ℹ` | `[info]` | cyan | no |
| Pending / thinking | `…` or `⏵` | `[working]` | dim | no |
| Trace / debug | `·` | `[trace]` | blue dim | no |
| User input | `>` | (no label) | bold | yes |
| Assistant output | (none) | (no label) | normal | no |

**Colorblind-safe defaults** (Wong palette, 8 colors): [https://www.nature.com/articles/nmeth.1618](https://www.nature.com/articles/nmeth.1618). Substitute blue + orange for red + green if we suspect CVD. Source: [Colorblind.io — Colorblind-Safe Palettes](https://colorblind.io/guides/colorblind-safe-palettes)

**Redundant cues for every state:**
- Active tab: `► [tabname]` + reverse video + bold (three signals)
- Error: red + `✗` + `[error]` label (three signals)
- Streaming: `…` glyph + spinner position + "streaming" text in status line
- Permission required: yellow + `�` + `[permission?]` prompt + input cursor blinks

### 4.4 256-color vs truecolor detection — STD

**Detection ladder:**

```python
def color_capability():
    if os.environ.get("NO_COLOR"):
        return 0
    if not sys.stdout.isatty():
        return 0
    if os.environ.get("COLORTERM") in ("truecolor", "24bit"):
        return 24
    if os.environ.get("TERM", "").endswith("-256color"):
        return 8  # 256-color palette, no truecolor
    term = os.environ.get("TERM", "")
    if term in ("dumb", ""):
        return 0
    return 8  # safe default
```

**Rules:**
- Always respect `NO_COLOR` (https://no-color.org)
- Always respect `TERM=dumb`
- Always respect non-TTY (pipes, files) — never emit color to a log file
- Default to **8 colors + bold/dim/underline** unless we know we have 256 or truecolor
- Provide a `--no-color` flag and `--color=always|auto|never`
- Source: [NO_COLOR spec](https://no-color.org/), [Bandit CLI ansi.ts reference](https://github.com/Burtson-Labs/bandit-agent-framework/blob/main/apps/bandit-cli/src/ansi.ts)

**Truecolor is risky:** Windows Terminal (pre-1.18), some tmux versions, and some SSH tunnels strip 24-bit color silently. **Test before assuming.**

### 4.5 Unicode box-drawing characters — STD

**Source:** [Unicode Box Drawing block](https://www.unicode.org/charts/PDF/U2500.pdf) (U+2500-U+257F); historical DEC VT100 origin.

**The problem:** character widths vary by terminal:

| Terminal | Box-drawing width | Emoji width | Notes |
|----------|-------------------|-------------|-------|
| Alacritty | Unicode standard (fixed since 2022) | correct | reliable |
| Kitty | mostly correct | correct, VS16-aware | best in class |
| Foot (Wayland) | ICU-based | correct | good |
| iTerm2 (macOS) | mostly correct | correct | good |
| GNOME Terminal (VTE) | correct since 0.60 | ZWJ sequences still flaky | older distros broken |
| WezTerm | correct | correct | good |
| Windows Terminal | correct | mostly correct | newer = better |
| tmux + screen | can break widths | depends on outer terminal | use `set -ga terminal-overrides ',xterm-256color:Tc'` for truecolor; width is harder |

**Practical rules:**
- **Use ASCII (`-`, `|`, `+`) by default.** They render correctly everywhere.
- **Use Unicode box-drawing (`─│┌┐└┘├┤┬┴┼`) when `--unicode` flag is set and `wcwidth()` reports 1.**
- **Never mix ASCII and Unicode in the same line** — alignment breaks.
- **Use halfwidth katakana / CJK only when terminal reports UTF-8 locale and font has glyphs.**
- **Emoji is for color-only terminals with emoji fonts (most modern macOS, Windows Terminal, Kitty with Noto Color Emoji).** Never assume emoji renders.

**Library support:**
- Python: `wcwidth` (handles ambiguous widths); `unicodedata.east_asian_width()` for raw lookup
- Test with: `python3 -c "import wcwidth; print(wcwidth.wcswidth('─│┌'))"` → should be `3`

### 4.6 TUI accessibility — HARD, with honest limits

| Audience | Status |
|----------|--------|
| Braille display users (BRLTTY) | **Supported by accident** — terminals are text. We just need to not emit ANSI to a Braille-only stream. Source: [BRLTTY](https://brltty.app/) |
| Screen reader users in a GUI terminal (Orca, NVDA in conhost) | **Partial** — terminal text is read; widgets (panels, tabs) are not announced unless the TUI library exports ARIA-like hints via OSC |
| Screen reader users in raw Linux console | **Supported by accident** — same as BRLTTY |
| Voice control users | **Limited** — TUI libraries don't expose role names; we add explicit spoken cues (`"Tab. Output panel. Type to continue."`) |
| Cognitive accessibility | **Hard mode** — long output is overwhelming. We chunk, summarize, and let users `/compact` history. |

**Honest flags:**
- TUI is the **least accessible** surface. We do not pretend otherwise.
- We commit to: keyboard-only navigation always, NO_COLOR always, OSC titles for context switching, and explicit status labels.
- We do **not** commit to: per-widget screen reader hints in TUI (unrealistic with current Python TUI libraries).

---

## 5. Per-platform checklists

### 5.1 TUI checklist

- [ ] All actions reachable without mouse
- [ ] `Tab`/`Shift+Tab` cycle panels
- [ ] `?` opens help; help shows every keybinding
- [ ] Slash command vocabulary matches the cross-platform list
- [ ] `Esc` cancels generation; second `Esc` clears input; third exits
- [ ] `Ctrl+C` and `Ctrl+D` follow Claude Code two-stage semantics
- [ ] Auto-scroll during stream; manual scroll pauses
- [ ] `G` / `End` jumps to live output
- [ ] Status line visible always (current mode, model, streaming/idle, permissions)
- [ ] Footer key-bar visible (`^C quit  ? help  /commands`)
- [ ] `--no-color`, `--plain`, `--unicode` flags work
- [ ] Respects `NO_COLOR`, `TERM=dumb`, non-TTY
- [ ] ANSI uses 8-color + bold/dim + glyph + label for every status
- [ ] OSC title updates with current context (chat name, model)
- [ ] Long output doesn't break width (test with wcwidth)
- [ ] Box-drawing is ASCII by default; Unicode behind `--unicode`

### 5.2 Tkinter desktop checklist (first build)

- [ ] Use `ttk` widgets, not raw Tk — gets system theme automatically
- [ ] `tkinter.font.nametofont("TkDefaultFont")` to read and respect system font size
- [ ] Menu bar on macOS via `Menu` widget; menu + header bar on Linux
- [ ] Left tree view for chat history; center for message list; bottom for composer
- [ ] Tab order matches visual order; override with `widget.lift()` only when necessary
- [ ] All buttons have text labels or accessible `tooltip` text
- [ ] Composer `Enter` sends, `Shift+Enter` newline (matches web)
- [ ] Color palette maps to GNOME palette; 4.5:1 contrast for text
- [ ] Focus ring visible on every interactive widget
- [ ] Window resize preserves layout (use `grid` with `sticky` + `weight`)
- [ ] File picker uses native dialog (`tkinter.filedialog`)
- [ ] Settings open as a modal `Toplevel` window
- [ ] **Honest a11y flag in README**: "Screen reader support on Linux requires Tka11y and is partial. TUI and web are primary a11y surfaces."

### 5.3 Web checklist

- [ ] axe-core in CI; no axe errors on any page
- [ ] All interactive elements are real `<button>`/`<a>`/`<input>` or ARIA-correct roles
- [ ] Visible focus indicator with ≥3:1 contrast
- [ ] Skip-to-content link at top
- [ ] Message list is semantic `<ul>`; streaming output in `aria-live="polite"`; status in separate assertive region
- [ ] Throttle live-region announcements (≤1/sec) to avoid screen reader backlog
- [ ] Every tool call is announced (visible + spoken)
- [ ] Composer supports Enter to send, Shift+Enter for newline
- [ ] Command palette `Cmd/Ctrl+K` matches ChatGPT vocabulary
- [ ] `Cmd/Ctrl+/` opens keyboard shortcut panel
- [ ] All keyboard shortcuts also discoverable in the help panel
- [ ] Modal dialogs trap focus; Esc closes; focus returns to opener
- [ ] Sidebar left; inspector (if added) right; both reversible in settings
- [ ] Touch targets ≥48×48 CSS px (mobile breakpoint)
- [ ] Color contrast 4.5:1 text / 3:1 UI components, including all states
- [ ] Manual NVDA + VoiceOver pass before each release
- [ ] Two user sessions per year with disabled participants

### 5.4 Mobile checklist

- [ ] Bottom navigation (Material 3) OR top tab bar (iOS HIG) — never hamburger for primary nav
- [ ] Composer anchored to bottom, above IME insets
- [ ] Send button bottom-right of composer; Enter (Bluetooth keyboard) sends
- [ ] All touch targets ≥44×44 pt (iOS) / ≥48×48 dp (Android)
- [ ] Status bar shows current model + streaming state
- [ ] Pull-down drawer for history OR separate History tab
- [ ] New chat FAB bottom-right or header `+` — both acceptable
- [ ] Stop generating is a single-tap pill at the top of the streaming region
- [ ] Voice input (mic button) left of text field; long-press to record
- [ ] Settings is a full-screen sheet pushed from bottom
- [ ] Destructive actions in red, top of confirmation sheet
- [ ] iOS: respect safe areas (notch, home indicator)
- [ ] Android: respect gesture nav insets; test with edge-to-edge
- [ ] Dark mode + light mode + system-follow; all tested for contrast
- [ ] Dynamic Type (iOS) / Font Scale (Android) does not break layout
- [ ] Reduce Motion preference disables non-essential animation

---

## 6. Open questions (flagged)

| # | Question | Lean | Needs user decision? |
|---|----------|------|----------------------|
| Q1 | Detect handedness and adapt? | **No** — keyboard shortcuts make it moot | Maybe later |
| Q2 | Add a Braille-friendly mode for TUI? | **Yes** — just means don't emit ANSI to Braille | No, do it |
| Q3 | Mirror layouts for RTL languages? | **Yes for text**, **no for controls** | Yes, defer to i18n pass |
| Q4 | Adopt a charting/diagram library for TUI? (e.g., `asciichart`, `textual-plotext`) | **Yes, textual-plotext** | Maybe |
| Q5 | Voice control support (TUI speaks widget names)? | **Partial** — only on `--voice` flag | Open |
| Q6 | Customizable shortcut bindings? (Cursor's chat panel does NOT support this and it's their #1 complaint) | **Yes** — store in `~/.config/cortexagent/keybindings.toml` | Yes |

---

## 7. Sources (alphabetical by domain)

**Accessibility standards & specs**
- [W3C WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/)
- [W3C — Contrast (Minimum) SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum)
- [W3C — Non-text Contrast SC 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast)
- [W3C — Focus Order SC 2.4.3](https://www.w3.org/WAI/WCAG22/Understanding/focus-order)
- [W3C — Focus Visible SC 2.4.7](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible)
- [W3C — Target Size Minimum SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)
- [W3C — Use of Color SC 1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color)
- [WAI-ARIA Authoring Practices — Keyboard Interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)
- [WAI-ARIA Authoring Practices — Live Regions](https://www.w3.org/WAI/ARIA/apg/practices/landmark-regions/)
- [MDN — Using ARIA live regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions)
- [Deque — Automated Accessibility Coverage Report](https://www.deque.com/automated-accessibility-coverage-report/)
- [axe-core rule descriptions](https://github.com/dequelabs/axe-core/blob/master/doc/rule-descriptions.md)
- [WebAIM — Contrast and Color Accessibility](https://webaim.org/articles/contrast/)
- [NO_COLOR spec](https://no-color.org/)

**Platform design guidelines**
- [Apple HIG — Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [Apple HIG — Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars)
- [Apple HIG — Split Views](https://developer.apple.com/design/human-interface-guidelines/split-views)
- [Apple HIG — macOS](https://developer.apple.com/design/human-interface-guidelines/macos)
- [Material Design 3 — Components](https://m3.material.io/components)
- [Material Design 3 — Buttons](https://m3.material.io/components/buttons/specs)
- [Material Design 3 — Text Fields](https://m3.material.io/components/text-fields/specs)
- [Material Design 3 — Lists](https://m3.material.io/components/lists/specs)
- [Material Design 3 — Navigation components](https://m3.material.io/components/navigation-bar/overview)
- [GNOME HIG — Dialogs](https://developer.gnome.org/hig/patterns/feedback/dialogs.html)
- [GNOME HIG — Keyboard Shortcuts](https://developer.gnome.org/hig/patterns/feedback/shortcuts.html)

**Existing AI agent UIs**
- [Claude Code CLI reference](https://docs.claude.com/en/docs/claude-code/cli-reference)
- [Claude Code interactive mode](https://docs.claude.com/en/docs/claude-code/interactive-mode)
- [Anthropic Help — Projects](https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects)
- [ChatGPT keyboard shortcuts (OpenAI Learn)](https://learn.chatgpt.com/docs/reference/commands)
- [Cursor 3.0 changelog](https://cursor.com/changelog/3-0)
- [Curio — Cursor IDE design style guide](https://designbycurio.com/learn/cursor-ide)
- [Inflection AI × ustwo Pi case study](https://ustwo.com/work/inflection-ai/)
- [ScreensDesign — Pi UI breakdown](https://screensdesign.com/showcase/pi-personal-ai-assistant)
- [Interface Patterns in the AI Era: ChatGPT — Medium](https://medium.com/@clairevo/interface-patterns-in-the-ai-era-chatgpt-b0e4f0828ce4)

**Ergonomics & handedness research**
- [Hoober & Berkman — *Designing Mobile Interfaces* (O'Reilly 2011)](https://www.oreilly.com/library/view/designing-mobile-interfaces/9781449378905/)
- [Inkpen et al. 2006 — Left-Handed Scrolling for Pen-Based Devices (IJHCI)](https://www.dgp.toronto.edu/~dearman/papers/2006-LeftScrolling-IJHCI.pdf)
- [Nelavelli & Ploetz 2018 — Adaptive App Design by Detecting Handedness (arXiv)](https://doi.org/10.48550/arxiv.1805.08367)
- [Lim et al. 2016 — WhichHand (ACM MobileHCI)](https://dl.acm.org/doi/10.1145/2957265.2961857)
- [Hanyang University — Investigating Smartphone Touch Area with One-Handed Interaction](https://repository.hanyang.ac.kr/handle/20.500.11754/192792)
- [Yonsei University — Natural thumb zone study](https://yonsei.elsevierpure.com/en/publications/natural-thumb-zone-on-smartphone-with-one-handed-interaction-effe/)
- [Otten, Karn & Parsons — Defining Thumb Reach Envelopes for Handheld Devices (Human Factors)](https://sage.cnpereading.com/doi/10.1177/0018720812470689)
- [Smashing Magazine — Designing Better UX for Left-Handed People (2025)](https://www.smashingmagazine.com/2025/07/designing-better-ux-left-handed-people/)
- [Designerly — Inclusive Mobile UX with Left-Handed Users](https://designerly.com/left-hand-ux/)

**Color & contrast research**
- [Wong — Points of view: Color blindness (Nature Methods)](https://www.nature.com/articles/nmeth.1618)
- [Colorblind.io — Designing for Color Blindness](https://colorblind.io/guides/designing-for-color-blindness)
- [Colorblind.io — Colorblind-Safe Palettes](https://colorblind.io/guides/colorblind-safe-palettes)
- [WDP — Error Presentation Spec](https://wdp.dev/spec/presentation/)
- [Bandit CLI ansi.ts reference](https://github.com/Burtson-Labs/bandit-agent-framework/blob/main/apps/bandit-cli/src/ansi.ts)

**TUI / terminal research**
- [BRLTTY home](https://brltty.app/)
- [BRLTTY reference manual](https://brltty.app/doc/Manual-BRLTTY/English/BRLTTY.html)
- [Ubuntu — Read the screen in Braille](https://documentation.ubuntu.com/desktop/en/latest/how-to/accessibility/orca/read-screen-in-braille/)
- [Lazygit (Git)](https://github.com/jesseduffield/lazygit)
- [btop (Git)](https://github.com/aristocratos/btop)
- [Unicode Box Drawing block (U+2500–U+257F)](https://www.unicode.org/charts/PDF/U2500.pdf)
- [Tka11y on PyPI](https://pypi.org/project/Tka11y/)
- [Tk bug 0e294d96 — Tk does not provide accessibility info to Orca](https://core.tcl-lang.org/tk/info/0e294d9604)
- [Python — Tkinter and fontconfig (The Durkee)](https://www.thedurkee.com/posts/python-tkinter-fontconfig/)

**Accessibility real-world implementations (patterns to copy)**
- [LibreChat issue #3570 — chat updates not announced](https://github.com/danny-avila/LibreChat/issues/3570)
- [LibreChat PR #3693 — live regions fix](https://github.com/danny-avila/LibreChat/pull/3693)
- [Jitsi PR #17716 — semantic chat list](https://github.com/jitsi/jitsi-meet/pull/17716)
- [VS Code issue #291129 — screen reader in chat panel](https://github.com/microsoft/vscode/issues/291129)
- [Discourse commit 0284e0a — chat live announcements](https://github.com/discourse/discourse/commit/0284e0a2a5e59264004083ecf0959cb9db1d7329)
- [Cursor Forum — focus not restored on chat close](https://forum.cursor.com/t/accessibility-issue-cant-move-cursor-back-to-the-main-editor-from-chat-pane/158570)

**Research session logistics**
- [Section508.gov — Conducting User Research with People with Disabilities](https://www.section508.gov/develop/usability-testing-with-people-with-disabilities/)
- [Deque — Real-Time Remote Usability Testing with Screen Readers](https://www.deque.com/blog/real-time-remote-usability-testing-screen-reader-users-part-1-practical-overview/)
- [Coforma — Conduct Remote Usability Research with Accessibility in Mind](https://coforma.io/resources/playbooks/accessibility-playbook/play-2-2)
- [dxw — What we learned doing research with people using AT](https://www.dxw.com/2024/08/what-i-learned-from-doing-research-with-people-using-screen-readers/)

---

*Document version: 2026-08-19 — initial draft for Tkinter desktop console design phase.*
