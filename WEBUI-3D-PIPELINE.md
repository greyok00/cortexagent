# Web UI — 3D Pipeline Visualization (THE new web UI)

> **IMPORTANT — canonical reference.** Any mention of "the web UI" in this
> project refers to THIS document. This is the new web UI. It is a **fully 3D
> interpretation of the CortexAgent pipelines** — not a traditional dashboard.

**Status:** 🎨 DESIGNED · ⏳ NOT YET BUILT (saved on request, 2026-08-16)

---

## What it is

A fully 3D, animated visualization of the prompt-processing pipeline. Instead
of a flat web dashboard, the user watches their prompt physically move through
the stages of the chain in 3D space.

## Core experience

- **Shows your prompt** as a 3D object/entity.
- **Animates it through the pipeline stages** — it slowly moves from stage to
  stage (e.g. "Stage 2"), visibly transforming as it goes.
- **Shows what the prompt is doing** at each stage.
- **Cool logos / stage icons** — each stage has a distinct visual identity.
- **Reframing animation** — e.g. when the prompt is "reframed for business,"
  the visual changes to reflect that.
- **Flashing keywords** — the keywords being extracted light up / flash as the
  pipeline processes them.
- **Speed selection slider** — the user controls how fast the animation runs.
- Everything is **cool-looking and animated**, not a static table.

## Pipeline stages to visualize (the chain)

1. **Prompt** (input)
2. **SlimToken minify / compression**
3. **Frame-of-reference** (reframing — e.g. business framing)
4. **Domain-database memory check** (CortexLLM memory)
5. **Overseer routing**
6. **Big-model generation** (output)

## Design principles

- Fully 3D (Three.js or similar), not a flat dashboard.
- Animated, expressive, "cool."
- Speed slider to control animation pace.
- Shows real pipeline data (the actual prompt, actual keywords, actual stages).
- Replaces the current web UI entirely.

## Related

- Animation spec (CortexAgent + Clawed): `docs/ANIMATION-SPEC.md`
- This is the destination for the "Cortex processing core" animation concept —
  the TUI animation is the 2D precursor; this is the full 3D realization.
