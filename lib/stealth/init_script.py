"""init_script — build the JS injected via CDP Page.addScriptToEvaluateOnNewDocument.

This script runs at document creation, BEFORE any page script, so the overrides
are in place before the page reads navigator.webdriver / canvas / WebGL. It:

1. Strips navigator.webdriver and the HeadlessChrome markers at the driver/CDP
   level (pre-page-script), not as a page-level override the page observes.
2. Makes navigator.platform / hardwareConcurrency / deviceMemory / maxTouchPoints
   coherent with the chosen device profile.
3. Spoofs WebGL VENDOR / RENDERER (37445/37446) to the profile GPU — the real GPU
   is the loudest fingerprint vector.
4. Injects SESSION-STABLE canvas noise: toDataURL/toBlob/getImageData are
   intercepted so each output pixel is perturbed by a pure function of
   (x, y, SEED). Repeated identical renders get identical noise, so multi-render
   consistency checks do not flag naive per-call random noise.
5. Injects session-stable audio noise into AudioBuffer.getChannelData.

The noise is deterministic in (coords, seed) only — never Math.random() per
call — which is what makes it pass consistency checks while still breaking
the canvas/audio fingerprint hash across profiles.
"""
from __future__ import annotations

import json
from typing import Any, Dict

# JS template. __PROFILE_JSON__ and __SEED__ are str.replace'd in to avoid
# Python f-string brace-escaping the entire script.
_JS = r"""
(() => {
  if (window.__stealth_patched__) return;   // idempotent: never double-patch a document
  window.__stealth_patched__ = true;
  window.__stealth_runs__ = (window.__stealth_runs__ || 0) + 1;
  const PROFILE = __PROFILE_JSON__;
  const SEED = __SEED__ | 0;
  // ---- seeded PRNG: mulberry32 (deterministic, no Math.random) ----------
  function mulberry32(a){a=a|0;return function(){a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)-((t^t>>>14)>>>0);return((t>>>0)/4294967296);};}
  // Deterministic per-pixel noise in [-amp, amp). Pure function of (x,y,SEED).
  function pixelNoise(x,y){const g=mulberry32((SEED^(x*73856093)^(y*19349663))>>>0);return (g()-0.5);}
  function idxNoise(i){const g=mulberry32((SEED^(i*83492791))>>>0);return (g()-0.5);}

  const define = (obj, prop, val) => {
    try { Object.defineProperty(obj, prop, { get: () => val, configurable: true }); } catch (e) {}
  };

  // ---- 1. webdriver / automation markers --------------------------------
  try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false, configurable: true }); } catch (e) {}
  // Clear the domAutomation / cdc_ injection markers if present.
  try { delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array; } catch (e) {}
  try { delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise; } catch (e) {}
  try { delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol; } catch (e) {}

  // ---- 2. coherent navigator signals ------------------------------------
  const nav = Navigator.prototype;
  define(nav, 'platform', PROFILE.platform);
  define(nav, 'hardwareConcurrency', PROFILE.hardwareConcurrency);
  define(nav, 'deviceMemory', PROFILE.deviceMemory);
  define(nav, 'maxTouchPoints', PROFILE.maxTouchPoints);
  // languages stays the browser default (coherent with UA locale).

  // ---- 3. WebGL vendor/renderer spoof (loudest vector) ------------------
  const patchGL = (proto) => {
    if (!proto || !proto.getParameter) return;
    const orig = proto.getParameter;
    proto.getParameter = function (p) {
      // UNMASKED_VENDOR_WEBGL=37445, UNMASKED_RENDERER_WEBGL=37446
      if (p === 37445) return PROFILE.webglVendor;
      if (p === 37446) return PROFILE.webglRenderer;
      if (p === 7936) return PROFILE.webglVendor;  // VENDOR
      if (p === 7937) return PROFILE.webglRenderer; // RENDERER
      return orig.call(this, p);
    };
  };
  patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // ---- 4. session-stable canvas noise -----------------------------------
  const amp = 1.0; // sub-2-LSB perturbation: invisible to humans, breaks the hash
  const getImageData = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function (...args) {
    const img = getImageData.apply(this, args);
    try {
      const d = img.data, w = img.width;
      for (let i = 0; i < d.length; i += 4) {
        const p = i >> 2, x = p % w, y = (p / w) | 0;
        const n = pixelNoise(x, y) * amp;
        d[i]     = d[i]     + n < 0 ? 0 : d[i]     + n > 255 ? 255 : d[i]     + n;
        d[i + 1] = d[i + 1] + n < 0 ? 0 : d[i + 1] + n > 255 ? 255 : d[i + 1] + n;
        d[i + 2] = d[i + 2] + n < 0 ? 0 : d[i + 2] + n > 255 ? 255 : d[i + 2] + n;
      }
    } catch (e) {}
    return img;
  };

  const toDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function (...args) {
    try {
      const off = document.createElement('canvas');
      off.width = this.width; off.height = this.height;
      if (!off.width || !off.height) return toDataURL.apply(this, args);
      const ctx = off.getContext('2d'); ctx.drawImage(this, 0, 0);
      const img = ctx.getImageData(0, 0, off.width, off.height); // patched -> noise
      ctx.putImageData(img, 0, 0);
      return toDataURL.apply(off, args);
    } catch (e) { return toDataURL.apply(this, args); }
  };

  const toBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function (cb, ...rest) {
    try {
      const off = document.createElement('canvas');
      off.width = this.width; off.height = this.height;
      if (!off.width || !off.height) return toBlob.call(this, cb, ...rest);
      const ctx = off.getContext('2d'); ctx.drawImage(this, 0, 0);
      const img = ctx.getImageData(0, 0, off.width, off.height);
      ctx.putImageData(img, 0, 0);
      return toBlob.call(off, cb, ...rest);
    } catch (e) { return toBlob.call(this, cb, ...rest); }
  };

  // ---- 5. session-stable audio noise ------------------------------------
  if (window.AudioBuffer && AudioBuffer.prototype.getChannelData) {
    const getChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function (...args) {
      const d = getChannelData.apply(this, args);
      try {
        for (let i = 0; i < d.length; i++) { d[i] += idxNoise(i) * 1e-7; }
      } catch (e) {}
      return d;
    };
  }

  // Tag the isolated world so the agent can verify the patch is live.
  window.__stealth_live__ = true;
  window.__stealth_seed__ = SEED;
})();
"""


def build_init_script(profile: Dict[str, Any]) -> str:
    """Return the JS init script string for a profile (from derive_profile)."""
    payload = {
        "platform": profile["platform"],
        "hardwareConcurrency": profile["hardwareConcurrency"],
        "deviceMemory": profile["deviceMemory"],
        "maxTouchPoints": profile.get("maxTouchPoints", 0),
        "webglVendor": profile["webglVendor"],
        "webglRenderer": profile["webglRenderer"],
    }
    js = _JS.replace("__PROFILE_JSON__", json.dumps(payload))
    js = js.replace("__SEED__", str(int(profile["seed"]) & 0xFFFFFFFF))
    return js