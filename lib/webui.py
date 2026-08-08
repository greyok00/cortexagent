#!/usr/bin/env python3
"""webui — HTTP UI for cortexagent with a three.js 3D cortex.

Stdlib only (http.server) + a vendored three.js (ESM) served from
assets/vendor/ at /static/*. Endpoints:

  GET  /            — 3D chat interface (gold cortex neural scene + glass chat)
  POST /message     — Send a message (proxies to claude-code subprocess)
  GET  /status      — JSON: profile, model, context, current task
  GET  /health      — Quick liveness
  GET  /assets/logo — Square logo
  GET  /static/*    — Vendored three.js + OrbitControls (offline-capable)

Auth: if CORTEXAGENT_WEBUI_TOKEN is set, requests must include
      Authorization: Bearer <token> OR X-CortexAgent-Token: <token>.

ENV knobs:
  CORTEXAGENT_WEBUI_ENABLED  — "1" to enable (default: on)
  CORTEXAGENT_WEBUI_PORT     — port (default: 8090)
  CORTEXAGENT_WEBUI_BIND     — bind address (default: 127.0.0.1)
  CORTEXAGENT_WEBUI_TOKEN    — auth token (default: none)

CLI:
  python3 webui.py serve          # foreground
  python3 webui.py smoke          # import + endpoint check
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


# ── Config ────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8090
DEFAULT_BIND = "127.0.0.1"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "cortexagentsquarelogo.jpg"
# Vendor dir for the 3D UI: three.js (ESM) + OrbitControls, served at /static/*
VENDOR_DIR = Path(__file__).resolve().parent.parent / "assets" / "vendor"
_STATIC_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
}
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>CORTEXAGENT</title>
<style>
  /* ── Design Tokens (UI Framework — Luxury Brand) ── */
  :root {
    --bg-primary: #000000;
    --bg-secondary: #0A0A0A;
    --bg-tertiary: #141414;
    --surface: rgba(20,20,20,0.55);
    --text-primary: #FFFFFF;
    --text-secondary: #A0A0A0;
    --text-tertiary: #666666;
    --accent: #C9A84C;
    --accent-hover: #D4B85C;
    --accent-soft: rgba(201,168,76,0.18);
    --border: rgba(201,168,76,0.18);
    --border-strong: rgba(201,168,76,0.35);
    --success: #6FCF97;
    --error: #E57373;
    --warning: #F2C94C;
    --radius: 14px;
    --font: 'Helvetica Neue', 'Inter', Arial, sans-serif;
    --mono: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    --transition: 600ms cubic-bezier(0.25, 0.1, 0.25, 1);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    font-family: var(--font); background: var(--bg-primary);
    color: var(--text-primary); font-weight: 300;
    letter-spacing: 0.04em; line-height: 1.6;
    overflow: hidden;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { color: var(--accent-hover); }

  /* ── 3D Canvas ── */
  #cortex {
    position: fixed; inset: 0; width: 100%; height: 100%;
    z-index: 0; display: block;
  }

  /* ── Loading overlay ── */
  #loading {
    position: fixed; inset: 0; z-index: 100; display: flex;
    flex-direction: column; align-items: center; justify-content: center;
    gap: 18px; background: var(--bg-primary);
    transition: opacity 0.8s ease; cursor: progress;
  }
  #loading.fade { opacity: 0; pointer-events: none; }
  .ring {
    width: 46px; height: 46px; border-radius: 50%;
    border: 1.5px solid rgba(201,168,76,0.12);
    border-top-color: var(--accent);
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-label {
    font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase;
    color: var(--text-tertiary);
  }

  /* ── HUD (top bar) ── */
  #hud {
    position: fixed; top: 0; left: 0; right: 0; z-index: 20;
    display: flex; align-items: center; gap: 14px;
    padding: 16px 22px; pointer-events: none;
  }
  #hud > * { pointer-events: auto; }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand .logo {
    width: 30px; height: 30px; border-radius: 8px;
    box-shadow: 0 0 18px rgba(201,168,76,0.25);
  }
  .brand h1 {
    font-size: 13px; font-weight: 700; letter-spacing: 0.22em;
    text-transform: uppercase; color: var(--accent); margin: 0;
  }
  .brand h1 small {
    display: block; font-size: 9px; letter-spacing: 0.34em;
    color: var(--text-tertiary); font-weight: 400; margin-top: 2px;
  }
  .status-chip {
    margin-left: auto; display: flex; align-items: center; gap: 8px;
    font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--text-tertiary);
    background: var(--surface; rgba(20,20,20,0.5));
    background: rgba(18,18,18,0.55);
    backdrop-filter: blur(14px) saturate(140%);
    -webkit-backdrop-filter: blur(14px) saturate(140%);
    border: 1px solid var(--border);
    padding: 7px 14px; border-radius: 999px;
    transition: color var(--transition), border-color var(--transition);
  }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-tertiary); }
  .status-chip.online { color: var(--success); border-color: rgba(111,207,151,0.4); }
  .status-chip.online .status-dot { background: var(--success); box-shadow: 0 0 10px var(--success); }
  .status-chip.offline { color: var(--error); border-color: rgba(229,115,115,0.35); }
  .status-chip.offline .status-dot { background: var(--error); }
  .ctx-bar {
    margin-top: 2px; width: 120px; height: 2px; border-radius: 2px;
    background: rgba(255,255,255,0.08); overflow: hidden; display: none;
  }
  .ctx-bar > i { display: block; height: 100%; width: 0%; background: var(--accent); transition: width 0.6s ease; }
  .status-chip.online .ctx-bar { display: block; }

  /* ── Chat panel (glass) ── */
  #panel {
    position: fixed; z-index: 15;
    right: 22px; bottom: 22px;
    width: min(420px, calc(100vw - 44px));
    max-height: calc(100vh - 130px);
    display: flex; flex-direction: column;
    background: rgba(12,12,12,0.62);
    backdrop-filter: blur(22px) saturate(150%);
    -webkit-backdrop-filter: blur(22px) saturate(150%);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 24px 70px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.04);
    overflow: hidden;
  }
  .panel-head {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 16px; border-bottom: 1px solid var(--border);
    font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--text-tertiary);
  }
  .panel-head .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
  .panel-head .pill { margin-left: auto; color: var(--accent); }

  .messages { flex: 1; overflow-y: auto; padding: 16px; scroll-behavior: smooth; min-height: 160px; }
  .messages::-webkit-scrollbar { width: 6px; }
  .messages::-webkit-scrollbar-thumb { background: rgba(201,168,76,0.25); border-radius: 3px; }

  .msg {
    padding: 11px 14px; margin: 8px 0; border-radius: 10px;
    white-space: pre-wrap; word-break: break-word;
    font-weight: 300; font-size: 14px;
    animation: rise 0.5s cubic-bezier(0.2,0.8,0.2,1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  .msg.user { background: var(--accent-soft); border-left: 2px solid var(--accent); }
  .msg.assistant { background: rgba(255,255,255,0.04); border: 1px solid var(--border); }
  .msg.error { background: rgba(229,115,115,0.12); border-left: 2px solid var(--error); color: var(--error); }
  .msg.system { background: rgba(255,255,255,0.03); color: var(--text-tertiary); font-style: italic; border: 1px dashed var(--border); }
  .msg .meta { font-size: 10px; color: var(--text-tertiary); margin-top: 5px; letter-spacing: 0.1em; text-transform: uppercase; }
  .msg .prefix { color: var(--accent); font-weight: 700; margin-right: 8px; }
  .msg.assistant .prefix { color: var(--success); }
  code { background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px; font-family: var(--mono); font-size: 12px; }
  pre { background: rgba(0,0,0,0.5); padding: 12px; margin: 8px 0; border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; font-size: 12px; line-height: 1.55; }

  /* ── Skeleton ── */
  .skeleton { padding: 11px 14px; }
  .sk-line { height: 11px; background: rgba(201,168,76,0.10); border-radius: 4px; margin: 7px 0; position: relative; overflow: hidden; }
  .sk-line::after { content: ''; position: absolute; inset: 0; transform: translateX(-100%); background: linear-gradient(90deg, transparent, rgba(201,168,76,0.18), transparent); animation: shimmer 1.4s infinite; }
  @keyframes shimmer { 100% { transform: translateX(100%); } }
  .sk-line:nth-child(1) { width: 82%; } .sk-line:nth-child(2) { width: 60%; } .sk-line:nth-child(3) { width: 70%; }

  /* ── Input ── */
  form { display: flex; gap: 10px; padding: 12px; border-top: 1px solid var(--border); background: rgba(0,0,0,0.25); }
  textarea {
    flex: 1; resize: none; min-height: 44px; max-height: 140px;
    background: rgba(0,0,0,0.4); color: var(--text-primary);
    border: 1px solid var(--border-strong); border-radius: 10px;
    padding: 12px 14px; font-family: var(--font); font-size: 14px;
    font-weight: 300; line-height: 1.5; transition: border-color var(--transition);
  }
  textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(201,168,76,0.08); }
  textarea::placeholder { color: var(--text-tertiary); }
  button {
    background: var(--accent); color: #1a1408; border: none;
    padding: 0 20px; border-radius: 10px; cursor: pointer;
    font-weight: 700; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase;
    transition: background var(--transition), transform 0.1s ease;
  }
  button:hover { background: var(--accent-hover); }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.35; cursor: wait; }

  .hint {
    position: fixed; left: 22px; bottom: 22px; z-index: 15;
    font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase;
    color: var(--text-tertiary); opacity: 0.7; pointer-events: none;
  }

  /* ── Responsive ── */
  @media (max-width: 640px) {
    #panel { right: 0; left: 0; bottom: 0; width: 100%; max-height: 62vh; border-radius: 16px 16px 0 0; }
    #hud { padding: 12px 14px; }
    .brand h1 { font-size: 11px; }
    .ctx-bar { width: 80px; }
    .hint { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { animation-duration: 0.01ms !important; }
  }
</style>
</head>
<body>
<canvas id="cortex"></canvas>

<div id="loading">
  <div class="ring"></div>
  <div class="loading-label">Booting Cortex</div>
</div>

<div id="hud">
  <div class="brand">
    <img src="/assets/logo" alt="CortexAgent" class="logo">
    <h1>CortexAgent<small>Neural Interface</small></h1>
  </div>
  <div class="status-chip offline" id="status">
    <span class="status-dot"></span><span id="status-text">Offline</span>
    <div class="ctx-bar"><i id="ctx-fill"></i></div>
  </div>
</div>

<div id="panel">
  <div class="panel-head">
    <span class="dot"></span><span>Conversation</span><span class="pill" id="ctx-label">—</span>
  </div>
  <div class="messages" id="messages">
    <div class="skeleton" id="skeleton">
      <div class="sk-line"></div><div class="sk-line"></div><div class="sk-line"></div>
    </div>
  </div>
  <form id="form">
    <textarea id="input" placeholder="Speak to the cortex…" autofocus></textarea>
    <button id="send" type="submit">Send</button>
  </form>
</div>

<div class="hint">Drag to orbit · Scroll to zoom</div>

<script type="importmap">
{
  "imports": {
    "three": "/static/three.module.min.js",
    "three/addons/": "/static/addons/"
  }
}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ── Renderer / scene / camera ──────────────────────────────────────────
const canvas = document.getElementById('cortex');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(52, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, 1.5, 15);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.enablePan = false;
controls.autoRotate = !reducedMotion;
controls.autoRotateSpeed = 0.45;
controls.minDistance = 8;
controls.maxDistance = 28;

// ── Glow texture (radial) ───────────────────────────────────────────────
function glowTex() {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,0.85)');
  grd.addColorStop(0.6, 'rgba(255,255,255,0.18)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const tex = glowTex();
const GOLD = new THREE.Color(0xC9A84C);
const GOLD_DIM = new THREE.Color(0x6b5a2a);

// ── Build the cortex: nodes on a fibonacci sphere + inner core ─────────
const N = 168;
const nodes = [];
const R = 6.4;
for (let i = 0; i < N; i++) {
  const inner = i < 96;
  const r = inner ? R * (0.30 + 0.65 * (i / 96)) : R + (Math.random() - 0.5) * 0.8;
  const t = i / N;
  const phi = Math.acos(1 - 2 * t);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  const jitter = inner ? 0 : 0.6;
  nodes.push(new THREE.Vector3(
    r * Math.sin(phi) * Math.cos(theta) + (Math.random() - 0.5) * jitter,
    r * Math.cos(phi) + (Math.random() - 0.5) * jitter,
    r * Math.sin(phi) * Math.sin(theta) + (Math.random() - 0.5) * jitter
  ));
}

// ── Edges: connect nearby nodes ────────────────────────────────────────
const edges = [];
const edgePos = [];
const THRESH = 2.7;
for (let i = 0; i < N; i++) {
  for (let j = i + 1; j < N; j++) {
    const d = nodes[i].distanceTo(nodes[j]);
    if (d < THRESH && Math.random() < 0.62) {
      edges.push({ a: i, b: j });
      edgePos.push(nodes[i].x, nodes[i].y, nodes[i].z, nodes[j].x, nodes[j].y, nodes[j].z);
    }
  }
}

const cortex = new THREE.Group();
scene.add(cortex);

// node points
const nodeGeom = new THREE.BufferGeometry();
const nodeArr = new Float32Array(N * 3);
nodes.forEach((p, i) => { nodeArr[i*3]=p.x; nodeArr[i*3+1]=p.y; nodeArr[i*3+2]=p.z; });
nodeGeom.setAttribute('position', new THREE.BufferAttribute(nodeArr, 3));
const nodeMat = new THREE.PointsMaterial({
  size: 0.26, map: tex, color: GOLD, transparent: true, depthWrite: false,
  blending: THREE.AdditiveBlending, sizeAttenuation: true, opacity: 0.95
});
const nodePoints = new THREE.Points(nodeGeom, nodeMat);
cortex.add(nodePoints);

// edges
const edgeGeom = new THREE.BufferGeometry();
edgeGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(edgePos), 3));
const edgeMat = new THREE.LineBasicMaterial({ color: GOLD_DIM, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending });
const edgeLines = new THREE.LineSegments(edgeGeom, edgeMat);
cortex.add(edgeLines);

// central core glow
const coreMat = new THREE.SpriteMaterial({ map: tex, color: GOLD, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false });
const core = new THREE.Sprite(coreMat); core.scale.set(4.5, 4.5, 1); cortex.add(core);

// ── Pulses: pool of points travelling along edges ──────────────────────
const P = 70;
const pulsePos = new Float32Array(P * 3);
const pulseGeom = new THREE.BufferGeometry();
pulseGeom.setAttribute('position', new THREE.BufferAttribute(pulsePos, 3));
const pulseMat = new THREE.PointsMaterial({
  size: 0.62, map: tex, color: 0xfff0c8, transparent: true, depthWrite: false,
  blending: THREE.AdditiveBlending, sizeAttenuation: true, opacity: 0.9
});
const pulsePoints = new THREE.Points(pulseGeom, pulseMat);
cortex.add(pulsePoints);
const pulses = [];
for (let i = 0; i < P; i++) {
  pulses.push({ edge: (Math.random() * edges.length) | 0, t: Math.random(), speed: 0.18 + Math.random() * 0.22 });
}

// ── Thinking intensity (0..1), spikes on send/response, decays ─────────
let think = 0;
function setThink(v) { think = Math.max(think, v); }

// ── Animation loop ─────────────────────────────────────────────────────
let last = performance.now();
let running = true;
function frame(now) {
  if (!running) return;
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000); last = now;

  for (let i = 0; i < P; i++) {
    const p = pulses[i];
    p.t += dt * p.speed * (0.45 + think * 3.2);
    if (p.t >= 1) { p.t = 0; p.edge = (Math.random() * edges.length) | 0; }
    const e = edges[p.edge]; if (!e) continue;
    const a = nodes[e.a], b = nodes[e.b];
    pulsePos[i*3]   = a.x + (b.x - a.x) * p.t;
    pulsePos[i*3+1] = a.y + (b.y - a.y) * p.t;
    pulsePos[i*3+2] = a.z + (b.z - a.z) * p.t;
  }
  pulseGeom.attributes.position.needsUpdate = true;

  nodeMat.size = 0.26 + think * 0.16;
  nodeMat.opacity = 0.85 + think * 0.15;
  edgeMat.opacity = 0.22 + think * 0.5;
  coreMat.opacity = 0.45 + think * 0.45;
  core.scale.setScalar(4.5 + think * 2.2);
  controls.autoRotateSpeed = (reducedMotion ? 0 : 0.45) + think * 2.4;
  if (!reducedMotion) cortex.rotation.y += dt * 0.04;

  think *= 0.986;
  controls.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(frame);

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
document.addEventListener('visibilitychange', () => {
  running = !document.hidden;
  if (running) { last = performance.now(); requestAnimationFrame(frame); }
});

// Fade out loader after first frame
requestAnimationFrame(() => {
  const l = document.getElementById('loading');
  l.classList.add('fade');
  setTimeout(() => l.remove(), 900);
});

// ── Chat logic (unchanged behaviour, wired to the cortex) ───────────────
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const messagesEl = document.getElementById('messages');
const statusChip = document.getElementById('status');
const statusText = document.getElementById('status-text');
const ctxFill = document.getElementById('ctx-fill');
const ctxLabel = document.getElementById('ctx-label');
const form = document.getElementById('form');
const input = document.getElementById('input');
const send = document.getElementById('send');
const skeleton = document.getElementById('skeleton');

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (TOKEN) h['Authorization'] = 'Bearer ' + TOKEN;
  return h;
}

async function loadStatus() {
  try {
    const r = await fetch('/status', { headers: authHeaders() });
    if (!r.ok) { statusText.textContent = 'Auth Required'; statusChip.className = 'status-chip offline'; return; }
    const j = await r.json();
    statusText.textContent = `${j.profile || 'default'} · ${j.model || 'local'}`;
    statusChip.className = 'status-chip online';
    if (j.context_used_tokens != null && j.context_max_tokens) {
      const pct = Math.min(100, (j.context_used_tokens / j.context_max_tokens) * 100);
      ctxFill.style.width = pct.toFixed(1) + '%';
      ctxLabel.textContent = `${j.context_used_tokens}/${j.context_max_tokens}`;
    } else {
      ctxLabel.textContent = j.model || 'local';
    }
  } catch (e) {
    statusText.textContent = 'Offline';
    statusChip.className = 'status-chip offline';
  }
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function append(role, text, cls) {
  if (skeleton) skeleton.remove();
  const div = document.createElement('div');
  div.className = 'msg ' + (cls || role);
  const prefix = role === 'user' ? '▸' : role === 'assistant' ? '✓' : '!';
  div.innerHTML = `<span class="prefix">${prefix}</span>${escHtml(text)}`;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  append('user', text);
  input.value = '';
  send.disabled = true;
  setThink(1.0);                       // cortex lights up while thinking
  if (skeleton) skeleton.style.display = 'block';
  try {
    const r = await fetch('/message', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ message: text }) });
    const j = await r.json();
    if (j.ok) { append('assistant', j.response || '(no response)'); setThink(0.55); }
    else { append('error', j.reason || 'request failed'); }
    loadStatus();
  } catch (err) {
    append('error', String(err));
  } finally {
    send.disabled = false;
    if (skeleton) skeleton.style.display = 'none';
    input.focus();
  }
});

loadStatus();
setInterval(loadStatus, 30000);
</script>
</body>
</html>
"""


