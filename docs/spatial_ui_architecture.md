# Spatial UI — 2D Panels in 3D Space

> Custom-built system for rendering 2D UI elements as floating, animated planes in a 3D scene.
> Each panel is a 2D surface positioned, rotated, and animated in 3D space.
> Transitions between "spaces" use spring physics for natural motion.

---

## The Concept

Imagine your control panel as a **3D world** where UI elements are flat planes floating in space.
- Panels **slide** between states (open/close/panel-switch)
- Panels **rotate** to face you as you orbit
- Spaces **transition** with camera + panel animations
- Layers **separate** depth-wise (background → panels → overlays)
- Everything is **2D content** — text, buttons, charts — but positioned in 3D

This gives you the **usability of 2D UI** with the **depth and motion of 3D**.

---

## Core Principles

1. **2D content, 3D positioning** — Panels are flat rectangles with HTML/canvas content, placed in 3D space
2. **State-driven layout** — Every panel has named positions/states; transitions interpolate between them
3. **Spring physics** — Natural, physical motion. No linear tweens.
4. **Layered depth** — Background layer, panel layer, overlay layer — each with its own depth offset
5. **Pointer events in 3D** — Raycast from screen click → 3D plane → find panel → trigger action
6. **Camera as context** — Zoom/pan changes scale; orbit changes perspective; transitions animate camera + panels together

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  SPATIAL UI LAYERS                                       │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  OVERLAY LAYER (z = +2 to +10)               │        │
│  │  - Modals, dialogs, tooltips                  │        │
│  │  - Always-front, always-facing camera         │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  PANEL LAYER (z = 0 to +2)                   │        │
│  │  - Main dashboard panels                      │        │
│  │  - Data visualizations                        │        │
│  │  - Controls & forms                           │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  BACKGROUND LAYER (z = -10 to -2)            │        │
│  │  - Particle effects                           │        │
│  │  - Grid floor                                 │        │
│  │  - Ambient lighting                           │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │  CAMERA                                      │        │
│  │  - Perspective camera with spring-driven      │        │
│  │    position/rotation                          │        │
│  └──────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

---

## Two Rendering Approaches

### Approach A: CSS3DRenderer (Recommended for most use)

Render actual HTML elements in 3D space using CSS transforms.

```
┌──────────────────────────────────────────────┐
│ WebGL Renderer (background, particles)       │
│ └── CSS3DRenderer (HTML panels)              │
└──────────────────────────────────────────────┘
```

**How it works:**
```jsx
import { CSS3DRenderer, CSS3DObject } from 'three/examples/jsm/renderers/CSS3DRenderer'

// Each panel is an actual DOM element positioned in 3D
const panel = document.createElement('div')
panel.className = 'ui-panel'
panel.innerHTML = '<button>Click me</button><h3>Panel Title</h3>'

const cssObject = new CSS3DObject(panel)
cssObject.position.set(0, 0, 0)  // 3D position
cssObject.rotation.set(0, 0, 0)  // 3D rotation
scene.add(cssObject)
```

**Pros:**
- Native HTML — full accessibility, keyboard nav, ARIA
- Text is crisp (browser-rendered, not texture-mapped)
- Works with any CSS framework (Tailwind, Radix, custom)
- Forms, inputs, selects work natively
- Smooth GPU-accelerated CSS transforms
- No texture update overhead

**Cons:**
- DOM elements always render "front-facing" (billboarded) — can't see panel edges
- Z-ordering issues when panels overlap
- Limited to CSS-transformable content (no WebGL textures on panels)
- Performance degrades with many complex DOM elements
- Cannot be post-processed (CSS3D output is separate from WebGL)

### Approach B: WebGL Planes with Canvas Textures

Render 2D content to off-screen `<canvas>`, then use that as a texture on a 3D plane.

```
┌──────────────────────────────────────┐
│ WebGL Renderer                        │
│ └── PlaneGeometry + canvasTexture    │
└──────────────────────────────────────┘
```

