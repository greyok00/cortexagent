# Spatial UI — 4K Glass & Futuristic Design System

> Vision Pro / Holographic / Glass-style 3D control panel
> Frosted glass panels, volumetric glow, iridescent accents, depth-aware motion

---

## Design Language

### The Aesthetic

```
┌────────────────────────────────────────────────────────────┐
│  VISUAL PRINCIPLES                                         │
│                                                            │
│  1. Glass is everything                                     │
│     Frosted, translucent panels with real light bleeding     │
│     through edges and corners                                │
│                                                            │
│  2. Depth is the layout                                     │
│     Not left/right/center — but near/far, layer-by-layer     │
│     Each Z-position carries semantic meaning                 │
│                                                            │
│  3. Light is the content                                    │
│     Glow isn't an effect — it's information                  │
│     Active elements emit light                               │
│     Alerts pulse                                             │
│     Connections are visible beams                            │
│                                                            │
│  4. Motion is physical                                      │
│     Spring physics everywhere                                │
│     Panels float, drift, respond to "air"                    │
│     No linear easing — only spring, bounce, settle           │
│                                                            │
│  5. Typography is crisp at 4K                               │
│     Every pixel matters                                      │
│     Text rendered at native resolution                       │
│     No texture-mapped text — use real DOM or vector          │
│                                                            │
│  6. Color is luminous, not flat                             │
│     No solid fills — only gradients and glow                 │
│     Primary: electric blue → cyan → white                    │
│     Accent: purple → pink gradient                           │
│     Alert: amber → red                                         │
│     Success: green → teal                                      │
└────────────────────────────────────────────────────────────┘
```

---

## Visual Language System

### Glass Panels

```
┌─────────────────────────────────────────────────┐
│  GLASS PANEL SPECIFICATION                      │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  ┌─────────────────────────────────────┐  │  │
│  │  │  ╭───────────────────────────────╮  │  │  │
│  │  │  │  Panel Title            [×]  │  │  │  │
│  │  │  ╰───────────────────────────────╯  │  │  │
│  │  │                                    │  │  │
│  │  │   Frosted glass — light bleeds    │  │  │
│  │  │   through, background blurs       │  │  │
│  │  │   behind, subtle edge glow        │  │  │
│  │  │                                    │  │  │
│  │  │            ┌─────┐                  │  │  │
│  │  │            │ BTN │                  │  │  │
│  │  │            └─────┘                  │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  MATERIAL SPECS:                                │
│  ─────────────────                               │
│  Background:   rgba(255,255,255,0.06)          │
│  Border:       rgba(255,255,255,0.12)          │
│  Border glow:  rgba(255,255,255,0.04)          │
│  Shadow:       rgba(0,0,0,0.3) at 40px blur   │
│  Backdrop:     blur(24px) saturate(150%)       │
│  Inner glow:   inset 0 0 0.5px rgba(...)       │
│  Edge light:   top-left gradient (white 10%)  │
│  Drop shadow:  0 8px 32px rgba(0,0,0,0.35)    │
│  Border radius:20px (large), 12px (small)     │
└─────────────────────────────────────────────────┘
```

### Glass Shader (WebGL)

For the frosted glass panels rendered as 3D planes:

```glsl
// Fragment shader for frosted glass panel
precision highp float;

uniform sampler2D u_background;    // Scene rendered behind panel
uniform vec2 u_resolution;          // Screen resolution
uniform vec2 u_panelPos;           // Panel position
uniform vec2 u_panelSize;          // Panel dimensions
uniform float u_blurAmount;        // Blur intensity
uniform vec3 u_tint;               // Glass tint color
uniform float u_edgeGlow;          // Edge glow intensity
uniform float u_time;              // Time for subtle animation

varying vec2 v_uv;

void main() {
    // Panel bounds
    vec2 panelMin = u_panelPos - u_panelSize * 0.5;
    vec2 panelMax = u_panelPos + u_panelSize * 0.5;

    // Is this pixel inside the panel?
    vec2 localUV = (v_uv * u_resolution - panelMin) / u_panelSize;
    float insidePanel = step(panelMin.x, v_uv.x * u_resolution.x) *
                       step(panelMin.y, v_uv.y * u_resolution.y) *
                       step(v_uv.x * u_resolution.x, panelMax.x) *
                       step(v_uv.y * u_resolution.y, panelMax.y);

    // Sample background with offset-based blur (fake gaussian)
    vec4 bg = vec4(0.0);
    float samples = 0.0;
    for (float x = -4.0; x <= 4.0; x += 1.0) {
        for (float y = -4.0; y <= 4.0; y += 1.0) {
            vec2 offset = vec2(x, y) * u_blurAmount / u_resolution;
            bg += texture2D(u_background, v_uv + offset);
            samples += 1.0;
        }
    }
    bg /= samples;

    // Apply tint and transparency
    vec3 glass = bg.rgb * (1.0 - length(u_tint) * 0.3) + u_tint * 0.06;
    float glassAlpha = 0.06 + length(u_tint) * 0.02;

    // Edge detection — glow at panel boundaries
    vec2 pixelPos = v_uv * u_resolution;
    vec2 edgeDist = min(pixelPos - panelMin, panelMax - pixelPos);
    float edge = smoothstep(0.0, 8.0, edgeDist.x) * smoothstep(0.0, 8.0, edgeDist.y);
    float edgeAlpha = 1.0 - edge; // 1 at edges, 0 in center
    float edgeMask = step(0.0, v_uv.x * u_resolution.x - panelMin.x) *
                    step(0.0, v_uv.y * u_resolution.y - panelMin.y) *
                    step(v_uv.x * u_resolution.x, panelMax.x) *
                    step(v_uv.y * u_resolution.y, panelMax.y);
    float edgeGlow = edgeAlpha * edgeMask * u_edgeGlow;

    // Top-left edge light (simulated directional light)
    float topLeft = 1.0 - smoothstep(0.0, 1.0,
        (length(v_uv - vec2(0.0)) / length(v_uv - vec2(1.0))));
    float edgeLight = insidePanel * edgeGlow * 0.4 * topLeft;

    // Compose: scene behind → glass → edge glow
    vec3 color = mix(bg, glass, glassAlpha);
    color += edgeGlow * vec3(0.6, 0.8, 1.0); // Blue-ish edge glow
    color += edgeLight;

    // Alpha: fully opaque in center, slight transparency at edges
    float alpha = glassAlpha * edgeMask;

    gl_FragColor = vec4(color, alpha);
}
```

### Iridescent Accent

For the futuristic "holographic" feel:

```glsl
// Holographic accent shader — subtle rainbow shimmer
uniform float u_time;
uniform float u_intensity;

vec3 iridescent(vec2 uv, float shift) {
    // Shift RGB channels by different amounts based on angle
    float angle = atan(uv.y, uv.x);
    float shift_r = sin(angle * 2.0 + u_time * 2.0) * shift;
    float shift_g = sin(angle * 2.0 + u_time * 2.0 + 2.094) * shift;
    float shift_b = sin(angle * 2.0 + u_time * 2.0 + 4.189) * shift;

    return vec3(shift_r, shift_g, shift_b);
}
```

---

## Color System

### Palette

