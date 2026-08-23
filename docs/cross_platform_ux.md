# Cross-Platform UI/UX Reference — CortexAgent

> Design principles for the four CortexAgent surfaces: **terminal TUI**, **Tkinter desktop console**,
> **web app**, and **mobile**. Written so interaction design is planned *before* any panel or screen
> is built — not retrofitted after.
>
> Scope: interaction design, accessibility, ergonomics, and cross-platform consistency.
> The visual design system (glass/3D aesthetic, color, typography, motion) lives separately in
> [`spatial_ui_design.md`](spatial_ui_design.md) and is deliberately **not** repeated here.
> This doc assumes that aesthetic; it defines *how a user operates* the panels, not *how they look*.

**Surfaces referenced throughout:** the input bar, active-tabs panel, scheduler panel, and memory
panel — the four recurring surfaces of CortexAgent. The principles apply to every panel/screen;
each section's checklist can be applied to any new surface before it's built.

---

## 0. The one rule that resolves every other tension

> **Consistency of meaning. Variety of mechanism.**

Users should never have to *re-learn what a panel is* when they switch surfaces — but they *should*
get the platform's native input modality, gesture language, and physical placement. Pixels and
gestures are platform-native; **state, terminology, and mental model are invariant.**

When in doubt, ask: *"Is this a property of the task, or a property of the platform?"*
- Task property → make it identical everywhere.
- Platform property → make it native everywhere.

---

## 1. Consistent vs. Platform-Native — the decision framework

### 1.1 The three tiers

| Tier | What lives here | Rule |
|------|-----------------|------|
| **Domain-invariant** | Mental model, task grammar, terminology, state semantics, undo/recovery guarantees, the identity of the four panels | Identical on every surface, byte-for-byte where sensible |
| **Cross-platform core** | The interaction *flow* (compose → send → see result → recall), keyboard model, focus flow, the four panel *roles* | Same behavior everywhere; the *input mechanism* adapts |
| **Platform-native** | Physical chrome, input modality, gesture language, control placement, system integration, typography scale, motion | Follow each platform's convention — never force one platform's chrome onto another |

### 1.2 A decision table you'll actually use

For **each UI element**, ask which column it falls in:

| UI element | Tier | Concrete guidance |
|-----------|------|-------------------|
| Panel identity + labels ("Active Tabs", "Scheduler", "Memory") | Domain-invariant | Same name, same ordering, same semantics everywhere |
| Send / Execute action | Cross-platform core | Same *purpose*; **placement is native** (see §3) |
| Text input / compose | Cross-platform core | Same editing model; native text field behavior |
| Command/back navigation | Platform-native | TUI=keys, desktop=Esc/Ctrl+W, web=browser back, mobile=system back |
| List scrolling | Platform-native | TUI: keys/PgUp; desktop: wheel+keys; web: scrollbar; mobile: touch |
| Status/alerts | Cross-platform core | Same severity model (`info/warn/error/critical`); same notification style is native |
| Autocomplete / suggestions | Cross-platform core | Same engine; keyboard vs touch invocation differs |
| Long-form log / memory output | Domain-invariant | Same *content*; **access strategy differs** (§4) |
| Cancel / interrupt (Ctrl+C) | Cross-platform core | Must behave identically; surface the same recovery affordance |
| Theme/contrast | Platform-native | Follow system theme + `prefers-color-scheme`; honor OS high-contrast |

### 1.3 Anti-patterns to reject

- **"Copy the web app to mobile"** — forces mouse paradigms (hover, drag, click-width targets) onto touch.
- **"Fancy TUI everywhere"** — boxes/colors that render fine in truecolor terminals break in 16-color or AT.
- **"Every platform gets its own UX language"** — destroys the shared mental model (the whole point of the four-panel identity).
- **"Native chrome, web semantics"** or the inverse — mixed signals confuse muscle memory.
- **"Emoji as core semantic"** — emoji render, size, and read differently per platform and AT; use them as *decoration*, never as the *only* signal (§4.4).