**How it works:**
```jsx
// Off-screen canvas for panel content
const canvas = document.createElement('canvas')
canvas.width = 512
canvas.height = 512
const ctx = canvas.getContext('2d')

// Draw 2D UI onto canvas
ctx.fillStyle = '#1a1a2e'
ctx.fillRect(0, 0, 512, 512)
ctx.fillStyle = '#ffffff'
ctx.font = '16px Inter'
ctx.fillText('Panel Title', 24, 48)

// Use as texture on plane
const texture = new THREE.CanvasTexture(canvas)
const plane = new THREE.Mesh(
  new THREE.PlaneGeometry(2, 2),
  new THREE.MeshBasicMaterial({ map: texture })
)
plane.position.set(0, 0, 0)
scene.add(plane)

// Update on change
function redraw() {
  ctx.clearRect(0, 0, 512, 512)
  // redraw UI...
  texture.needsUpdate = true
}
```

**Pros:**
- Full 3D control — panels rotate, bend, distort
- Can be post-processed with bloom, blur, etc.
- Better performance for many panels (single draw call)
- True perspective — you see panel edges when rotated
- Can mix with WebGL content seamlessly

**Cons:**
- No native HTML — must draw everything manually
- Text rendering requires manual layout engine
- Input/click handling must be custom
- Canvas resolution limits (need high-res for crisp text)
- No keyboard nav, no ARIA, no accessibility

### Approach C: Hybrid (Best of Both Worlds)

Use CSS3DRenderer for interactive panels (forms, buttons, text), and WebGL planes for data visualizations (charts, graphs, particles).

```
┌──────────────────────────────────────┐
│ WebGL Renderer                       │
│ ├─ Background particles              │
│ ├─ Data visualization planes         │
│ └─ Grid floor                        │
│                                      │
│ └── CSS3DRenderer (overlay)          │
│    ├─ Main dashboard panels          │
│    ├─ Modal dialogs                  │
│    └─ Tooltip overlays               │
└──────────────────────────────────────┘
```

---

## Panel System Design

### Panel Definition

```typescript
interface Panel {
  id: string
  title: string
  // Content is a React component or HTML string
  content: React.ComponentType<PanelProps> | string
  // Named positions the panel can occupy
  layout: Record<string, PanelPosition>
  // Current state
  state: PanelState
  // Animation configuration
  spring?: SpringConfig
  // Layer ordering
  order: number
  // Interaction
  interactive: boolean
  closable: boolean
  // Visual
  size?: { width: number; height: number }
  borderRadius?: number
  shadow?: boolean
  border?: boolean
}

interface PanelPosition {
  position: [x: number, y: number, z: number]
  rotation: [x: number, y: number, z: number]
  scale: number
}

interface SpringConfig {
  stiffness: number    // How much the panel "wants" to reach target
  damping: number      // How quickly motion settles
  mass: number         // Panel "weight"
  velocity?: number    // Initial velocity
}
```

### Layout System

Panels have named positions — not absolute coordinates. This makes transitions declarative:

```typescript
const layout = {
  // Default: single panel, centered
  default: {
    panel1: {
      position: [0, 0, 0],
      rotation: [0, 0, 0],
      scale: 1
    }
  },
  // Two panels side by side
  'side-by-side': {
    panel1: {
      position: [-2.5, 0.5, 0],
      rotation: [0, 0, 0],
      scale: 0.8
    },
    panel2: {
      position: [2.5, 0.5, 0],
      rotation: [0, 0, 0],
      scale: 0.8
    }
  },
  // Three panels in a triangle
  'triad': {
    panel1: {
      position: [0, 2, -1],
      rotation: [-0.2, 0, 0],
      scale: 0.7
    },
    panel2: {
      position: [-2.5, -1, -1],
      rotation: [0.1, 0.15, 0],
      scale: 0.7
    },
    panel3: {
      position: [2.5, -1, -1],
      rotation: [0.1, -0.15, 0],
      scale: 0.7
    }
  }
}
```