```
┌──────────────────────────────────────────────────────────┐
│  COLOR PALETTE                                           │
│                                                          │
│  BASE (Dark)                                             │
│  ─────────────                                           │
│  Void:        #05050a     — Scene background              │
│  Abyss:       #0a0a14     — Panel interior                │
│  Depth:       #0f0f1a     — Elevated surfaces             │
│  Shadow:      #141420     — Shadows, overlays             │
│  Mist:        rgba(255,255,255,0.04) — Glass base        │
│  Glass:       rgba(255,255,255,0.08) — Glass edge        │
│  Vapor:       rgba(255,255,255,0.06) — Subtle text       │
│  Frost:       rgba(255,255,255,0.12) — Borders, icons    │
│  Crystal:     rgba(255,255,255,0.7)  — Primary text      │
│  Diamond:     rgba(255,255,255,0.9)  — Headers, labels   │
│  White:       #ffffff                   — Highlights      │
│                                                          │
│  ACCENTS (Luminous)                                      │
│  ────────                                                │
│  Aurora:      #3b82f6 → #06b6d4 → #8b5cf6 — Primary      │
│  Ember:       #f59e0b → #ef4444   — Warnings             │
│  Prism:       #10b685 → #06b6d4   — Success              │
│  Nova:        #8b5cf6 → #ec4899   — Alerts, critical     │
│  Flux:        #f97316 → #eab308   — Active, processing   │
│  Echo:        #6366f1 → #3b82f6   — Selection, focus     │
│                                                          │
│  GRADIENTS                                               │
│  ────────                                                │
│  Dawn:        #0ea5e9 → #8b5cf6    — Panel headers       │
│  Horizon:     #06b6d4 → #3b82f6    — Buttons, links      │
│  Zenith:      #8b5cf6 → #ec4899    — Highlights          │
│  Aurora:      #10b685 → #06b6d4    — Success states      │
│  Nebula:      #6366f1 →#8b5cf6     — Active elements      │
│                                                          │
│  TEXTURE (Noise overlay — adds depth to glass)           │
│  ──────────────────────────────────────                  │
│  Grain: 0.5% white noise, opacity 0.03                   │
│  Applied as overlay blend on all glass surfaces          │
└──────────────────────────────────────────────────────────┘
```

### Typography

```
┌──────────────────────────────────────────────────────────┐
│  TYPOGRAPHY — 4K Native Rendering                        │
│                                                          │
│  Font Stack:                                             │
│  ──────────                                              │
│  Primary:   Inter (variable weight)                      │
│  Monospace:   JetBrains Mono (variable weight)           │
│  Display:     SF Pro Display (macOS native)              │
│                                                          │
│  Scale (4K optimized):                                   │
│  ─────                                                   │
│  Display XL:    48px / bold   — Hero titles              │
│  Display L:     32px / bold   — Page headers             │
│  Display M:     24px / bold   — Section headers          │
│  Heading:       20px / semibold — Card titles            │
│  Body L:        16px / regular — Large text, labels      │
│  Body M:        14px / regular — Default text            │
│  Body S:        12px / regular — Captions, meta          │
│  Mono:          14px / medium — Code, data, metrics      │
│  Nano:          10px / medium — Tags, badges             │
│                                                          │
│  Line Heights:                                           │
│  ─────                                                     │
│  Display:   1.1 (tight)                                  │
│  Heading:   1.2                                          │
│  Body:      1.5 (comfortable)                            │
│  Mono:      1.6 (readable)                               │
│                                                          │
│  Kerning:   +20 to +50 for display sizes                 │
│  Tracking:  +50 for captions and labels                  │
│                                                          │
│  Anti-aliasing:                                           │
│  ─────────────                                             │
│  Font smoothing: antialiased (not subpixel)              │
│  Canvas text:   use ImageBitmap for crisp rendering      │
│  WebGL text:    SDF (signed distance field) text         │
│  HTML overlay:  native anti-aliasing                     │
└──────────────────────────────────────────────────────────┘
```

---

## Post-Processing Effects

### Effect Stack

```
┌────────────────────────────────────────────────────────┐
│  POST-PROCESSING PIPELINE                               │
│                                                         │
│  1. Render Pass                                          │
│     Scene rendered at 4K resolution                     │
│     HDR tone mapping (ACES)                             │
│                                                         │
│  2. Bloom Pass                                          │
│     Threshold: 0.6 — Only bright elements bloom         │
│     Radius: 16px (soft, wide glow)                      │
│     Intensity: 0.4 — Subtle, not garish                 │
│                                                         │
│  3. Color Grading                                         │
│     Lift: -0.02 (slight dark tint)                      │
│     Gamma: 1.05 (slight warmth)                         │
│     Gain: +0.03 (lift highlights)                       │
│     Saturation: 0.95 (slightly muted, cinematic)        │
│                                                         │
│  4. Vignette                                            │
│     Strength: 0.3 — Darken edges subtly                  │
│     Center: 0.6 — Wide vignette                          │
│                                                         │
│  5. Chromatic Aberration (subtle)                       │
│     Amount: 0.001 — Only at screen edges                 │
│     Adds "lens" feel, not "VHS" feel                     │
│                                                         │
│  6. Film Grain                                            │
│     Strength: 0.02 — Almost invisible                    │
│     Adds organic texture to gradients                    │
│                                                         │
│  TOTAL: 6 passes, <3ms on mid GPU at 4K                │
└────────────────────────────────────────────────────────┘
```

