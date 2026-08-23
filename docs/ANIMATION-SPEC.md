# Enhanced Animation Requirements — CortexAgent & Clawed (separate)

> **Status:** ✅ CortexAgent core animation IMPLEMENTED (2026-08-17) in `lib/processing_animation.py` + wired into the TUI. Clawed remains separate.
>
> This is the **separate CortexAgent and Clawed implementation prompt** for
> active-work animations. It keeps the two products independent while making
> their active-work states more visual and substantial.

## Global requirement

Make the active-work animation noticeably **larger, more expressive, and more
visually interesting** than a tiny spinner or one moving bar.

### CortexAgent and Clawed stay SEPARATE

- Each application implements its own animations with its own renderer, theme,
  timing, state model, and configuration.
- **Do not share** animation packages, frame tables, renderers, config keys, or
  UI components.
- They may use similar concepts but must have **product-specific visual
  identities**.
- Both may access CortexLLM memory, but the code is totally severed between them.

### The animation must still be

- Compact enough not to scroll the conversation or break layout.
- Rendered in place in a fixed reserved region.
- Informative rather than decorative.
- Driven only by the application's existing render/update loop; **never create a
  busy loop**.
- Safe for narrow terminals.
- Fully readable when color is disabled.
- Static when reduced-motion is enabled.

---

## CortexAgent animation design

Use a larger **"Cortex processing core"** animation directly above the input
box. Reserve a fixed area of **5–7 terminal rows** while work is active.

### Normal active layout

```text
╭─ CORTEX / ACTIVE ───────────────────────────────────────────────╮
│                                                                  │
│              ╭───────◈───────╮                                  │
│              │  ◌  ◉  ◌  ◉   │   Processing request             │
│              ╰───────◈───────╯                                  │
│                                                                  │
│ Organizing your request and checking required context.           │
│ ██████████████░░░░░░░░░░░░ 48%   Context preparation            │
│ 2 of 5 stages complete · 12.6k input tokens prepared · Esc stop │
╰──────────────────────────────────────────────────────────────────╯
```

This is **not** a giant splash screen. It is a fixed-height, visually meaningful
work surface that replaces the small three-row status card **only while an
active request exists**.

### CortexAgent animation modes

Use one distinct animation per real high-level stage.

#### Preparing / organizing context
Visual: orbiting context nodes around a core.
```text
              ╭───────◈───────╮
              │  ◌  ◉  ◌  ◉   │
              ╰───────◈───────╯
```
Animate the surrounding nodes moving around the center, 4–8 frames maximum.
Use cyan/blue for normal work and yellow for validation warnings.
Meaning: collecting, ordering, validating, and framing prompt/context blocks.

#### SlimToken optimization
Visual: wide context material entering from the left, compressed material
leaving on the right.
```text
   [████████████████]  →  ◈  →  [██████████]
   context before           optimized context
```
Animate a few blocks contracting toward the core. Display factual values when
available:
```text
   15.3k tokens  →  ◈  →  12.6k tokens
   saved 2.7k tokens (18.0%)
```
Use purple/magenta accent for actual SlimToken optimization. Do not animate it
when SlimToken is not active.

#### Sending / prefill
Visual: request packet flow toward the model core.
```text
   ◇ ──◇ ──◇ ──▶ [ ◈ MODEL ]
```
Animate packets moving toward the model. Use cyan/blue. Show real input
throughput when available:
```text
   Sending 12.6k input tokens · 842 tok/s
```

#### Generating response
Visual: output stream emerging from the core.
```text
   [ ◈ MODEL ] ──▶ ▌▍▎▏
```
Animate the output tail expanding and contracting or use a multi-cell waveform:
```text
   [ ◈ MODEL ] ──▶ ▁▃▆█▆▃▁
```
Use green for generated output and cyan for the model core. This must remain
**indeterminate** unless the application has a real completion estimate.
Show:
```text
Generating a response from the prepared context.
Output 47.6 tok/s · 384 tokens generated · Esc to stop
```

#### Tool waiting
Visual: a signal traveling between CortexAgent and a tool marker.
```text
   [ ◈ ] ── · · · ──▶ [ ⬡ TOOL ]
```
Animate the dots only. Use yellow. **Never** show tool arguments, raw command
output, tool payloads, or tool internals.

#### Completion
Visual: short one-time success burst:
```text
                ✦  ✓  ✦
             Request complete
```
Show for 800–1500 ms, then remove the entire progress panel in place and return
to normal input layout.

#### Error
Visual: static, not flashing:
```text
                !  ◈  !
          Request needs attention
```
Use red plus a concise safe message and actions:
```text
The model connection was interrupted before completion.
[Retry] [Open logs] [Dismiss]
```
Never flash red or rapidly animate error states.

### CortexAgent layout rules