### Transition System

Transitions interpolate between states using spring physics:

```
Transition:
  FROM: { position: [0,0,0], rotation: [0,0,0], scale: 1 }
  TO:   { position: [-2.5,0.5,0], rotation: [0,0,0], scale: 0.8 }

Spring physics solves:
  acceleration = stiffness × (target - current) - damping × velocity
  velocity += acceleration × dt
  current += velocity × dt

Result: natural overshoot + settle, like a physical panel sliding into place
```

---

## Spring Physics Implementation

From first principles — no external library needed:

```typescript
class Spring {
  constructor(
    public target: number = 0,
    public position: number = 0,
    public velocity: number = 0,
    public stiffness: number = 120,
    public damping: number = 15,
    public mass: number = 1
  ) {}

  setTarget(target: number): void {
    this.target = target
  }

  update(dt: number): void {
    // Spring force
    const displacement = this.position - this.target
    const springForce = -this.stiffness * displacement
    // Damping force
    const dampingForce = -this.damping * this.velocity
    // Acceleration
    const acceleration = (springForce + dampingForce) / this.mass
    // Integrate
    this.velocity += acceleration * dt
    this.position += this.velocity * dt
  }

  get settled(): boolean {
    return Math.abs(this.position - this.target) < 0.001 &&
           Math.abs(this.velocity) < 0.001
  }

  // Convenience: lerp to target (no overshoot)
  static lerp(current: number, target: number, t: number): number {
    return current + (target - current) * t
  }
}

// Batch of springs for multi-dimensional animation
class Spring3D {
  x: Spring
  y: Spring
  z: Spring
  rx: Spring
  ry: Spring
  rz: Spring
  scale: Spring

  constructor() {
    this.x = new Spring(0)
    this.y = new Spring(0)
    this.z = new Spring(0)
    this.rx = new Spring(0)
    this.ry = new Spring(0)
    this.rz = new Spring(0)
    this.scale = new Spring(1)
  }

  animateTo(pos: [number, number, number], rot: [number, number, number], scl: number): void {
    this.x.setTarget(pos[0])
    this.y.setTarget(pos[1])
    this.z.setTarget(pos[2])
    this.rx.setTarget(rot[0])
    this.ry.setTarget(rot[1])
    this.rz.setTarget(rot[2])
    this.scale.setTarget(scl)
  }

  update(dt: number): void {
    this.x.update(dt); this.y.update(dt); this.z.update(dt)
    this.rx.update(dt); this.ry.update(dt); this.rz.update(dt)
    this.scale.update(dt)
  }
}
```

### Tuning Guide

| Motion Type | Stiffness | Damping | Mass | Feel |
|-------------|-----------|---------|------|------|
| **Slide in** | 80 | 12 | 1 | Smooth, controlled |
| **Bounce pop** | 200 | 8 | 0.8 | Energetic, playful |
| **Snap** | 300 | 20 | 0.5 | Crisp, immediate |
| **Float drift** | 40 | 8 | 1.5 | Gentle, ethereal |
| **Heavy panel** | 150 | 18 | 2.0 | Substantial, weighty |

---

## Space Transitions

A "space" is a named layout configuration. Transitions animate camera + all panels together:

```typescript
interface Space {
  name: string
  panels: Record<string, PanelDefinition>
  camera: {
    position: [x, y, z]
    target: [x, y, z]  // Look-at target
    fov: number
  }
  background: {
    color: string
    fogNear: number
    fogFar: number
    ambientIntensity: number
  }
  transition: {
    duration: number    // Seconds for camera to move
    easing: 'spring' | 'smooth' | 'instant'
  }
}
```

### Example Spaces