### Bloom Configuration

```typescript
const bloom = {
  // Only things brighter than this emit glow
  threshold: 0.6,

  // How wide the glow spreads
  radius: 16,

  // How strong the glow is
  intensity: 0.4,

  // Only bloom once (no multi-bounce — too expensive)
  iterations: 1,

  // Bright elements that bloom:
  // - Active panel borders
  // - Alert pulses
  // - Connection beams
  // - Progress indicators
  // - Selection highlights
}
```

### Vignette & Film Grain

```glsl
// Vignette fragment shader
precision highp float;
uniform sampler2D u_texture;  // Scene texture
uniform vec2 u_resolution;     // Screen resolution
uniform float u_intensity;     // Vignette strength
uniform vec2 u_center;        // Vignette center

varying vec2 v_uv;

void main() {
    vec2 center = u_resolution * u_center;
    float dist = distance(v_uv * u_resolution, center);
    float vignette = smoothstep(
        u_resolution.x * 0.4,
        u_resolution.x * 0.05,
        dist * u_intensity
    );

    vec3 color = texture2D(u_texture, v_uv).rgb;
    // Apply vignette — darken
    color *= 1.0 - vignette * 0.5;

    // Film grain — subtle noise
    float grain = fract(sin(dot(v_uv * u_resolution, vec2(12.9898, 78.233))) * 0.02);
    color += grain - 0.01;

    // Subtle vignette color tint — slightly blue in shadows
    color = mix(color, color * vec3(0.85, 0.9, 1.0), vignette * 0.3);

    gl_FragColor = vec4(color, 1.0);
}
```

---

## Lighting Design

### Scene Lighting

```
┌────────────────────────────────────────────────────────┐
│  LIGHTING SETUP                                         │
│                                                         │
│  ┌──────────────────────────────────────────┐          │
│  │  Directional Light (top-left)             │          │
│  │  Color: #1a2a4a                            │          │
│  │  Intensity: 0.3                            │          │
│  │  Purpose: Simulates window light           │          │
│  └──────────────────────────────────────────┘          │
│                                                         │
│  ┌──────────────────────────────────────────┐          │
│  │  Ambient Light                            │          │
│  │  Color: #0a0a1a                            │          │
│  │  Intensity: 0.15                           │          │
│  │  Purpose: Base fill, prevents pure black   │          │
│  └──────────────────────────────────────────┘          │
│                                                         │
│  ┌──────────────────────────────────────────┐          │
│  │  Point Lights (panel-specific)            │          │
│  │  — Each active panel has a tiny point     │          │
│  │    light that contributes to bloom         │          │
│  │  Color: Panel accent color                 │          │
│  │  Intensity: 0.05-0.1 (very subtle)         │          │
│  │  Radius: 3-5 units                         │          │
│  └──────────────────────────────────────────┘          │
│                                                         │
│  ┌──────────────────────────────────────────┐          │
│  │  Environment Map                          │          │
│  │  Procedural gradient sky (dark blue)       │          │
│  │  Used for reflections on glass surfaces    │          │
│  │  Used for refraction in transmission       │          │
│  └──────────────────────────────────────────┘          │
└────────────────────────────────────────────────────────┘
```

---

## Panel Templates

### Template: Metrics Panel

