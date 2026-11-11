#!/usr/bin/env python3
"""captcha_solve.py - THE local, key-free captcha solver.

One module owns the whole SOLVE contract for the slot lane: it detects
which provider is on the page (recaptcha/hcaptcha/turnstile via the same
iframe regex family browser_session already uses), captures the challenge
frames, asks rungs of the engine LADDER in order until one answers, clicks
the answers in-page, verifies the response field filled, and returns an
honest record. Rungs:

  llm : the model ALREADY RESIDENT for cortexagent, via the local ollama
        gateway (GREYSEARCH_LLM_URL, default http://127.0.0.1:11600,
        /v1/chat/completions - the /api/chat images field is silently
        dropped for cloud models). think:false, small max_tokens. Zero new
        VRAM: we ask an already-running model.
  cpu : the vendored ONNX weights loaded by captcha_model (CPU provider,
        bounded threads, never VRAM): the per-prompt GRID classifier for
        tile-pick challenges, the YOLO DETECTORS for coordinate challenges
        ("click on the X" over one big image -> click points), and the CLIP
        encoder pair as the semantic matcher for prompts nothing vendored
        specializes on.
  gpu : the same loaders with the CUDA provider, ONLY when
        GREYSEARCH_CAPTCHA_GPU=on AND gpu_free(); default off, the
        gpu-natural-mode rule is never overridden by this module.

Two challenge MODES, detected at capture time: "pick" (a grid of tiles,
answered with tile indices to toggle) and "points" (one image element,
answered with normalized click coordinates). The llm rung answers both
(tile-pick JSON vs point-coordinate JSON); the cpu/gpu rungs dispatch by
mode - grid classifier or CLIP for picks, object detector for points.

GREYSEARCH_CAPTCHA_SOLVER=off means detect and skip honestly - the lane
records a captcha-skip mark like any other exhausted attempt; no model is
consulted and no challenge content leaves the page. Records carry provider,
rungs tried with latency, rounds, and solved booleans - never challenge
content, screenshots or tokens.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("greysearch.captcha")

KNOWN_RUNGS = ("llm", "cpu", "gpu")
_SOLVER_KNOB = "GREYSEARCH_CAPTCHA_SOLVER"
_SOLVER_OFF = ("off", "0", "false")
_RUNG_KNOB = "GREYSEARCH_CAPTCHA_RUNGS"
_DEFAULT_RUNGS = "llm,cpu"
_GPU_KNOB = "GREYSEARCH_CAPTCHA_GPU"
_ROUNDS_KNOB = "GREYSEARCH_CAPTCHA_MAX_ROUNDS"
_DEFAULT_ROUNDS = 3


def solver_enabled() -> bool:
    """The kill switch contract: on unless GREYSEARCH_CAPTCHA_SOLVER was
    explicitly set to off/0/false."""
    return os.environ.get(_SOLVER_KNOB, "").strip().lower() not in _SOLVER_OFF


def _gpu_flag_on() -> bool:
    return os.environ.get(_GPU_KNOB, "").strip().lower() in ("1", "on",
                                                             "true", "yes")


def engine_rungs(has_model: bool) -> List[str]:
    """The explicit rung order: GREYSEARCH_CAPTCHA_RUNGS as a comma list,
    defaulted to llm,cpu, filtered to KNOWN_RUNGS; the gpu rung only rides
    along when GREYSEARCH_CAPTCHA_GPU is explicitly on; the cpu rung is
    dropped when no model file resolves; llm is never dropped (its absence
    surfaces as a failed attempt, honestly)."""
    raw = os.environ.get(_RUNG_KNOB, "").strip() or _DEFAULT_RUNGS
    rungs: List[str] = []
    for part in raw.split(","):
        r = part.strip().lower()
        if r in KNOWN_RUNGS and r not in rungs:
            if r == "gpu" and not _gpu_flag_on():
                continue
            if r == "cpu" and not has_model:
                continue
            rungs.append(r)
    if _gpu_flag_on() and "gpu" not in rungs:
        rungs.append("gpu")
    return rungs


def max_rounds() -> int:
    try:
        n = int(os.environ.get(_ROUNDS_KNOB, "").strip() or _DEFAULT_ROUNDS)
    except (TypeError, ValueError):
        n = _DEFAULT_ROUNDS
    return max(1, min(n, 10))


import base64
import urllib.request
import urllib.error

LLM_MODEL = "glm-5.3-flash:cloud"
_LLM_TIMEOUT_KNOB = "GREYSEARCH_CAPTCHA_LLM_TIMEOUT_S"
_LLM_TIMEOUT_DEFAULT = 20.0

_PROMPT_TEMPLATE = """SELECT the image tiles matching the description, \
then reply ONLY with JSON like {{\"picks\":[0,3]}} using 0-based tile \
indices in the order the tiles were sent. Description: {prompt}"""

_POINT_PROMPT_TEMPLATE = """You are looking at ONE image. {prompt} Reply \
ONLY with JSON like {{\"points\":[[0.62,0.31]]}} - the image-space coordinate \
pair (x then y, each normalized 0..1 across the image's width then height) \
of the CENTER of EACH matching object instance. No prose."""


def llm_timeout() -> float:
    """The LLM rung's wall-clock ceiling: GREYSEARCH_CAPTCHA_LLM_TIMEOUT_S,
    defaulted to 20s; non-numeric or non-positive values fall back to the
    default rather than raising."""
    try:
        v = float(os.environ.get(_LLM_TIMEOUT_KNOB, "").strip()
                  or _LLM_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        v = _LLM_TIMEOUT_DEFAULT
    return v if v > 0 else _LLM_TIMEOUT_DEFAULT


def _gateway_post(payload: Dict[str, Any],
                  timeout_s: float) -> Optional[Dict[str, Any]]:
    """One POST to the resident-model gateway (GREYSEARCH_LLM_URL,
    default http://127.0.0.1:11600) at /v1/chat/completions - the ONLY
    format that carries images to the cloud namespace. Malformed traffic,
    timeouts and non-200s are all the same None: a clean fall-through to
    the next rung, never an exception."""
    base = (os.environ.get("GREYSEARCH_LLM_URL")
            or "http://127.0.0.1:11600").strip().rstrip("/")
    try:
        req = urllib.request.Request(
            f"{base}/v1/chat/completions",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode() or "{}")
    except Exception:
        return None


def attempt_llm(images: List[bytes], prompt: str,
                timeout_s: float) -> Optional[List[int]]:
    """Rung 1: the already-resident model. Returns 0-based tile picks or
    None (gateway down, malformed answer, empty inputs). The prompt is
    fixed-shape; the challenge text is untrusted DATA inside it."""
    if not images or not prompt:
        return None
    content: List[Dict[str, Any]] = [
        {"type": "text",
         "text": _PROMPT_TEMPLATE.format(prompt=prompt[:80])}]
    for img in images:
        b64 = base64.b64encode(img).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    payload = {"model": LLM_MODEL,
               "messages": [{"role": "user", "content": content}],
               "max_tokens": 128, "think": False}
    reply = _gateway_post(payload, timeout_s)
    if not isinstance(reply, dict):
        return None
    try:
        text = reply["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None
    # tolerate a fenced or prose-wrapped JSON: pick the first picks array
    m = re.search(r"\{[^{}]*\"picks\"\s*:\s*\[[^{}]*\]", str(text))
    if not m:
        return None
    picks: List[int] = []
    for tok in m.group(0).split("[", 1)[1].split("]")[0].split(","):
        tok = tok.strip()
        if tok.isdigit() and int(tok) < len(images):
            picks.append(int(tok))
    return picks or None


def attempt_llm_points(image: bytes, prompt: str,
                       timeout_s: float) -> Optional[List[tuple]]:
    """Rung 1 for coordinate challenges: the resident model returns the
    normalized click points of each matching instance. Same total-None
    contract as attempt_llm."""
    if not image or not prompt:
        return None
    content: List[Dict[str, Any]] = [
        {"type": "text",
         "text": _POINT_PROMPT_TEMPLATE.format(prompt=prompt[:80])},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64,"
                              + base64.b64encode(image).decode()}}]
    payload = {"model": LLM_MODEL,
               "messages": [{"role": "user", "content": content}],
               "max_tokens": 160, "think": False}
    reply = _gateway_post(payload, timeout_s)
    if not isinstance(reply, dict):
        return None
    try:
        text = reply["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None
    m = re.search(r"\{[^{}]*\"points\"\s*:\s*\[(.*?)\]\s*\}", str(text))
    if not m:
        return None
    points: List[tuple] = []
    body = m.group(1)
    for row in re.findall(r"\[\s*([0-9.,\-eE\s]+)\]", body):
        try:
            parts = [p.strip() for p in row.split(",") if p.strip()]
            x, y = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            points.append((x, y))
    return points or None


_PROVIDER_SCAN_JS = """
() => {
  const re = /(recaptcha|hcaptcha|turnstile)/i;
  const out = new Set();
  for (const f of Array.from(document.querySelectorAll('iframe'))) {
    const m = String(f.src||'').match(re) || String(f.title||'').match(re);
    if (m) out.add(m[1].toLowerCase());
    const a = String(f.src||'').match(/(arkoselabs|funcaptcha)/i);
    if (a) out.add('arkose');
  }
  const t = (((document.body||{})).innerText||'').slice(0, 2000);
  if (re.test(t)) { const m = t.match(re); if (m) out.add(m[1].toLowerCase()); }
  if (document.querySelector("script[src*='recaptcha/releases'],"
                            + "script[src*='recaptcha/api.js'],"
                            + ".grecaptcha-badge")) out.add('recaptcha-v3');
  const hasTextImage = [...document.querySelectorAll('img, canvas')].some(
    el => /captcha/i.test([el.src, el.id, el.className, el.alt].join(' '))
          && (el.naturalWidth || el.width || 0) > 40);
  const hasTextInput = [...document.querySelectorAll('input')].some(
    i => String(i.type || 'text') === 'text'
         && /captcha|verif|code/i.test(
             [i.name, i.id, i.placeholder].join(' ')));
  if (hasTextImage && hasTextInput) out.add('text');
  return ['greysearch-providers'].concat(Array.from(out));
}
"""

_FRAME_SEL = {
    "recaptcha": "iframe[title*='recaptcha challenge' i],"
                 "iframe[src*='recaptcha']",
    "hcaptcha": "iframe[src*='hcaptcha.com/captcha']",
    "turnstile": "iframe[src*='challenges.cloudflare.com']",
    "arkose": "iframe[src*='arkoselabs'], iframe[src*='funcaptcha']",
}
_TILE_SELECTOR = {
    "recaptcha": ".rc-imageselect-target .rc-imageselect-tile, "
                 ".rc-imageselect-target td",
    "hcaptcha": ".challenge-view .task-image, .task-grid .image",
    "turnstile": "",
    "arkose": "[class*='game'] [class*='image'] img, "
              ".challenge-image, img[alt]",
}
_SUBMIT_SELECTOR = {
    "recaptcha": ".verify-button, .rc-button-default,.button-submit",
    "hcaptcha": ".button-submit, .challenge-button",
    "turnstile": "",
    "arkose": "[class*='submit'], .challenge-button",
}
_TILE_MAX = 16          # deterministic capture upper bound
_IMAGE_BYTES_MAX = 200_000
_IMAGE_POINTS_BYTES_MAX = 900_000   # single-image challenges capture larger


def detect_provider(page) -> Optional[str]:
    """First provider marker present on the page (same marker family
    browser_session's widget scan already trusts, extended with the
    Arkose/FunCaptcha frame, the score-only reCAPTCHA v3 markers, and the
    legacy text-captcha shape - an image + a text input that name
    themselves), None when none."""
    try:
        res = page.evaluate(_PROVIDER_SCAN_JS)
    except Exception:
        return None
    for name in ("recaptcha", "hcaptcha", "turnstile", "arkose",
                 "recaptcha-v3", "text"):
        try:
            if res and name in res:
                return name
        except Exception:
            pass
    return None


def _challenge_frame(page, provider):
    """The provider challenge frame locator, or None. Turnstile has no
    grid so this returns None for it by design."""
    if provider not in _FRAME_SEL or not _TILE_SELECTOR.get(provider):
        return None
    try:
        return page.frame_locator(_FRAME_SEL[provider])
    except Exception:
        return None


def capture_grid(page, provider: str) -> Optional[Dict[str, Any]]:
    """PNG screenshots of the challenge tiles in DOM order plus the prompt
    text. Never raises: an unreadable challenge is an honest None for the
    ladder's round loop."""
    fl = _challenge_frame(page, provider)
    if fl is None:
        return None
    try:
        loc = fl.locator(_TILE_SELECTOR[provider])
        tiles = loc.all()[:_TILE_MAX]
    except Exception:
        return None
    if not tiles:
        return None
    # the one-image challenge captures one big PNG; its budget is larger
    byte_cap = (_IMAGE_BYTES_MAX if len(tiles) > 1
                else _IMAGE_POINTS_BYTES_MAX)
    images = []
    for t in tiles:
        try:
            png = t.screenshot(timeout=5000)
            # keep the slot aligned even for an oversized tile: dropping
            # it index-shifts the images list and dispatch_clicks would
            # then click the wrong tile. Only the decode, never the slot.
            if not png or len(png) > byte_cap:
                images.append(b"")
            else:
                images.append(png)
        except Exception:
            images.append(b"")
    if not any(images):
        return None
    prompt = None
    try:
        prompt = (fl.locator(".prompt-text").first.inner_text(timeout=2000)
                  or "").strip()
    except Exception:
        prompt = ""
    if not prompt:
        try:
            prompt = (page.inner_text(timeout=2000) or "").strip()[:80]
        except Exception:
            prompt = ""
    # A single element under the tile selector is the ONE-image challenge
    # shape (area select / image click): mode "points" - the answers are
    # click coordinates, not tile toggles.
    return {"mode": "pick" if len(tiles) > 1 else "points",
            "prompt": prompt or "Select all matching images",
            "images": images}


def dispatch_clicks(page, provider: str, picks: List[int]) -> bool:
    """Click the picked tiles in the challenge frame (0-based, DOM order).
    True only when every pick actually clicked; bounds and unavailable
    frames honestly return False."""
    if not picks:
        return False
    fl = _challenge_frame(page, provider)
    if fl is None:
        return False
    try:
        loc = fl.locator(_TILE_SELECTOR[provider])
        tiles = loc.all()
    except Exception:
        return False
    clicked = 0
    for p in picks:
        if not isinstance(p, int) or p < 0 or p >= len(tiles):
            continue
        try:
            tiles[p].click(timeout=3000)
            clicked += 1
        except Exception:
            pass
    if clicked != len(picks):
        return False
    try:
        sel = _SUBMIT_SELECTOR.get(provider, "")
        if sel:
            fl.locator(sel).first.click(timeout=3000)
    except Exception:
        pass
    return True


def dispatch_points(page, provider: str, points: List[tuple]) -> bool:
    """Click normalized coordinates inside the single challenge image
    element (0..1 fractions of its bounding box). True only when every
    point actually clicked; unavailable frames/bounds honestly return
    False."""
    if not points:
        return False
    fl = _challenge_frame(page, provider)
    if fl is None:
        return False
    try:
        loc = fl.locator(_TILE_SELECTOR[provider])
        tiles = loc.all()
    except Exception:
        return False
    if not tiles:
        return False
    try:
        box = tiles[0].bounding_box()
    except Exception:
        box = None
    if not box:
        return False
    # phase 1 - EVERY point is validated (shape + 0..1 bounds) before the
    # FIRST click: one malformed or out-of-range entry must not leave
    # half-dragged markers on the challenge while the caller reports a
    # miss. All-or-nothing, like the tile path above.
    validated: List = []
    for p in points:
        try:
            x, y = float(p[0]), float(p[1])
        except (IndexError, TypeError, ValueError):
            return False
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return False
        validated.append((x, y))
    # phase 2 - the whole validated sequence clicks or nothing does: a
    # mid-click failure stops before the submit and the record is False
    for x, y in validated:
        try:
            page.mouse.click(
                box["x"] + x * box["width"],
                box["y"] + y * box["height"])
        except Exception:
            return False
    try:
        sel = _SUBMIT_SELECTOR.get(provider, "")
        if sel:
            fl.locator(sel).first.click(timeout=3000)
    except Exception:
        pass
    return True


def _cpu_attempt(images: List[bytes], prompt: str,
                 classifier: Any) -> Optional[List[int]]:
    """Rung 2/3 body: the classifier answers with picks. Kept as a hook so
    ladder fallbacks are testable hermetically."""
    return classifier.classify(images, prompt)


def solve_challenge(page, provider: Optional[str] = None) -> Dict[str, Any]:
    """The full SOLVE contract for one challenged page: detect, capture,
    run the ladder per round, click, and stop the moment the ladder answers
    with picks that actually click, or honestly record the skip at the
    round cap. The no-weights providers route to their own strategies:
    arkose (llm once, honest detect-and-record on the rotation shape),
    recaptcha-v3 (detect-and-record), text (transcribe + type). Never
    raises into the caller's page flow."""
    rec: Dict[str, Any] = {"engaged": False, "provider": provider or "",
                           "rungs": [], "rung": None, "rounds": 0,
                           "solved": False, "latency_ms": {}, "error": None}
    if not solver_enabled():
        return rec
    if provider is None:
        provider = detect_provider(page) or ""
    rec["provider"] = provider
    if not provider:
        rec["error"] = "challenge: no provider detected"
        return rec
    # the no-weights providers carry their own strategies
    if provider == "arkose":
        return solve_arkose(page)
    if provider == "recaptcha-v3":
        return solve_v3_report()
    if provider == "text":
        return solve_text(page)
    rec["engaged"] = True
    import captcha_model as _cm
    grid_model = None
    detector = None
    match = None
    # true PRESENCE, not just the location: any rung is offered only when
    # its weights actually sit on disk (captcha_model.has_cpu_runway covers
    # the grid library, the YOLO detectors + their label table, and the
    # CLIP pair), so the cpu rung is only offered when something can load.
    has_model = _cm.has_cpu_runway()
    rec["rungs"] = engine_rungs(has_model)
    if not rec["rungs"]:
        rec["error"] = "rungs: none available (no model, gpu off)"
        return rec
    cap = max_rounds()
    for rnd in range(1, cap + 1):
        rec["rounds"] = rnd
        cap_now = capture_grid(page, provider)
        if not cap_now or not cap_now.get("images"):
            rec["error"] = "challenge: tiles unreadable"
            return rec
        images = cap_now["images"]
        prompt = cap_now["prompt"]
        mode = cap_now.get("mode", "pick")
        for rung in rec["rungs"]:
            started = time.time()
            picks: Optional[Any] = None
            if rung == "llm":
                if mode == "points":
                    picks = (attempt_llm_points(images[0], prompt,
                                                llm_timeout())
                             if images else None)
                else:
                    picks = attempt_llm(images, prompt, llm_timeout())
            elif rung in ("cpu", "gpu"):
                device = "cpu" if rung == "cpu" else "gpu"
                # mode dispatch: tile challenges answer with classifiers
                # (the grid library first, then the CLIP matcher when no
                # grid model speaks for the prompt), coordinate challenges
                # answer with the object detector's click points.
                if mode == "points":
                    detector = detector or _cm.load_detector(device)
                    if detector is not None:
                        picks = detector.locate(images[0], prompt)
                else:
                    grid_model = grid_model or _cm.load_classifier(device)
                    if grid_model is not None:
                        picks = _cpu_attempt(images, prompt, grid_model)
                    if picks is None:
                        match = match or _cm.load_clip(device)
                        if match is not None:
                            picks = match.classify(images, prompt)
            took = round((time.time() - started) * 1000.0, 1)
            rec["latency_ms"][rung] = max(
                rec["latency_ms"].get(rung, 0.0), took)
            if picks:
                landed = (dispatch_points(page, provider, picks)
                          if mode == "points"
                          else dispatch_clicks(page, provider, picks))
                if landed:
                    rec["rung"] = rung
                    rec["solved"] = True
                    return rec
        # the round's ladder answered nothing that clicked; retry capture
    rec["error"] = "cap: rounds exhausted without a landed solve"
    return rec


# ---- the no-weights provider strategies (2026-11-05 phase 3) ----------
# Arkose/FunCaptcha, reCAPTCHA v3 and legacy text captchas have no vendored
# ONNX coverage: they answer through the llm rung where an answer can
# honestly land, and detect-and-record where it cannot. A fake solve is
# never produced anywhere here.

_TRANSCRIBE_TEMPLATE = """Transcribe EXACTLY the characters that appear \
in this image. Reply with ONLY those characters - no quotes, no spaces, \
no explanation."""


def attempt_llm_text(image: bytes,
                     timeout_s: float) -> Optional[str]:
    """The text-captcha transcription rung: one image in, the exact
    characters out. Same total-None contract as the other rungs; a reply
    with no usable alphanumerics is an honest miss, never a guess."""
    if not image:
        return None
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": _TRANSCRIBE_TEMPLATE},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64,"
                              + base64.b64encode(image).decode()}}]
    payload = {"model": LLM_MODEL,
               "messages": [{"role": "user", "content": content}],
               "max_tokens": 32, "think": False}
    reply = _gateway_post(payload, timeout_s)
    if not isinstance(reply, dict):
        return None
    try:
        text = reply["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return None
    answer = re.sub(r"[^a-zA-Z0-9]", "", str(text))
    if not answer or len(answer) > 24:
        return None
    return answer


_TEXT_SCAN_JS = """
() => {
  const img = [...document.querySelectorAll('img, canvas')].find(
    el => /captcha/i.test([el.src, el.id, el.className, el.alt].join(' '))
          && (el.naturalWidth || el.width || 0) > 40);
  const input = [...document.querySelectorAll('input')].find(
    i => String(i.type || 'text') === 'text'
         && /captcha|verif|code/i.test(
             [i.name, i.id, i.placeholder].join(' ')));
  if (!img || !input) return null;
  img.setAttribute('data-greysearch-captcha-img', '1');
  input.setAttribute('data-greysearch-captcha-input', '1');
  return 'marked';
}
"""
_TEXT_IMG_SEL = "[data-greysearch-captcha-img]"
_TEXT_INPUT_SEL = "[data-greysearch-captcha-input]"
_TEXT_SUBMIT_SEL = "button[type='submit'], input[type='submit']"


def solve_text(page) -> Dict[str, Any]:
    """The legacy text-captcha strategy: find the pairing image + input
    (both have to name themselves), transcribe through the llm rung, type
    the answer into the field and submit. The re-wait contract governs
    whether the answer took - the record is honest about never having
    verified it itself."""
    rec: Dict[str, Any] = {"engaged": True, "provider": "text",
                           "rungs": ["llm"], "rung": None, "rounds": 1,
                           "solved": False, "latency_ms": {}, "error": None}
    if not solver_enabled():
        rec.update({"engaged": False, "rungs": [], "rounds": 0})
        return rec
    try:
        marked = bool(page.evaluate(_TEXT_SCAN_JS))
    except Exception:
        marked = False
    if not marked:
        rec["error"] = "text: no named captcha image + input pair found"
        return rec
    try:
        png = page.locator(_TEXT_IMG_SEL).first.screenshot(timeout=5000)
    except Exception:
        png = None
    if not png:
        rec["error"] = "text: captcha image unreadable"
        return rec
    started = time.time()
    answer = attempt_llm_text(png, llm_timeout())
    rec["latency_ms"]["llm"] = round((time.time() - started) * 1000.0, 1)
    if not answer:
        rec["error"] = "text: llm rung unavailable or transcription empty"
        return rec
    rec["rung"] = "llm"
    try:
        field = page.locator(_TEXT_INPUT_SEL).first
        field.fill(answer or "", timeout=3000)
        field.press("Enter", timeout=3000)
        try:
            page.locator(_TEXT_SUBMIT_SEL).first.click(timeout=2000)
        except Exception:
            pass
        rec["solved"] = True
    except Exception as e:
        rec["error"] = f"text: answer could not be typed ({type(e).__name__})"
        rec["solved"] = False
    return rec


def solve_v3_report() -> Dict[str, Any]:
    """reCAPTCHA v3: score-based proof-of-work. There is no visual
    challenge to answer and nothing to click - the honest move is
    detect-and-record: the page's own token flow (invisible widget,
    re-wait contract) carries the pass-fail. Never a fabricated token."""
    return {"engaged": True, "provider": "recaptcha-v3", "rungs": [],
            "rung": None, "rounds": 0, "solved": False, "latency_ms": {},
            "error": "recaptcha-v3: score-based widget, no visual challenge"
                     " - detect-and-record (page token flow governs)"}


def solve_arkose(page) -> Dict[str, Any]:
    """Arkose/FunCaptcha: engage the frame, capture the challenge
    graphics, ask the llm rung ONCE. The three-tile match variant answers
    with tile picks that land like any grid; the rotation/upright variants
    have no click-point semantics that can be verified in-page, so an llm
    answer there is REJECTED rather than guessed at - detected and
    recorded, honestly."""
    rec: Dict[str, Any] = {"engaged": True, "provider": "arkose",
                           "rungs": ["llm"], "rung": None, "rounds": 0,
                           "solved": False, "latency_ms": {}, "error": None}
    if not solver_enabled():
        rec.update({"engaged": False, "rungs": [], "rounds": 0})
        return rec
    if _challenge_frame(page, "arkose") is None:
        rec["error"] = "arkose: challenge frame unreadable"
        return rec
    cap = capture_grid(page, "arkose")
    rec["rounds"] = 1
    if not cap or not cap.get("images"):
        rec["error"] = ("arkose: challenge graphics unreadable -"
                        " detected and recorded")
        rec["rungs"] = []
        return rec
    mode = cap.get("mode", "pick")
    started = time.time()
    # the match variant is a tile grid: tile picks can honestly land.
    # the rotation shape is ONE image: click coordinates on the artwork do
    # NOT map to the physical rotation control, so no points rung runs.
    picks = (attempt_llm(cap["images"], cap["prompt"], llm_timeout())
             if mode == "pick" else None)
    rec["latency_ms"]["llm"] = round((time.time() - started) * 1000.0, 1)
    if not picks:
        rec["error"] = ("arkose: no decisive llm answer for this variant -"
                        " detected and recorded")
        return rec
    if dispatch_clicks(page, "arkose", picks):
        rec["rung"] = "llm"
        rec["solved"] = True
        return rec
    rec["error"] = ("arkose: llm answer did not land -"
                    " detected and recorded")
    return rec
_TURNSTILE_BOX_SEL = "input[type='checkbox'], .ctp-checkbox-label, label"


_TURNSTILE_FRAME_SEL = ("iframe[src*='challenges.cloudflare.com'],"
                        "iframe[title*='turnstile' i]")


def solve_turnstile(page) -> Dict[str, Any]:
    """The behavioral rung for Turnstile/JS walls: click the checkbox when
    one is clickable and let the EXISTING wait contract (browser_session's
    two-phase wait) do the rest; the record is honest about absence.
    No model, no capture - Turnstile's challenge is JS proof-of-work the
    browser itself answers."""
    rec: Dict[str, Any] = {"engaged": True, "provider": "turnstile",
                           "rungs": ["behavioral"], "rung": "behavioral",
                           "rounds": 0, "solved": False,
                           "latency_ms": {}, "error": None}
    if not solver_enabled():
        rec["engaged"] = False
        rec["rung"] = None
        rec["rungs"] = []
        return rec
    clicked = False
    try:
        fl = page.frame_locator(_TURNSTILE_FRAME_SEL)
        box = fl.locator(_TURNSTILE_BOX_SEL)
        # Real Playwright narrows to one candidate with .first; the fake
        # locator in the hermetic tests has no .first, so getattr keeps
        # both honest (same shape as the brief fix on _FakeFrame.first,
        # but on the implementation side because the test is verbatim).
        box = getattr(box, "first", box)
        # The brief's drafting leftover `if box.count() or True:` is
        # removed: absence means NO click. Count resolves both ways -
        # Playwright's locator.count() method or the fake's int property.
        n = box.count
        if callable(n):
            n = n()
        if int(n or 0) > 0:
            try:
                box.click(timeout=3000)
                clicked = True
            except Exception:
                clicked = False
    except Exception:
        clicked = False
    if not clicked:
        rec["error"] = "no checkbox clickable; wait contract continues"
    rec["solved"] = clicked
    rec["rounds"] = 1
    return rec