```typescript
const spaces: Record<string, Space> = {
  overview: {
    name: 'Overview',
    panels: {
      'seed-graph': {
        layout: 'side-by-side',
        position: 'panel1'  // Full width, centered
      },
      'metrics': {
        layout: 'side-by-side',
        position: 'panel2'  // Small, top-right
      },
      'activity': {
        layout: 'default',
        position: 'hidden'  // Off-screen
      }
    },
    camera: {
      position: [0, 3, 8],
      target: [0, 0, 0],
      fov: 50
    },
    background: {
      color: '#0a0a1a',
      fogNear: 5,
      fogFar: 20,
      ambientIntensity: 0.4
    },
    transition: { duration: 1.2, easing: 'spring' }
  },

  detail: {
    name: 'Detail View',
    panels: {
      'seed-graph': {
        layout: 'default',
        position: 'hidden'
      },
      'metrics': {
        layout: 'default',
        position: 'hidden'
      },
      'activity': {
        layout: 'default',
        position: 'visible'  // Full panel, front and center
      }
    },
    camera: {
      position: [0, 1, 4],
      target: [0, 0, -1],
      fov: 35
    },
    background: {
      color: '#0a0a1a',
      fogNear: 3,
      fogFar: 15,
      ambientIntensity: 0.6
    },
    transition: { duration: 1.0, easing: 'spring' }
  }
}
```

### Transition Animation Steps

```
When transitioning from space A → space B:

1. Calculate delta for each panel:
   delta.position = B.panel.position - A.panel.position
   delta.rotation = B.panel.rotation - A.panel.rotation
   delta.scale = B.panel.scale / A.panel.scale

2. Animate camera:
   camera.position lerps from A.camera.position → B.camera.position
   camera.target lerps from A.camera.target → B.camera.target
   camera.fov eases from A.camera.fov → B.camera.fov

3. Animate background:
   scene.fog.near eases from A.fogNear → B.fogNear
   scene.fog.far eases from A.fogFar → B.fogFar
   scene.background.color lerp

4. Animate panels:
   Each panel uses its own spring physics for position/rotation/scale
   Staggered: panels don't all start at the same time
   Stagger offset: index × 0.05s (panels enter sequentially)

5. Panel lifecycle:
   - Panels going to "hidden": animate to off-screen position, then unmount
   - Panels appearing: mount off-screen, animate to position
   - Panels staying: just adjust position/rotation/scale
```

---

## Interaction Model

### 3D Pointer → Panel Mapping

```typescript
// Raycaster from camera through mouse position
function handleClick(event: MouseEvent): void {
  const mouse = new THREE.Vector2(
    (event.clientX / window.innerWidth) * 2 - 1,  // -1 to 1
    -(event.clientY / window.innerHeight) * 2 + 1
  )

  const raycaster = new THREE.Raycaster()
  raycaster.setFromCamera(mouse, camera)

  // Test against all panel planes
  const intersects = raycaster.intersectObjects(panelMeshes, true)

  if (intersects.length > 0) {
    const hit = intersects[0].object
    const panel = findPanelByMesh(hit.object)

    if (panel && panel.interactive) {
      // Dispatch click through the actual HTML element
      // (for CSS3DRenderer) or trigger panel action (for WebGL)
      panel.dispatchClick(intersects[0].point)
    }
  }
}
```

### CSS3DRenderer Interaction (Simpler)

With CSS3DRenderer, DOM elements receive native pointer events:

```jsx
// Each panel is a real DOM element
<div
  className="css-panel"
  style={{
    transform: `translate3d(${x}px, ${y}px, ${z}px) rotateX(${rx}deg) rotateY(${ry}deg) scale(${scale})`,
  }}
  onClick={() => panel.onClick()}
  onPointerMove={(e) => {
    // Hover detection is automatic via CSS
    e.target.style.filter = 'brightness(1.1)'
  }}
>
  {/* Actual HTML content */}
</div>
```

### WebGL Plane Interaction

For canvas-texture panels, use a hit-testing system:

```typescript
// Maintain a mapping from mesh → panel
const panelMap = new Map<THREE.Object3D, Panel>()

// On click, raycast, look up panel in map
raycaster.intersectObjects(scene.children).forEach(hit => {
  const panel = panelMap.get(hit.object)
  // Calculate local UV coordinates for sub-panel clicking
  const { u, v } = hit.uvs[0]
  panel.dispatchClickAt(u, v)  // Dispatch to HTML canvas at that point
})
```