```
┌──────────────────────────────────────────────┐
│  ╭───────────────────────────────────────╮   │
│  │  METRICS                       [—][×] │   │
│  │  ───────────────────────────────────   │   │
│  │                                        │   │
│  │  ┌──────────┐  ┌──────────┐           │   │
│  │  │ CPU      │  │ RAM      │           │   │
│  │  │ ██▓▓▓▓  │  │ ███▓▓▓   │           │   │
│  │  │ 67%      │  │ 4.2/8 GB │           │   │
│  │  └──────────┘  └──────────┘           │   │
│  │                                        │   │
│  │  ┌────────────────────────┐           │   │
│  │  │ Agents: 12 active      │           │   │
│  │  │ Seeds:  34 running     │           │   │
│  │  │ Budget: $247/mo       │           │   │
│  │  └────────────────────────┘           │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  GLASS SPECS:                                │
│  - Border: 1px rgba(255,255,255,0.08)        │
│  - Background: rgba(10,10,26,0.7)            │
│  - Backdrop blur: 20px                       │
│  - Shadow: 0 16px 48px rgba(0,0,0,0.4)       │
│  - Radius: 20px                              │
└──────────────────────────────────────────────┘
```

### Template: Seed Visualization Panel

```
┌──────────────────────────────────────────────┐
│  ╭───────────────────────────────────────╮   │
│  │  SEED GRAPH                    [—][×] │   │
│  │  ───────────────────────────────────   │   │
│  │                                        │   │
│  │    ┌────────┐                           │   │
│  │    │  TREE  │                           │   │
│  │    └──┬──┬──┘                           │   │
│  │  ┌──┐ │  └──┐                          │   │
│  │  │P │ │S   │S                          │   │
│  │  └──┘ │    │                          │   │
│  │   │    │    │                          │   │
│  │  ┌┴┐ ┌┴┐ ┌┴┐                           │   │
│  │  │S│ │S│ │P│  ← Seed nodes              │   │
│  │  └┬┘ └┬┘ └┬┘  (size = maturity)          │   │
│  │   │    │    │  Color = stage              │   │
│  │   └────┴────┘  Lines = relationships        │   │
│  │                                        │   │
│  │  [Filters: All | Active | Alert]       │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  GLASS SPECS:                                │
│  - Border: 1px rgba(59,130,246,0.2)         │
│  - Active border glow: 0 0 20px rgba(...)    │
│  - Background: rgba(10,10,26,0.6)            │
│  - Backdrop blur: 24px                       │
│  - Shadow: 0 16px 48px rgba(59,130,246,0.15) │
└──────────────────────────────────────────────┘
```

### Template: Alert Panel

```
┌──────────────────────────────────────────────┐
│  ╭───────────────────────────────────────╮   │
│  │  ⚡ ALERT                     [×]      │   │
│  │  ───────────────────────────────────   │   │
│  │                                        │   │
│  │  Budget ceiling approaching            │   │
│  │  Current: $247/mo (92%)               │   │
│  │                                        │   │
│  │  ┌──────────────────────────────┐      │   │
│  │  │████████████████░░░░░░░░░░░░░│      │   │
│  │  │   $247 / $267 per month      │      │   │
│  │  └──────────────────────────────┘      │   │
│  │                                        │   │
│  │  [Review Spend]  [Ignore]              │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  GLASS SPECS:                                │
│  - Border: 1px rgba(139,92,246,0.4)         │
│  - Border glow: 0 0 24px rgba(139,92,246,0.2)│
│  - Background: rgba(20,10,30,0.8)           │
│  - Pulsing animation: border glow 0.5s loop  │
│  - Shadow: 0 16px 48px rgba(139,92,246,0.2)  │
└──────────────────────────────────────────────┘
```

---

## Animation System

### Spring Constants for UI Motion