- Reserve 5–7 rows only during active work; clear/reclaim the region after
  completion.
- The visual animation uses 2–3 rows maximum inside the card.
- Keep one user-facing status sentence.
- Keep one real progress/indeterminate row.
- Keep one concise metrics/action row.
- The card must update in place and never append animation frames to the
  transcript.
- Cap width at 72 terminal columns, but safely scale down:
  ```go
  panelWidth := min(72, terminalWidth-2)
  panelWidth = max(40, panelWidth)
  ```
- At 40–54 columns, use a simplified one-line animation:
  ```text
  ◈  ◌ ◉ ◌  Organizing context
  ```
- At less than 40 columns, use:
  ```text
  ◈ Working · 48%
  ```
- Use ANSI/Unicode display-width-aware layout.
- Never wrap.
- Use existing theme utilities; do not hardcode escape codes.

### CortexAgent animation settings

Add CortexAgent-only settings in its own configuration format:
```yaml
ui:
  progress:
    enabled: true
    style: cortex_core
    animation:
      enabled: true
      size: large
      frame_interval_ms: 180
      reduced_motion: auto
      show_stage_visuals: true
```
Requirements:
- `size`: `compact`, `normal`, `large`.
- **Default to `large`** for capable terminals, but auto-fallback to compact on
  narrow/short terminals.
- `reduced_motion: auto` respects system/app preference when possible.
- With reduced motion, render a static stage illustration rather than cycling
  frames.
- Preserve user overrides across config migration.

---

## Clawed animation design

Clawed must implement its own **entirely independent** visual identity. Do not
copy CortexAgent's "core/orbit/packet" frames or wording.

Use a larger **"Clawed activity"** animation near its input area, reserving
**4–6 terminal rows** during active work.

Suggested Clawed-specific visual language: a claw/paw, scanning reticle, or
moving signal trail.

### Example active state

```text
╭─ CLAWED / WORKING ────────────────────────────────────────────────╮
│                                                                    │
│                 ╲  ╱                                               │
│              ─── ◉ ───     scanning request                        │
│                 ╱  ╲                                               │
│                                                                    │
│ Reviewing available context.                                       │
│ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░ 42%   Preparing request                  │
│ 2 stages complete · Esc cancel                                     │
╰────────────────────────────────────────────────────────────────────╯
```

### Clawed animation modes (distinct from CortexAgent)

- Request preparation: scanning reticle / radar sweep.
- Context review: moving scan line across a compact block.
- Model request: signal beacon or segmented transmission line.
- Generation: growing text waveform or "claw marks" moving outward.
- Tool wait: static tool marker with a moving locator dot.
- Completion: short static/one-cycle confirmation symbol.
- Error: static alert state.

### Clawed requirements

- Build all frames, state mappings, colors, timings, and configuration inside
  Clawed only.
- Use Clawed's own theme/rendering architecture.
- Use a separate Clawed config section and independent setting names.
- Do not import CortexAgent animation/state/config code.
- Avoid copying the exact CortexAgent card design.
- Preserve the same privacy boundary: no thought traces, raw tools, code
  streams, prompts, or logs in normal mode.
- Final user-requested code remains visible only as final answer content.

---

## Shared UX safety expectations (without shared code)

Even though CortexAgent and Clawed remain fully separate implementations, both
must independently follow these product requirements:

- Never fake a determinate percentage.
- Use indeterminate animation for generation and unknown waits.
- Do not animate faster than is comfortable; target 150–250 ms frames.
- Do not flash more than three times per second.
- Provide reduced-motion mode.
- Do not append animation frames or progress messages to chat history.
- Animate only while work is active.
- Preserve an accessible textual status at all times.
- Use a fixed active-work region and clear it cleanly on completion.
- Keep debug logs, raw errors, traces, and technical details behind explicit
  opt-in controls.

---

## Exit / cleanup behavior (Ctrl+C) — CortexAgent

**Observed problem (2026-08-16):** Ctrl+C / normal exit leaves the long-running
model server (llama-server on :8080) alive and never kills the system tray.

**Current behavior:** `shutdown()` calls `runtimeHost.dispose()` +
`process.exit(0)` but does NOT kill the big model server or the tray. Only
`emergencyTerminalExit()` calls `killTrackedDetachedChildren()`.

**Design intent (from memory):** "CLI close kills big-only" — the big model
(~13.7GB VRAM) should be killed on CLI close to free VRAM, while the always-on
overseer systemd daemon stays.

**Decision needed:** Should Ctrl+C kill the big model server and/or the system
tray? Recommendation: kill the big model server (frees VRAM), leave the
always-on daemon and tray as independent apps. Implement a clean exit path that
kills the big model on Ctrl+C without killing the daemon/tray.

## Related

- 3D web UI plan (the full realization of this concept): `WEBUI-3D-PIPELINE.md`