### 1.4 Practical rule of thumb
Match the **50–150 ms cognitive load** of each surface. A power user's keystroke "muscle memory" for
`Ctrl+K` (jump-to-memory) should survive to desktop and web; but `⌘K`/`Ctrl+K` binding is *native*, not
a faithful copy of a TUI key. Bind the same *action*, to each platform's conventional key.

---

## 2. Accessibility as a baseline requirement

Accessibility is **not** a checklist add-on; it is a **baseline contract**. Design surfaces so that a
keyboard-only user, a screen-reader user, a low-vision user, and a motor-impaired user each have a
*complete* path through the app — not a parallel "accessibility mode."

### 2.1 Color contrast — hard minimums (WCAG 2.2)

| Element | Minimum ratio | Notes |
|---|---|---|
| Normal text | **4.5:1** | WCAG AA; against every background it appears on (not just the theme) |
| Large text (≥18pt / 14pt bold) | **3:1** | |
| UI components & graphics | **3:1** | Send button border/state, panel chrome, focus ring vs. its background |
| AAA (stretch) | 7:1 text, 4.5:1 large | Aim here for text in the Memory and Scheduler panels — they're read for long stretches |

**Contract for the design system:** every color token in `spatial_ui_design.md` (glass, electric blue,
amber alerts, etc.) must be paired with its **on-color** that passes 4.5:1, *and* must not be the *only*
carrier of meaning. A green "healthy" and red "critical" must also differ by **icon + text**, never by
color alone (colorblind-safe, §2.4).

### 2.2 Semantic widget usage

- **Use the platform's native control first** (Tkinter `ttk.Button`, HTML `<button>`, `accessibilityRole` on
  mobile). Native controls get semantics, focus, keyboard handling, and AT support for free.