```
┌────────────────────────────────────────────────────────┐
│  SPRING TUNING GUIDE                                    │
│                                                         │
│  Panel Types:                                           │
│  ──────────                                             │
│  Small widget:     stiffness=150, damping=12, mass=0.8  │
│  Medium panel:     stiffness=120, damping=15, mass=1.0  │
│  Large panel:      stiffness=100, damping=12, mass=1.5  │
│  Modal/dialog:     stiffness=200, damping=8, mass=0.6   │
│  Alert:            stiffness=250, damping=10, mass=0.5  │
│                                                         │
│  Transitions:                                           │
│  ──────────                                             │
│  Space switch:     stiffness=80, damping=10, mass=1.2   │
│  Panel open/close: stiffness=120, damping=15, mass=1.0  │
│  Panel move:       stiffness=150, damping=12, mass=0.8  │
│  Camera orbit:     stiffness=60, damping=8, mass=2.0    │
│  Camera zoom:      stiffness=100, damping=12, mass=1.0  │
│                                                         │
│  Micro-interactions:                                      │
│  ──────────────────                                       │
│  Button hover:     stiffness=200, damping=10, mass=0.5  │
│  Button click:     stiffness=300, damping=15, mass=0.3  │
│  Checkbox:         stiffness=180, damping=12, mass=0.5  │
│  Toggle switch:    stiffness=220, damping=14, mass=0.6  │
│  Slider drag:      stiffness=250, damping=10, mass=0.4  │
│                                                         │
│  ENTRANCE ANIMATIONS:                                     │
│  ────────────────────                                     │
│  Slide-in:       From edge, overshoot, settle           │
│  Pop-in:         Scale from 0, bounce, settle           │
│  Fade-slide:     Opacity + position, no overshoot       │
│  Flip-in:        Rotate from Y-axis, settle            │
│  Cascade:        Staggered slide-in (50ms delay each)   │
│  Snap-in:        Immediate, no overshoot               │
│  Float-in:       Gentle drift from position             │
│                                                         │
│  EXIT ANIMATIONS:                                         │
│  ───────────────                                          │
│  Slide-out:      To edge, ease-out                     │
│  Shrink-out:     Scale to 0, fade out                  │
│  Fade-out:       Opacity only, no movement             │
│  Flip-out:       Rotate out on Y-axis                  │
│  Dissolve:       Random particles scatter              │
└────────────────────────────────────────────────────────┘
```

### Animation Examples

```
┌────────────────────────────────────────────────────────┐
│  ANIMATION: Space Transition                            │
│                                                         │
│  User clicks "Detail" in nav.                           │
│                                                         │
│  T+0.0s  — Space transition begins                      │
│           Current panels start animating to new         │
│           positions                                     │
│           Camera begins spring-driven move to new       │
│           position                                      │
│                                                         │
│  T+0.05s — Panel 2 starts (staggered)                   │
│  T+0.10s — Panel 3 starts (staggered)                   │
│           Background fog begins adjusting               │
│                                                         │
│  T+0.3s  — Camera reaches 80% of target position        │
│           Panels reach 70% of target positions          │
│                                                         │
│  T+0.5s  — Camera overshoots, settles back              │
│           Panels overshoot, settle back                 │
│                                                         │
│  T+0.8s  — All panels settled                           │
│           Transition complete                           │
│                                                         │
│  TOTAL: ~0.8s (subtle, not distracting)                 │
└────────────────────────────────────────────────────────┘
```

---

## 4K Rendering

### Resolution & Pixel Density

```
┌────────────────────────────────────────────────────────┐
│  4K RENDERING STRATEGY                                  │
│                                                         │
│  Canvas Resolution:                                     │
│  ──────────────────                                       │
│  Base canvas: 1920×1080 (logical pixels)               │
│  WebGL buffer: 3840×2160 (2× devicePixelRatio)          │
│  CSS display: 1920×1080 (stretches to 4K monitor)      │
│                                                         │
│  Text Rendering:                                        │
│  ─────────────                                            │
│  HTML text:   Native OS anti-aliasing (crisp at 4K)    │
│  Canvas text: Use ImageBitmap + high-res canvas        │
│  WebGL text:  SDF (Signed Distance Field) —              │
│               scalable, crisp at any distance/angle     │
│  3D labels:   CSS3DRenderer for text planes            │
│                                                         │
│  Performance Targets at 4K:                             │
│  ────────────────────────                                 │
│  GPU: NVIDIA RTX 3060 / Apple M2 or better             │
│  VRAM: 4GB minimum for 4K textures                     │
│  FPS: 60 with 20 panels, bloom, SSAO                   │
│  FPS: 30 with 50 panels, full effects                  │
│                                                         │
│  Adaptive Quality:                                      │
│  ──────────────────                                       │
│  Detect GPU tier → adjust effects automatically         │
│  Low:    No bloom, no SSAO, no chromatic aberration     │
│  Medium: Bloom + SSAO only                              │
│  High:   Full pipeline (6 passes)                       │
│  Ultra:  Full pipeline + temporal anti-aliasing        │
│                                                         │
│  Fallback:                                               │
│  ─────────                                                  │
│  If WebGL2 unavailable → degrade to CSS3DRenderer       │
│  If GPU < 2GB VRAM → reduce texture resolution by 50%   │
└────────────────────────────────────────────────────────┘
```