def _get_config() -> Dict:
    return {
        "enabled": os.environ.get("CORTEXAGENT_WEBUI_ENABLED", "1") != "0",
        "port": int(os.environ.get("CORTEXAGENT_WEBUI_PORT", str(DEFAULT_PORT))),
        "bind": os.environ.get("CORTEXAGENT_WEBUI_BIND", DEFAULT_BIND),
        "token": os.environ.get("CORTEXAGENT_WEBUI_TOKEN", "").strip(),
    }


def _check_auth(headers) -> bool:
    cfg = _get_config()
    if not cfg["token"]:
        return True
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == cfg["token"]:
        return True
    if headers.get("X-CortexAgent-Token", "").strip() == cfg["token"]:
        return True
    return False


def _status_payload() -> Dict:
    """Collect real status from cortexagent's runtime state."""
    profile = os.environ.get("CORTEXAGENT_PROFILE", "default")
    model = os.environ.get("CORTEXAGENT_ALIAS", "local")
    ctx_used = None
    ctx_max = None
    # Pull from heap/dump files if present
    heap = Path.home() / ".cortexagent" / "state" / "ctx_usage.json"
    if heap.exists():
        try:
            data = json.loads(heap.read_text())
            ctx_used = data.get("tokens_used")
            ctx_max = data.get("tokens_max")
        except Exception:
            pass
    return {
        "profile": profile,
        "model": model,
        "context_used_tokens": ctx_used,
        "context_max_tokens": ctx_max,
        "timestamp": datetime.now().isoformat(),
    }