- A custom widget must expose **name, role, value, and state** to the platform's accessibility API:
  - TUI: `textual`/`prompt_toolkit` widgets expose labels; if rolling your own, emit explicit screen-reader
    labels, not raw box-drawing.
  - Desktop/Tkinter: Tk's AT story is **weak** — see the desktop checklist §5.2 for what to do about it.
  - Web: correct ARIA role (don't invent roles), `aria-label` where there's no visible text, `aria-live`
    regions for streaming output.
- **Focus order must be logical** (matches visual order for LTR). Never tab into a hidden element.

### 2.3 Screen-reader / assistive-tech compatibility

| Surface | Primary AT | Live output handling |
|---|---|---|
| Terminal TUI | NVDA/Orca over the terminal; Speak-Aloud | Streaming model output must announce *arrival* without interrupting typing — keep an explicit live-region/status line the AT can watch |
| Desktop (Tk) | Narrator / NVDA (Tk interop is limited) | Provide a dedicated "announce status" call rather than relying on Tk virtual events |
| Web | VoiceOver, NVDA, TalkBack | `aria-live="polite"` for status; `aria-live="assertive"` only for genuinely blocking errors |
| Mobile | VoiceOver (iOS) / TalkBack (Android) | Respect the OS announcer; don't fight it with custom haptic-heavy gestures |

**Key rule:** streaming/model output should be **polite/quiet** (don't interrupt), while *errors and
   blocking status* may be **assertive**. Make every state transition discoverable, not just visible.

### 2.4 Colorblind + low-vision safety
- Never convey state **by color alone** (§2.1). Pair color + icon + text.
- Honor OS **high-contrast / forced-colors** modes (web `forced-colors`, macOS "Increase Contrast",
  Windows high contrast).
- Provide both **light and dark** themes that each pass 4.5:1 (the glass aesthetic must have a
  high-contrast sibling, not just glow).
- Support **text scaling** (system font scale / web zoom to 200%+ / mobile Dynamic Type) without
  breaking the four-panel layout.

### 2.5 Real-user testing is mandatory — scanners are not enough

Automated scanners (axe, Lighthouse, WAVE) catch **only a fraction** of real AT failures — typically
  30–50%, and almost none of the *interaction* problems (focus flow, announcement ordering, gesture
  conflicts). **Baseline requirement:**

1. **Per platform, test with real assistive-tech users** — minimum 3–5 distinct AT/impairment profiles
   (screen reader, keyboard-only, low vision/magnifier, motor).
2. Include one *novice* AT user (fresh to the tool) — they surface on-boarding barriers scanners can't.
3. Run the **core task** end-to-end (compose → send → read result → recall from memory) — not just
   "does the button have a label."
4. Record *time-on-task* vs. a sighted/mouse baseline; a big gap = an accessibility tax, fix it.
5. Iterate: fix → re-test with the same users. Accessibility regressions are **blocking**.
6. Repeat the pass when a **new panel** ships — each panel gets its own AT pass before it's "done."

**Where to find testers (no budget):** university disability-services UX programs, regional WCAG /
AT meetups, a11y Slack, or offering a small stipend through a local advocacy org. Even 3 users beats
0 and beats any scanner.

---

## 3. Interaction ergonomics — handedness & placement

Design for **both** dominant hands and for **no** dominant hand (switchable). No fixed corner should
assume one-hand dominance.

### 3.1 The send-button question (your explicit concern)

A **bottom-right send button is right-hand-biased** — it sits in the right thumb's natural reach zone
on a phone held in the right hand, and near the mouse on a desktop. For a **left-handed** user it's
the far corner. This is the single most common handedness bug.

**Mitigation ladder (choose, don't fake it):**

| Approach | Effort | Fit |
|---|---|---|
| **Keep it bottom-right but make the whole layout mirrorable** (a `Handedness: left/right` setting that flips input bar + action panel) | Medium | The *correct* fix; matches OS left-hand modes |
| **Bottom-center send** (between input and panels) | Low | Thumb-neutral-ish; slightly larger travel for right thumb; good default |
| **Make the input bar the action**: pressing `Enter` (desktop/TUI/web) or the keyboard's return on mobile *is* the send; a visible on-screen send is secondary | Low | Keyboard- and physical-keyboard-native users never need the button |
| Follow the **platform convention** (e.g., major chat apps put Send bottom-right) | Trivial | Acceptable *only* if you also offer the left-hand mirror; otherwise ship biased |

**Recommended:** make the primary send path **keyboard-native** (Enter everywhere), and place the
visual send where **both thumbs** can reach it, defaulting to bottom-right for convention but exposing
a handedness toggle.

### 3.2 Side-panel placement

| Panel position | Who it favors | Risk |
|---|---|---|
| **Right panel** (e.g., Memory / Active Tabs on the right) | Right-handed mouse users (less cross-screen travel); LTR reading flow | Left-handers make long sweeps; conflicts with scrollbars/vertical gesture zones |
| **Left panel** | Left-handed mouse users; RTL reading | Right-handed dominant flow disrupted |
| **Non-dominant side** | The general rule: keep the *dominant* hand on the primary content / input, put reference panels on the *non-dominant* side | Reading a panel while typing pulls the eyes/pointer away |

**Rule:** put the **primary working surface (input/compose/result)** in the dominant-hand's near zone,
and **reference panels** (memory, scheduler list, active tabs) on the **non-dominant** side so the
dominant hand stays on the primary action. On mobile, reference panels are **bottom sheets or tabs**,
not persistent side rails (side rails waste thumb-reach space).

### 3.3 Handedness audit — apply to every panel

- [ ] Does any *frequently-used* control live only in a **far corner** that one hand must stretch to?
- [ ] Is the layout **mirrorable** (a setting flips it), or at least **RTL/LTR aware**?
- [ ] Is the primary action reachable by **both** thumbs without a comfortable re-grip?
- [ ] Are **secondary actions** (cancel, edit, archive) not in a "shadow" the dominant hand covers?
- [ ] Does the OS **accessibility setting** (one-handed keyboard, right/left-hand toggle, etc.) get respected?
- [ ] Does a **10-finger** (both-hands-on-keyboard) user also have a fast path (shortcuts), not only pointer?

### 3.4 Motor ergonomics
- **Touch targets ≥ 44–48 px** on mobile (recommended; WCAG target-size minimum is 24×24 CSS px — that is a
  floor, not a target).
- **Spacing** between actionable targets: ≥ 8 px to prevent mis-taps.
- Respect **reduced motion** (mobile Reduce Motion / web `prefers-reduced-motion`) — turn off spring
  physics, parallax, and the glass "air" drift from the design system for those users.

---

## 4. Terminal-specific constraints (don't carry these to GUI)

The terminal is the *most* constrained surface and the one that must remain fully usable. These rules
**invert** some GUI assumptions:

### 4.1 Keyboard-only is the baseline, not an add-on
In a TUI the keyboard is the **only** input. Every action must have a keybinding, every focusable
element must be reachable, every state must be *readable*, not just visible. There is no mouse, no
hover, no drag. If it only works with the mouse, it doesn't exist.

### 4.2 Don't rely on color or spacing to convey hierarchy
- **Color:** terminals range from 16-color ANSI to truecolor. Convey severity/state with **symbols,
  structure, and text** first — color is an enhancement that may not be rendered.
- **Spacing**: monospace grid + tabular alignment, not CSS margins. Hierarchy via **indentation,
  numbering, and explicit headers/breadcrumbs** (`[1] / [2] / [3]`, `─` rules, `>> ` depth markers).
- **Emoji** is not safe as a semantic (uncolored, width-variable, AT-read-ambiguously). Use ASCII-safe
  markers (`[!]` `[x]` `[*]`) as the semantic, emoji as optional garnish.

### 4.3 Scrollback is finite and shallow
Terminal scrollback is typically **~10k lines**, and "scroll forever" is not a retrieval strategy for a
  memory panel or long model output. Provide **bounded access**: pagination, `/tail`, `/grep`,
  `/save-to-file`, and a filtered search — not a dependency on the emulator's buffer.

### 4.4 Screen readers over the terminal
- Provide a **label or a screen-reader-safe** rendering mode (a "plain output" toggle that strips box
  drawing) for dense panels.
- Streamed output must let a screen reader keep up: chunk, keep a stable cursor/location, expose a
  "head/tail" point, not a live-flood.

### 4.5 Width / wrapping / unicode reality
- Design for **80-col minimum**, render fine to 160+; **no fixed-width assumptions** about the layout.
- **Text wrapping** in narrow terminals, **CJK/wide glyphs** (width-2 cells), and **combining characters**
  must not break alignment or cursor math.
- Detect **color support** (`TERM`, `COLORTERM`); degrade gracefully to mono.

### 4.6 TUI library implications
`textual`, `prompt_toolkit`, or `urwid` differ in accessibility support:
- Prefer the library's **accessible/render** abstractions to raw box-drawing.
- Keep a **raw text output mode** for model output (AT and pipe/compat), in addition to the rich view.

---

## 5. Per-platform checklists

Apply the relevant checklist to **every panel/screen before it's built.** Each is "definition-of-done"
for that surface.

### 5.1 Terminal TUI
- [ ] Every action has a keyboard binding; keyboard is the only input (no mouse-only).
- [ ] No state conveyed by color/spacing alone; symbols + structure carry hierarchy (§4.2).
- [ ] 80-col design works; wraps and handles wide/CJK without breaking cursor math.
- [ ] Long output (memory/logs) has **filter/pagination/export**, not scroll-forever reliance.
- [ ] Focus is **visible** in every terminal mode (highlight row, cursor).
- [ ] Screen-reader-safe: a plain-text output mode + live-status announce model.
- [ ] Enter sends, Ctrl+C/Ctrl+K etc. match the shared action set (§1.4).

### 5.2 Desktop (Tkinter console)
- [ ] **DPI/HiDPI**: Tk is notoriously blurry at scale — force `Tkinter` scaling correctly or choose a
  scaling-aware approach; test at 100%/150%/200% OS scale.
- [ ] **Native controls** via `ttk` where possible (real semantics + theming).
- [ ] **Tab order** explicit; `Alt` mnemonics + accelerators (Ctrl+K, Ctrl+P, etc.) on every command.
- [ ] **AT is the gap**: Tk's screen-reader story is weak; expose an explicit "announce status"
  hook + prefer ttk widgets; test with Narrator/NVDA; if the gap is unacceptable, plan a web or
  native shell for AT-sensitive surfaces.
- [ ] **Keyboard-only** full path (no control reachable only by mouse).
- [ ] **Contrast** from the design system verified at 4.5:1 in both themes.
- [ ] **DPI / resize** behavior sane; the four panels reflow, no fixed-width trap.
- [ ] **Handedness**: input is keyboard-native + a mirrorable layout; side panels on non-dominant side.
- [ ] Minimize-to-tray / restore behavior is discoverable and keyboard-accessible.

### 5.3 Web
- [ ] **WCAG 2.2 AA**: 4.5:1 text / 3:1 UI+graphics; verified (not assumed).
- [ ] **Semantic HTML** + correct ARIA; roles only where HTML lacks a native equivalent.
- [ ] **Live regions** for streaming output; polite vs assertive correct.
- [ ] **Keyboard** fully operable; visible focus; no focus traps.
- [ ] **Responsive**: works from a small phone-width up to a wide desktop; the four panels adapt
  (side rails → drawers on small screens, §3.2).
- [ ] **Zoom to 400%** without horizontal breakage; dynamic-type safe.
- [ ] Respect `prefers-reduced-motion`, `prefers-color-schem`, `forced-colors`.
- [ ] **Touch targets ≥ 44px** where pointer is the input.
- [ ] **Real AT test** (NVDA/VoiceOver + keyboard-only) on the core task; not just axe.

### 5.4 Mobile
- [ ] **Thumb-zone ergonomics**: primary action in reach, mirrorable for left hand (§3.1–3.2).
- [ ] **44–48 px** touch targets, ≥8 px spacing; no hover/drag-only actions.
- [ ] **System back** + navigation gestures honored (not a web-clone back button).
- [ ] **VoiceOver/TalkBack** support; every interactive element labeled and reachable.
- [ ] **Dynamic Type** / font scaling; **Reduce Motion** respected.
- [ ] **Safe areas** (notch/home indicator), **keyboard avoidance** for the input bar.
- [ ] **Orientation**: usable in both, or a clean lock reason (don't break the composer).
- [ ] **Offline/online** and **permission** patterns follow the OS, not web conventions.

---

## 6. Universal "new panel / new screen" gate — apply before building

A single reusable checklist for **any** new surface (a "record view", a "model status" panel, a
"scheduler run" screen — or any of the four core panels on a new platform):

**Before building:**
- [ ] **Model**: what is this panel's *role* (input / reference / control / status)? It maps to a
      defined tier (§1) — is it domain-invariant, core, or native?
- [ ] **Handedness**: where does it sit, does it assume a dominant hand (§3)?
- [ ] **Accessibility**: which AT does the target platform use; what are its contrast + semantic +
      live-region requirements (§2)?
- [ ] **Terminal path**: if this panel exists in the TUI, how is it keyboard-only + hierarchy-without-color (§4)?
- [ ] **Keyboard model**: does every action have a platform-native key (§1.4)?

**After building, before shipping:**
- [ ] Scanner passes (axe/WAVE/Lighthouse) — *and* one real AT user ran the core task (§2.5).
- [ ] Both themes pass 4.5:1 on every text, 3:1 on every control (§2.1).
- [ ] Handedness mirror present and the far-corner stretch test passes (§3.3).
- [ ] The panel reuses the domain terminology verbatim (no invented synonyms, §1.1).
- [ ] No new panel silently breaks an existing surface's model (regression on the shared identity).

---

## 7. Priority order when resources are tight

If you can't do everything at once, ship in this order — it front-loads the irreversible decisions:

1. **The shared four-panel identity + terminology** (§1) — cheapest, highest leverage, done in docs.
2. **Keyboard-first input everywhere** (Enter = send; bind the same actions) — the single biggest
   usability win across all four surfaces.
3. **Contrast + color-not-alone** contract (§2.1, §2.4) — cheap, catches the most common failures.
4. **Real AT pass on the core task on one surface** (start with web) — prove the model, then repeat
   per surface (§2.5).
5. **Handedness mirror on desktop + mobile** (§3) — the second-most-common ergonomic miss.
6. **TUI plain-text/output mode** (§4.4) — the terminal surfaces' largest accessibility + compat risk.

**First build failure to avoid repeating:** the prior build had *no* UX consideration. The single most
important guard here is the **gate in §6** — every panel passes it *before* code is written, and the
**accessibility pass in §2.5** happens *with real users*, not after.

---

## 8. Handedness toggle — desktop console mockup

Concrete application of §3.1–3.2 to the Tkinter desktop console. The whole layout **mirrors**,
not just the send button. Reference panels (Active Tabs, Scheduler, Memory) sit on the
**non-dominant** side; the primary working area + input stay center; the send button lands on the
**dominant** side.

### 8.1 Right-handed (default)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CortexAgent — Desktop Console                    [☰] [⚙] [—] [□] [×]   │
├───────────────┬──────────────────────────────────────────────┬───────────┤
│  ACTIVE TABS  │                                              │  MEMORY   │
│  · model-1    │   ┌──────────────────────────────────────┐   │  [recall] │
│  · planner    │   │                                      │   │  [history]│
│  · scheduler  │   │        primary working area          │   │  · item 1 │
│               │   │        (compose / result)            │   │  · item 2 │
│  SCHEDULER    │   │                                      │   │  · item 3 │
│  · 09:00 run  │   └──────────────────────────────────────┘   │           │
│  · 12:30 run  │   ┌──────────────────────────────────────┐   │           │
│  [▸ run now]  │   │  [ input field ................. ]   │   │           │
│               │   │  [send]  ← near right hand          │   │           │
└───────────────┴───┴──────────────────────────────────────┴───┴───────────┘
```

- Reference panels (Active Tabs, Scheduler, Memory) on the **left** — the non-dominant side for a
  right-hander — so the right hand stays on the input/send.
- Send button **bottom-right**, adjacent to the input field, in the right hand's natural reach.

### 8.2 Left-handed (mirrored)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CortexAgent — Desktop Console                    [☰] [⚙] [—] [□] [×]   │
├───────────┬──────────────────────────────────────────────┬───────────────┤
│  MEMORY   │                                              │  ACTIVE TABS  │
│  [recall] │   ┌──────────────────────────────────────┐   │  · model-1    │
│  [history]│   │                                      │   │  · planner    │
│  · item 1 │   │        primary working area          │   │  · scheduler  │
│  · item 2 │   │        (compose / result)            │   │               │
│  · item 3 │   │                                      │   │  SCHEDULER    │
│           │   └──────────────────────────────────────┘   │  · 09:00 run  │
│           │   ┌──────────────────────────────────────┐   │  · 12:30 run  │
│           │   │  [ input field ................. ]   │   │  [▸ run now]  │
│           │   │  [send]  ← near left hand            │   │               │
└───────────┴───┴──────────────────────────────────────┴───┴───────────────┘
```

- Reference panels flip to the **right** (non-dominant for a left-hander).
- Send button **bottom-left**, adjacent to the input, in the left hand's natural reach.

### 8.3 The toggle

```
Settings → Appearance → Handedness:   (•) Right (default)   ( ) Left
```

- The toggle mirrors the **entire layout** (panel rails + send side), not just the send button.
- It is **persisted** per user and **independent** of OS language/RTL (a left-handed English user and
  a right-handed Arabic user are different axes).
- On **mobile**, the same setting flips the thumb-zone placement of the send action (§3.1) and the
  bottom-sheet/tab order (§3.2).
- The **TUI** needs no mirror (keyboard-only, no spatial dominance) — the toggle is a no-op there,
  which is correct.

### 8.4 Verification for this mockup
- [ ] Mirror flips both the reference-panel rail *and* the send side together.
- [ ] Send stays adjacent to the input field in both orientations (no orphaned corner button).
- [ ] The setting is discoverable and keyboard-accessible (Settings reachable by keyboard).
- [ ] Covered by the accessibility protocol's `handedness` step on desktop + mobile (§5.2, §5.4).

---

*Revision date: 2026-08-19. Standards referenced: WCAG 2.2 (AA), WAI-ARIA 1.2, Apple HIG, Material
Design, Microsoft Windows accessibility conventions, terminal / TUI accessibility practice.*