---

## Interaction Design

### Hover & Focus States

```
┌────────────────────────────────────────────────────────┐
│  HOVER STATE                                            │
│                                                         │
│  Normal panel:                                           │
│  border: 1px rgba(255,255,255,0.08)                     │
│  background: rgba(10,10,26,0.7)                         │
│                                                         │
│  Hover state (spring in 150ms):                          │
│  border: 1px rgba(255,255,255,0.15) — Brighter          │
│  box-shadow: 0 0 30px rgba(100,200,255,0.1) — Edge glow  │
│  transform: translateZ(4px) — Lift toward camera          │
│                                                         │
│  Active/click state:                                     │
│  transform: translateZ(8px) — More lift                  │
│  border: 1px rgba(100,200,255,0.3) — Blue edge           │
│  Background: rgba(10,10,26,0.8) — Slightly darker        │
│                                                         │
│  Selected state:                                         │
│  border: 1px rgba(99,102,241,0.5) — Indigo               │
│  box-shadow: 0 0 32px rgba(99,102,241,0.2) — Glow        │
│  Background: rgba(99,102,241,0.08) — Subtle tint         │
│                                                         │
│  Active/alert state:                                     │
│  border: 1px rgba(236,72,153,0.4) — Pink                 │
│  box-shadow: 0 0 40px rgba(236,72,153,0.3) — Pulsing     │
│  Animation: glow intensity oscillates 0.2-0.4, 2s loop   │
└────────────────────────────────────────────────────────┘
```

### Camera Controls

```
┌────────────────────────────────────────────────────────┐
│  CAMERA NAVIGATION                                      │
│                                                         │
│  Mouse:                                                  │
│  ────                                                   │
│  Scroll — Zoom in/out (spring-physics zoom)             │
│  Drag — Orbit around center                             │
│  Right-drag — Pan                                     │
│  Click on panel — Focus panel (camera moves to face it) │
│                                                         │
│  Keyboard:                                               │
│  ────────                                                 │
│  WASD — Pan camera                                      │
│  QE — Zoom in/out                                       │
│  R/F — Roll camera                                      │
│  1-9 — Jump to preset views                             │
│  Space — Reset camera to overview                       │
│  Ctrl+1 — Focus selected panel                          │
│                                                         │
│  Touch (tablet/phone):                                   │
│  ──────────────────────                                   │
│  One finger drag — Orbit                                │
│  Two finger drag — Pan                                  │
│  Pinch — Zoom                                           │
│  Tap — Select panel                                     │
│                                                         │
│  Vision Pro / Spatial:                                   │
│  ──────────────────────                                   │
│  Eye gaze — Hover panels (highlight)                    │
│  Pinch — Zoom in/out                                    │
│  Tap — Select panel                                     │
│  Gaze + hold — Grab/move panel                          │
│                                                         │
│  Camera presets:                                         │
│  ────────────────────                                     │
│  Overview — Wide angle, see all panels                  │
│  Detail — Zoom to single panel                          │
│  Focus — Camera faces selected panel head-on            │
│  Isometric — Angled top-down view                       │
│  Custom — User-defined free camera                      │
└────────────────────────────────────────────────────────┘
```

---

## File Structure