def _proxy_to_claude(message: str, profile: str = "default",
                     timeout: int = 300) -> Tuple[bool, str]:
    """Send a message to a claude-code subprocess and return (ok, response).

    Uses `claude -p <message> --profile <profile>` non-interactively. Falls back
    to a direct echo if claude isn't available or fails.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", message, "--profile", profile],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, f"claude exit {result.returncode}: {result.stderr.strip()[:200]}"
    except FileNotFoundError:
        return False, "claude binary not found in PATH"
    except subprocess.TimeoutExpired:
        return False, f"claude timed out after {timeout}s"
    except Exception as e:
        return False, f"proxy error: {e}"


# ── HTTP handler ──────────────────────────────────────────────────────────
class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Quieter logs
        sys.stderr.write(f"[webui] {fmt % args}\n")

    def _send_json(self, status: int, payload: Dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str) -> None:
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _send_logo(self) -> None:
        try:
            data = _LOGO_PATH.read_bytes()
        except Exception:
            self._send_json(404, {"ok": False, "reason": "logo not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, rel: str) -> None:
        """Serve a vendored static asset (three.js etc.) from assets/vendor/.
        Path is confined: no traversal outside VENDOR_DIR."""
        base = VENDOR_DIR.resolve()
        try:
            target = (base / rel).resolve()
        except Exception:
            self._send_json(404, {"ok": False, "reason": "not found"})
            return
        if base not in target.parents and target != base:
            self._send_json(404, {"ok": False, "reason": "not found"})
            return
        if not target.is_file():
            self._send_json(404, {"ok": False, "reason": "not found"})
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _STATIC_MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _check_auth_or_401(self) -> bool:
        if not _check_auth(self.headers):
            self._send_json(401, {"ok": False, "reason": "auth required"})
            return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "cortexagent-webui"})
            return
        if parsed.path in ("/", "/index.html"):
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/status":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _status_payload())
            return
        if parsed.path == "/assets/logo":
            self._send_logo()
            return
        if parsed.path.startswith("/static/"):
            self._send_static(parsed.path[len("/static/"):])
            return
        self._send_json(404, {"ok": False, "reason": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/message":
            self._send_json(404, {"ok": False, "reason": "not found"})
            return
        if not self._check_auth_or_401():
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"ok": False, "reason": f"parse error: {e}"})
            return
        message = (body.get("message") or "").strip()
        if not message:
            self._send_json(400, {"ok": False, "reason": "empty message"})
            return
        profile = body.get("profile", os.environ.get("CORTEXAGENT_PROFILE", "default"))
        ok, response = _proxy_to_claude(message, profile=profile)
        self._send_json(200 if ok else 500, {
            "ok": ok,
            "response": response,
            "reason": None if ok else response,
        })


# ── Server bootstrap ─────────────────────────────────────────────────────
def serve_forever(bind: Optional[str] = None, port: Optional[int] = None) -> ThreadingHTTPServer:
    cfg = _get_config()
    bind = bind or cfg["bind"]
    port = port or cfg["port"]
    if not cfg["enabled"]:
        raise RuntimeError("CORTEXAGENT_WEBUI_ENABLED=0")
    server = ThreadingHTTPServer((bind, port), WebUIHandler)
    print(f"[webui] serving on http://{bind}:{port}", file=sys.stderr)
    return server


# ── CLI ─────────────────────────────────────────────────────────────────────
def _cli(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "smoke":
        return _smoke()
    if cmd == "serve":
        try:
            server = serve_forever()
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[webui] shutting down")
            server.shutdown()
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def _smoke() -> int:
    # Smoke: import + ephemeral server + endpoint checks
    import urllib.request

    # Serve on a free port
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    # Disable auth for smoke
    os.environ["CORTEXAGENT_WEBUI_TOKEN"] = ""
    server = serve_forever(port=port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # GET /health
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            assert r.status == 200
            payload = json.loads(r.read())
            assert payload["ok"] is True
        print(f"  /health: ok={payload['ok']}")

        # GET /
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
            body = r.read().decode()
            assert "CORTEXAGENT" in body and "<textarea" in body
        print(f"  /: 3D HTML served (cortex scene + textarea)")

        # GET /static/three.module.min.js (vendored, offline-capable)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/three.module.min.js", timeout=5) as r:
            assert r.status == 200
            assert "three" in r.read().decode().lower()
        print(f"  /static/three.module.min.js: vendored three.js served")

        # static path traversal blocked
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/static/../../etc/passwd", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print(f"  /static/ traversal: 404 (confined)")

        # GET /status
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=5) as r:
            assert r.status == 200
            payload = json.loads(r.read())
            assert "profile" in payload
        print(f"  /status: profile={payload['profile']} model={payload['model']}")

        # POST /message with empty message
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/message",
            data=json.dumps({"message": ""}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            payload = json.loads(e.read())
            assert "empty" in payload["reason"].lower()
        print(f"  /message empty: rejected with 400")

        # 404
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nonexistent", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print(f"  /nonexistent: 404")
    finally:
        server.shutdown()
        server.server_close()

    # Auth path: spin up a second server with a token set BEFORE serving
    os.environ["CORTEXAGENT_WEBUI_TOKEN"] = "secret-xyz"
    import socket as _socket
    s2 = _socket.socket()
    s2.bind(("127.0.0.1", 0))
    port2 = s2.getsockname()[1]
    s2.close()
    server2 = serve_forever(port=port2)
    t2 = threading.Thread(target=server2.serve_forever, daemon=True)
    t2.start()
    try:
        # No auth → 401
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port2}/status", timeout=5)
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        print(f"  /status with token set (no auth sent): 401")
        # With bearer token → 200
        req = urllib.request.Request(
            f"http://127.0.0.1:{port2}/status",
            headers={"Authorization": "Bearer secret-xyz"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        print(f"  /status with valid bearer token: 200")
        # With X-CortexAgent-Token header → 200
        req = urllib.request.Request(
            f"http://127.0.0.1:{port2}/status",
            headers={"X-CortexAgent-Token": "secret-xyz"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        print(f"  /status with X-CortexAgent-Token: 200")
    finally:
        server2.shutdown()
        server2.server_close()
        os.environ["CORTEXAGENT_WEBUI_TOKEN"] = ""

    print("webui: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))