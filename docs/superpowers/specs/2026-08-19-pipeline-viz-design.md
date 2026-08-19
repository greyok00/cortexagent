# Pipeline Viz — Molten-Gold 3D Journey (Design)

**Date:** 2026-08-19
**Status:** ✅ APPROVED (user sign-off) · ⏳ NOT YET BUILT
**Canonical anchor:** `WEBUI-3D-PIPELINE.md` ("THE new web UI")
**Scope:** **UI only.** No backend changes. The live-data feed reads existing
8093 endpoints; nothing on the server side is modified.

---

## 1. What it is

A fully-3D, cinematic visualization of the CortexAgent prompt-processing
pipeline. A single **molten-gold prompt entity** physically travels a path
through **6 stage nodes**, visibly transforming at each one. It replaces the
current 10-stage gyroscope (`pipeline-viz.html`) entirely.

The user's aesthetic requirement is a **glowing molten-lava / liquid-gold**
look — high-quality and cinematic, **never "8-bit"** (no flat boxes, no cheap
primitive effects, no flat color gradients).

## 2. The experience (what it does)

### 2.1 The 6 stages (from the canonical spec)

| # | Stage | What happens to the entity |
|---|-------|------------------------------|
| 1 | **Prompt** | The raw prompt materializes as a molten-gold mass |
| 2 | **SlimToken minify** | It compresses — shrinks, densifies, glows hotter |
| 3 | **Frame-of-reference** | Reframing animation — the visual *changes* (e.g. shifts to "business" framing) |
| 4 | **Memory check** | Keywords being extracted **flash** as it's matched against memory |
| 5 | **Overseer routing** | It forks/splits toward the chosen model |
| 6 | **Big-model generation** | It blooms into the final answer |

### 2.2 The anti-strip guarantee (HARD requirement)

The user explicitly rejected a linear strip ("shitty strip going one-to-next").
This is **camera-driven**, not a fixed wide shot watching a dot orbit:

- The camera **dollies/arcs to each stage** as the entity arrives — an
  establishing shot per stage.
- At each node the entity **transforms, doesn't slide**: color shifts through
  a blackbody ramp, shape morphs, keywords flash. The transformation is the
  event; the travel is connective tissue.
- Stage nodes are **landmarks with identity** (own glow + icon + halo that
  activates on arrival), not tick marks.

### 2.3 Controls

- **Speed slider** (from the canonical spec) — user controls animation pace.
- **Live-when-busy, cinematic-when-idle** (user decision): reflects real
  pipeline activity from 8093 when there is any; falls back to the scripted
  journey when idle.

## 3. The molten-gold aesthetic (what it's capable of)

Research finding #1: **metals have no diffuse color — their entire appearance
comes from the environment map.** This is why the current gold dots read as
flat. The 8 highest-leverage techniques, in priority order:

| # | Technique | Why it matters |
|---|-----------|----------------|
| 1 | **PMREM environment map** | Metals are 100% reflection; without a good envMap nothing else matters. `pmrem.fromScene(new RoomEnvironment(), 0.04)` or an HDR equirect. |
| 2 | **`onBeforeCompile` noise displacement** on a PBR material | Keeps real reflections + tone mapping while the surface churns. A raw `ShaderMaterial` throws away envMap/tone mapping — the "8-bit" trap. |
| 3 | **`clearcoat` + low `clearcoatRoughness` + `iridescence`** | The wet/molten sheen that sells "liquid" over "solid gold". |
| 4 | **Temperature-driven blackbody ramp** (white-hot → gold → deep orange → dark) with `smoothstep` banding | Kills the flat-gradient cheap tell. |
| 5 | **Selective bloom** (emissive > 1.0, `UnrealBloomPass` threshold ~1.0) | The cinematic glow. |
| 6 | **Multi-layer scrolling noise** (2+ layers, different directions/speeds) | Kills the "repetitive scrolling texture" fake look. |
| 7 | **Additive ember particles** (`InstancedMesh`, soft sprite, `depthWrite:false`) | Secondary VFX that sells realism. |
| 8 | **Cinematic camera + staged transitions** | The journey, not the strip. |

### 3.1 In-scene prompt text

- **troika-three-text** (SDF) rendered *inside* the 3D world — occluded by
  geometry, affected by bloom. Not a flat HTML overlay.
- **Perlin-dissolve gold-dust transition** between stages: the prompt text
  dissolves into gold dust and re-forms (Codrops "Gommage" pattern, adapted to
  WebGL2 via `onBeforeCompile`).
- **Font bundled locally** — troika's runtime CDN fetch fails silently in
  air-gapped setups (known trap). `configureTextBuilder({ useWorker:false })`
  if CSP blocks workers.

### 3.2 Path following

- `CatmullRomCurve3` with **`getPointAt(t)`** (arc-length, uniform speed), not
  `getPoint(t)`. Orient with `getTangentAt(t)`; bank via a Frenet–Serret frame.

## 4. Live-data integration (secondary)

- **SSE** (matches existing `pipeline-server.py` / webui SSE) or **polling**
  (~1–2s) for tokens/sec + prompt data from 8093.
- **Update state outside the render loop; draw inside it.** The SSE/polling
  handler writes to a state object; `animate()` only reads current state.
- O(1) lookup via a `Map` of id→object; reuse a `Float32Array` ring buffer +
  `needsUpdate`; shared material set. No per-frame network work.

## 5. Performance budget (60fps on consumer hardware)

| Resource | Budget |
|----------|--------|
| Draw calls | < 100 |
| Ember particles | 2,000–5,000 (1 `InstancedMesh` draw call) |
| Pixel ratio | ≤ 2 (1.5 on mobile) — biggest 4K saver |
| Noise octaves | 4–6 |
| Displacement tessellation | `IcosahedronGeometry(1, 6)` / `SphereGeometry(1, 128)` |
| Loop allocations | 0 (reuse Vector3/Matrix4, object pool) |

- `ACESFilmicToneMapping` + `toneMappingExposure ≈ 1.0–1.2`.
- **`OutputPass` is required in r152+** for tone mapping + sRGB. Composer
  order: `RenderPass → UnrealBloomPass → OutputPass`. No `GammaCorrectionShader`
  after `OutputPass`.

## 6. Scope boundaries

- **INCLUDE:** the 6-stage molten-gold journey, camera-driven staging, in-scene
  SDF prompt text with gold-dust dissolve, speed slider, live-when-busy /
  cinematic-when-idle, ember particles, bloom, environment map.
- **EXCLUDE:** any backend/server changes; any flat 2D dashboard panels; the
  current 10-stage gyroscope; any "8-bit" primitive effects.
- **CONSTRAINTS:** localhost-only binding (127.0.0.1:8090); pure 3D (no flat
  DOM overlay panels); smooth 60fps; no personal data leaks.

## 7. Definition of done

- The 6-stage journey renders as molten-gold (envMap + displacement + clearcoat
  + blackbody ramp + bloom), not flat gold dots.
- The camera dollies/arcs per stage; the entity transforms (not slides) at each
  node; keywords flash at memory-check.
- In-scene prompt text dissolves into gold dust between stages (font bundled
  locally, no CDN dependency).
- Speed slider works; live-when-busy / cinematic-when-idle both function.
- Zero console errors; smooth 60fps; < 100 draw calls.
- Verified live in the browser (text-only, no screenshots to the model).

## 8. Related

- `WEBUI-3D-PIPELINE.md` — the canonical spec this implements.
- `docs/ANIMATION-SPEC.md` — the TUI 2D precursor (separate).
- Research synthesis: `pipeline-viz-molten-lava-research.md` (memory).