```
src/spatial-ui/
├── engine/
│   ├── renderer.ts       # WebGL + CSS3D hybrid renderer
│   ├── camera.ts         # Spring-driven camera controller
│   ├── scene.ts          # Scene setup, lighting, environment
│   ├── layers.ts         # Layer management (bg, panel, overlay)
│   └── postprocessing.ts # Bloom, vignette, color grading
├── glass/
│   ├── material.ts       # Glass material (WebGL shader)
│   ├── shader-fs.glsl    # Fragment shader
│   ├── shader-vs.glsl    # Vertex shader
│   └── env-map.ts        # Procedural environment map
├── panels/
│   ├── manager.ts        # Panel lifecycle
│   ├── panel.ts          # Panel base class
│   ├── metrics.ts        # Metrics panel component
│   ├── graph.ts          # Seed graph panel
│   ├── alert.ts          # Alert panel component
│   ├── template.ts       # Panel template system
│   └── html.ts           # HTML overlay panel wrapper
├── animation/
│   ├── spring.ts         # Spring physics engine
│   ├── transitions.ts    # Space transitions
│   ├── entrance.ts       # Entrance animations
│   ├── micro.ts          # Micro-interactions
│   └── timeline.ts       # Sequenced animations
├── ui/
│   ├── typography.ts     # Text rendering (SDF, HTML)
│   ├── icons.ts          # Vector icons in 3D
│   ├── charts.ts         # Data visualization
│   ├── buttons.ts        # 3D buttons
│   └── sliders.ts        # 3D sliders
├── interaction/
│   ├── pointer.ts        # Mouse/touch/eye tracking
│   ├── keyboard.ts       # Keyboard shortcuts
│   ├── gestures.ts       # Hand/spatial gestures
│   └── hover.ts          # Hover detection + states
├── data/
│   ├── spaces.ts         # Space definitions
│   ├── layouts.ts        # Layout definitions
│   └── themes.ts         # Theme/color definitions
└── index.ts              # Public API
```

---

## Quick Reference: Building a Glass Panel

```typescript
// 1. Create glass material
const glassMat = new THREE.ShaderMaterial({
  uniforms: {
    u_background: { value: null },
    u_resolution: { value: new THREE.Vector2(width, height) },
    u_panelPos: { value: new THREE.Vector2(0, 0) },
    u_panelSize: { value: new THREE.Vector2(4, 3) },
    u_blurAmount: { value: 2.0 },
    u_tint: { value: new THREE.Vector3(0.2, 0.3, 0.5) },
    u_edgeGlow: { value: 0.5 },
    u_time: { value: 0 }
  },
  vertexShader: /* vertex shader */,
  fragmentShader: /* fragment shader */,
  transparent: true,
  side: THREE.DoubleSide
})

// 2. Create panel geometry
const geometry = new THREE.PlaneGeometry(4, 3)
const panel = new THREE.Mesh(geometry, glassMat)
panel.position.set(0, 0, 0)
scene.add(panel)

// 3. Add to spring animation system
const spring = new Spring(panel.position, new THREE.Vector3(0, 0, 2))
spring.animateTo(targetPosition)

// 4. Add to layer system
ui.layers.panelLayer.add(panel)

// 5. Register for interaction
ui.interaction.register(panel, {
  onClick: () => panel.onClick(),
  onHover: () => panel.onHover(),
  onUnhover: () => panel.onUnhover()
})
```

---

## Summary: The Vision

```
┌────────────────────────────────────────────────────────┐
│  THE FINAL PRODUCT                                      │
│                                                         │
│  A 3D control panel that feels like looking through     │
│  a glass screen in a dark room.                       │
│                                                         │
│  Panels float in space, frosted glass with light        │
│  bleeding through edges. They respond to your gaze      │
│  with subtle glow. When you switch views, everything    │
│  slides and rotates with physical weight — not           │
│  linear motion, but spring-driven motion with           │
│  overshoot and settle.                                  │
│                                                         │
│  The background is a deep void with faint particles      │
│  drifting like stars. Connection lines between           │
│  panels glow when active. Alerts pulse with soft          │
│  light. Everything has depth. Everything has motion.     │
│                                                         │
│  Text is crisp at 4K. Buttons feel physical.             │
│  Transitions feel inevitable.                           │
│                                                         │
│  It's not a dashboard. It's an experience.              │
└────────────────────────────────────────────────────────┘
```