---

## Performance Optimization

### Rendering
- **CSS3DRenderer** — Use `will-change: transform` on panels
- **WebGL planes** — Batch canvas textures into a sprite atlas
- **Frustum culling** — Hide panels outside camera view
- **LOD** — Lower-res canvas textures for distant panels

### Animation
- **Throttle updates** — Only call `spring.update()` when panel is in view
- **Skip settled springs** — Don't update springs that are within 0.001 of target
- **Batch DOM writes** — Group all CSS3D transform updates in one rAF callback
- **Use `transform3d`** — Forces GPU compositing, avoids layout/paint

### Memory
- **Pool panel objects** — Reuse DOM elements for panels that hide/show
- **Defer canvas rendering** — Don't redraw canvases when not visible
- **Limit active panels** — Max panels in a space; others unmount

---

## Code Structure

```
src/
├── spatial-ui/
│   ├── engine/
│   │   ├── spring.ts          # Spring physics implementation
│   │   ├── scene.ts           # Scene setup (renderer, camera, lighting)
│   │   ├── layers.ts          # Layer management (background, panel, overlay)
│   │   └── space.ts           # Space/scene definitions + transitions
│   ├── panels/
│   │   ├── manager.ts         # Panel lifecycle (create, show, hide, destroy)
│   │   ├── layout.ts          # Layout system (positions, transitions)
│   │   ├── renderer-css.ts    # CSS3DRenderer panel renderer
│   │   └── renderer-webgl.ts  # WebGL plane panel renderer
│   ├── interaction/
│   │   ├── pointer.ts         # Pointer → 3D raycasting
│   │   ├── keyboard.ts        # Keyboard shortcuts
│   │   └── gestures.ts        # Touch/swipe gestures for camera orbit
│   ├── animation/
│   │   ├── transitions.ts     # Space transition animations
│   │   ├── easing.ts          # Easing functions (spring, smooth, bounce)
│   │   └── timeline.ts        # Sequenced multi-step animations
│   └── index.ts               # Public API
```

### Public API

```typescript
import { SpatialUI } from './spatial-ui'

const ui = new SpatialUI({
  container: document.getElementById('app'),
  renderer: 'css3d',        // 'css3d' | 'webgl' | 'hybrid'
  camera: { fov: 50 },
  spring: { stiffness: 120, damping: 15 }
})

// Define spaces
ui.defineSpace('overview', {
  camera: { position: [0, 3, 8], fov: 50 },
  panels: {
    'dashboard': { type: 'html', layout: 'center' },
    'metrics': { type: 'html', layout: 'top-right', size: [0.6, 0.4] },
    'activity': { type: 'html', layout: 'hidden' }
  }
})

// Create panels (deferred content)
ui.registerPanel('dashboard', () => renderDashboardHTML())
ui.registerPanel('metrics', () => renderMetricsHTML())
ui.registerPanel('activity', () => renderActivityHTML())

// Navigate
ui.goToSpace('overview')     // Animate camera + panels
ui.goToSpace('detail')       // Another space transition

// Control individual panels
ui.showPanel('activity')     // Animate panel into view
ui.hidePanel('metrics')      // Animate panel out of view
ui.movePanel('dashboard', { position: [-2, 1, 0] })
ui.animatePanel('dashboard', 'bounce')  // Pre-built animation

// Events
ui.on('space-change', (from, to) => console.log(`${from} → ${to}`))
ui.on('panel-click', (panelId, point) => console.log(`Clicked ${panelId}`))
ui.on('camera-orbit', (orientation) => console.log('User orbiting...'))
```

---

## Animation Presets

### Panel Entrance Animations

| Name | Description | Best For |
|------|-------------|---------|
| **slide-in** | Slides from edge, overshoots, settles | Primary panels |
| **pop-in** | Scales up from 0 with bounce | Small widgets, alerts |
| **fade-slide** | Fades in while sliding | Secondary panels |
| **flip-in** | Flips from z-rotation | Transitions, reveals |
| **cascade** | Multiple panels, staggered delay | Space transitions |
| **snap-in** | Immediate, no overshoot | Urgent alerts, errors |

### Space Transition Styles

| Name | Description |
|------|-------------|
| **smooth** | Camera + panels ease together |
| **crash** | Camera snaps, panels follow |
| **orbit** | Camera rotates around, panels rearrange |
| **zoom** | Camera zooms in/out, panels fade |
| **warp** | Camera flies past, panels blur |
| **cinematic** | Multi-step: panels hide → camera moves → panels show |

---

## CSS Framework for Panel Styling

```css
/* Base panel */
.spacial-panel {
  background: rgba(10, 10, 26, 0.85);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 24px;
  color: #ffffff;
  font-family: 'Inter', system-ui, sans-serif;
  will-change: transform;
  transform-style: preserve-3d;
  pointer-events: auto;
  user-select: text;
}

/* Panel header */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

/* Panel title with icon */
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.7);
}

/* Panel content area */
.panel-content {
  /* Content injected here */
}

/* Panel controls */
.panel-controls {
  display: flex;
  gap: 8px;
}

/* Panel button */
.panel-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 6px 12px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.panel-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.15);
}

/* Active/hover state for 3D panels */
.spacial-panel:hover {
  border-color: rgba(100, 200, 255, 0.2);
  box-shadow: 0 0 30px rgba(100, 200, 255, 0.05);
}

/* Panel that's facing the camera */
.spacial-panel.facing-camera {
  /* Panels rotate to face camera in "always-facing" mode */
}

/* Panel shadow */
.spacial-panel::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 10%;
  right: 10%;
  height: 20px;
  background: radial-gradient(ellipse, rgba(0,0,0,0.3) 0%, transparent 70%);
  filter: blur(8px);
  pointer-events: none;
}
```

---

## Performance Benchmarks to Target

| Metric | Target | Notes |
|--------|--------|-------|
| **Frame rate** | 60 FPS | 10 panels in view |
| **Frame rate** | 30 FPS | 30 panels in view |
| **Space transition time** | < 1.5s | Camera + all panels |
| **Panel click latency** | < 50ms | Pointer → action |
| **Panel count** | 50 max | Per space |
| **Camera orbit latency** | < 16ms | Per frame |
| **Memory usage** | < 200MB | With 50 panels |

---

## Comparison to Existing Approaches

| Feature | Custom 3D UI | HTML Overlay | Pure 3D |
|---------|-------------|-------------|---------|
| **2D usability** | Full (CSS3D) | Full | Poor |
| **3D depth** | Full | None | Full |
| **Animations** | Full control | CSS limited | Full |
| **Accessibility** | Full (CSS3D) | Full | None |
| **Performance** | Good | Good | Variable |
| **Development time** | Longest | Shortest | Long |
| **Flexibility** | Unlimited | Limited | High |
| **Learning curve** | Steep | Easy | Steep |

---

## Decision: Build Your Own

**Why build this instead of using existing solutions:**

1. **Total control over motion** — Every spring constant, every easing curve, every transition is yours to tune
2. **Unified system** — Panels, camera, background, animations all in one cohesive system
3. **Custom interaction model** — Not constrained by existing paradigms
4. **Optimized for OPERATOR** — Built specifically for the seed/portfolio metaphor
5. **No bloat** — Only what you need, nothing extra
6. **Identity** — This becomes a signature experience, not a library wrapper

**Build it if:**
- You value motion design as a core product feature
- You want the UI to feel unlike anything else
- You have the engineering bandwidth for a custom animation system
- The 3D spatial metaphor is central to the experience

**Skip building if:**
- You just want the result ASAP
- Motion design isn't a differentiator for you
- Your team lacks 3D/WebGL expertise

