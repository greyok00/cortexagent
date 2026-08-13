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
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Session bridge: shared file between TUI and webui chat
from lib.session_bridge import SessionBridge
BRIDGE = SessionBridge()

# Import backend modules (self-contained: no external :8095 proxy needed)
from lib.config import CFG as _CFG  # noqa: E402
from lib.grammar_proxy import _get_metrics as _proxy_metrics  # noqa: E402
from lib.state_format import format_dashboard as _format_dashboard  # noqa: E402
from lib import overseer as _ov  # noqa: E402


# ── Config ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
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



# ── Template ──────────────────────────────────────────────────────────────
# HTML template loaded from disk (separate file for maintainability)
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets"
_TEMPLATE_PATH = _TEMPLATE_DIR / "webui_template.html"

def _load_template() -> str:
    """Load the HTML template from disk."""
    try:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _get_config() -> Dict:
    return {
        "enabled": os.environ.get("CORTEXAGENT_WEBUI_ENABLED", "1") != "0",
        "port": int(os.environ.get("CORTEXAGENT_WEBUI_PORT", str(DEFAULT_PORT))),
        "bind": os.environ.get("CORTEXAGENT_WEBUI_BIND", DEFAULT_BIND),
        "token": os.environ.get("CORTEXAGENT_WEBUI_TOKEN", "").strip(),
    }


def _check_auth(headers, path: str = "") -> bool:
    cfg = _get_config()
    if not cfg["token"]:
        return True
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == cfg["token"]:
        return True
    if headers.get("X-CortexAgent-Token", "").strip() == cfg["token"]:
        return True
    # Also accept token via URL query param (for EventSource compatibility)
    if path:
        try:
            from urllib.parse import parse_qs
            qs = parse_qs(urlparse(path).query)
            if qs.get("token") and qs["token"][0] == cfg["token"]:
                return True
        except Exception:
            pass
    return False


def _status_payload() -> Dict:
    """Collect real status from cortexagent's runtime state. Includes per-process
    VRAM, minify snapshot, proxy tok/s rates, and the active session identity
    so the HUD chip can show more than just `profile · model`."""
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
    # Extract last TUI response from session bridge
    last_response = ""
    try:
        lines = BRIDGE._path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            ev = json.loads(line.strip())
            if ev.get("type") == "response" and ev.get("from") == "tui":
                last_response = ev.get("content", "")
                break
    except Exception:
        pass
    # Live data: daemon + proxy snapshot
    daemon = _daemon_status()
    proxy = _proxy_metrics()
    return {
        "profile": profile,
        "model": model,
        "model_alias": str((daemon.get("big") or {}).get("alias") or model),
        "context_used_tokens": ctx_used,
        "context_max_tokens": ctx_max,
        "last_response": last_response,
        "proxy_up": bool(proxy),
        "current_in_tps": float(proxy.get("current_in_tps", 0.0) or 0.0),
        "current_out_tps": float(proxy.get("current_out_tps", 0.0) or 0.0),
        "vram_by_proc": (daemon.get("vram_by_proc") if isinstance(daemon, dict)
                         else {}) or {},
        "minify": (proxy.get("minify") if isinstance(proxy, dict) else {}) or {},
        "session": (daemon.get("session") if isinstance(daemon, dict) else {}) or {},
        "active_sessions": int((daemon or {}).get("active_sessions", 0) or 0),
        "timestamp": datetime.now().isoformat(),
    }


def _proxy_to_claude(message: str, profile: str = "default",
                     timeout: int = 300) -> Tuple[bool, str]:
    """Send a message to a claude-code subprocess and return (ok, response).

    Uses `claude -p <message>` non-interactively (no `--profile`: the installed
    claude build has no such flag and fails with "unknown option '--profile'").
    Falls back to a direct echo if claude isn't available or fails.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", message],
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


# ── State readers (replacing the missing tray-proxy backend) ────────────────
# These helpers were originally meant to forward to a tray chat backend on
# :8095 that no longer exists. They now read state directly from the daemon
# control socket, the grammar proxy /metrics, and the JSON files the overseer
# writes to ~/.cortexagent/*.json — so the webui works standalone.

import urllib.error  # noqa: E402  (used by /api/tps, /api/overseer readers)
import urllib.request as _urlreq  # noqa: E402
from lib import control as _ctl  # noqa: E402

_PROXY_URL = f"http://127.0.0.1:{os.environ.get('CORTEXAGENT_PROXY_PORT', '8081')}"
_STATE_DIR = Path.home() / ".cortexagent"
_DAEMON_TIMEOUT = 2.0      # seconds — status reads must stay snappy
_PROXY_TIMEOUT = 1.5       # seconds — /metrics must NEVER hang the UI


def _read_json(path: Path, default=None):
    """Tiny helper: read a JSON file or return ``default`` on any failure."""
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8") or "null")
    except Exception:
        return default


def _daemon_status() -> Dict:
    """Query the daemon control socket for status. Returns {} on any failure."""
    try:
        return _ctl.send_request("status", timeout=_DAEMON_TIMEOUT) or {}
    except Exception:
        return {}


def _proxy_metrics() -> Dict:
    """Fetch /metrics from the grammar proxy. Returns {} on any failure."""
    try:
        with _urlreq.urlopen(f"{_PROXY_URL}/metrics", timeout=_PROXY_TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _gpu_vram() -> Dict[str, int]:
    """Whole-GPU memory read (used/free/total MiB) for the dashboard's VRAM
    card. Falls back to {} when nvidia-smi is missing. Daemon-supplied
    vram_by_proc is preferred — this only runs when that's not in the payload."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return {}
        used, free, total = (int(x.strip()) for x in out.stdout.strip().split(",")[:3])
        return {"used_mb": used, "free_mb": free, "total_mb": total}
    except Exception:
        return {}


def _systemd_units() -> Tuple[Dict[str, bool], Dict[str, int]]:
    """systemctl --user is-active + Main PID for the cortexagent services."""
    units = {"cortexagent.service": False, "cortexagent-overseer.service": False,
             "cortexagent-tray.service": False}
    pids: Dict[str, int] = {}
    for unit in list(units.keys()):
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", unit],
                               capture_output=True, text=True, timeout=1.5)
            units[unit] = (r.stdout.strip() == "active")
            rp = subprocess.run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"],
                                capture_output=True, text=True, timeout=1.5)
            pid_s = rp.stdout.strip()
            if pid_s.isdigit():
                pids[unit] = int(pid_s)
        except Exception:
            pass
    return units, pids


def _active_cortexagent_procs() -> List[Dict]:
    """Inventory ONLY our own local stack — NEVER generic claude / ollama.

    Match signals (must hit one):
      comm == ``llama-server`` with ``--port 8080`` (big) or ``--port 8082`` (tiny)
      cmdline contains  ``/lib/daemon.py``
      cmdline contains  ``/lib/overseer.py``
      cmdline contains  ``/lib/grammar_proxy.py``
      cmdline contains  ``/lib/webui.py``
      cmdline contains  ``/lib/diffusion_backend.py``

    Anything else (third-party ``claude``, ``ollama launch …``, the MCP
    bridge process, ad-hoc shells) is deliberately ignored — the user runs
    their own claude on a cloud model and we must not claim ownership of it.
    """
    out: List[Dict] = []
    try:
        ps = subprocess.run(["ps", "-eo", "pid,etime,comm,args"],
                            capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return out
    seen: set = set()

    def _emit(pid_i: int, etime: str, kind: str, cmdline: str) -> None:
        if pid_i in seen:
            return
        seen.add(pid_i)
        secs = 0
        try:
            seg = etime.split("-")
            if len(seg) == 2:
                secs = int(seg[0]) * 86400 + sum(int(x) * m
                                                 for x, m in zip(seg[1].split(":"), [3600, 60, 1]))
            else:
                secs = sum(int(x) * m for x, m in zip(seg[0].split(":"), [3600, 60, 1]))
        except Exception:
            secs = 0
        out.append({"pid": pid_i, "uptime_s": secs, "kind": kind, "cmd": cmdline[:160]})

    for line in ps.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        pid_s, etime, comm, args = parts
        if not args:
            continue
        try:
            pid_i = int(pid_s)
        except ValueError:
            continue
        matched = False
        if comm == "llama-server":
            if "--port 8080" in args or "--port=8080" in args:
                _emit(pid_i, etime, "big", args); matched = True
            elif "--port 8082" in args or "--port=8082" in args:
                _emit(pid_i, etime, "tiny", args); matched = True
        if matched:
            continue
        for marker, kind in (
            ("/lib/daemon.py",            "daemon"),
            ("/lib/overseer.py",          "overseer"),
            ("/lib/grammar_proxy.py",     "proxy"),
            ("/lib/webui.py",             "webui"),
            ("/lib/diffusion_backend.py", "diffusion"),
        ):
            if marker in args:
                _emit(pid_i, etime, kind, args)
                break
    return out[:8]


def _log_tail(path: Path, lines: int = 25) -> List[str]:
    """Tail the last N lines of a log file (bounded I/O)."""
    try:
        if not path.exists():
            return []
        # Read the tail cheaply — open in binary, seek to ~last 64KB, split.
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 65536))
            data = f.read().decode("utf-8", "replace")
        return data.splitlines()[-lines:]
    except Exception:
        return []


# ── JSON endpoint builders (the MISSING helpers) ────────────────────────────

def _api_state() -> Dict:
    """{models, active_model, tabs} — front-end schema at webui_template.html:672."""
    models: List[Dict] = []
    # Big model from CFG (no fallback swap — only one model on :8080)
    big_alias = str(_CFG.big_alias) if hasattr(_CFG, "big_alias") else "cortexagent"
    big_name = (str(_CFG.big_model).rsplit("/", 1)[-1]
                if hasattr(_CFG, "big_model") else "big")
    models.append({"id": big_alias, "name": big_name, "kind": "chat",
                   "alias": big_alias})
    # Image / video model slots
    models.append({"id": "image", "name": "Image (diffusion)", "kind": "image"})
    models.append({"id": "video", "name": "Video (LTX)", "kind": "video"})
    active_path = _STATE_DIR / "state" / "active_model.json"
    active = _read_json(active_path, default={"model": big_alias})
    if not isinstance(active, dict):
        active = {"model": big_alias}
    return {
        "models": models,
        "active_model": str(active.get("model") or big_alias),
        "tabs": [
            {"value": "cortexagent", "label": big_name.split("-")[0] or "Cortex",
             "short": "Cx", "icon": "🧠"},
            {"value": "image", "label": "Image", "short": "Img", "icon": "🎨"},
            {"value": "video", "label": "Video", "short": "Vid", "icon": "🎬"},
        ],
    }


def _api_models() -> List[Dict]:
    """Flat list of model entries for /api/models (legacy front-end field)."""
    return _api_state().get("models", [])


def _api_tps() -> Dict:
    """Tok/s + VRAM proxy snapshot. proxy_up=false when the proxy is down so
    the HUD can render the offline chip."""
    m = _proxy_metrics()
    return {
        "proxy_up": bool(m),
        "current_tok_s": float(m.get("current_out_tps",
                                     m.get("current_tok_s", 0.0)) or 0.0),
        "current_in_tps": float(m.get("current_in_tps", 0.0) or 0.0),
        "current_out_tps": float(m.get("current_out_tps", 0.0) or 0.0),
        "avg_tok_s": float(m.get("avg_out_tps",
                                  m.get("avg_tok_s", 0.0)) or 0.0),
        "avg_in_tps": float(m.get("avg_in_tps", 0.0) or 0.0),
        "avg_out_tps": float(m.get("avg_out_tps", 0.0) or 0.0),
        "avg15m_tok_s": float(m.get("avg_tok_s", 0.0) or 0.0),  # alias for FE
        "requests": int(m.get("requests", 0) or 0),
        "prompt_tokens": int(m.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(m.get("completion_tokens", 0) or 0),
        "total_tokens": int(m.get("total_tokens", 0) or 0),
        "vram_used_mib": int(m.get("vram_used_mib", 0) or 0),
        "vram_total_mib": int(m.get("vram_total_mib", 0) or 0),
        "minify": m.get("minify") or {},
        "sessions": m.get("sessions") or {},
        "started_at": m.get("started_at"),
        "last_request_ts": float(m.get("last_request_ts", 0.0) or 0.0),
    }


def _api_overseer() -> Dict:
    """Merged dashboard payload — composes daemon + overseer + proxy + disk
    state into the NESTED schema the front-end's makeCards(j) consumes (see
    webui_template.html:988). The earlier implementation returned a flat
    bundle (mostly `_format_dashboard()` keys) plus a `logs` overlay, leaving
    every card reading `undefined`. We build the nested shape directly from
    the same backing files; `/status` provides vram_by_proc / minify / tps
    that the JS merges in via `{ ...ovR, ...stR }`.
    """
    daemon = _daemon_status()
    proxy = _proxy_metrics()
    ov_state = _read_json(_STATE_DIR / "overseer_state.json", default={}) or {}
    steps_state = _read_json(_STATE_DIR / "big_model_steps.json", default={}) or {}
    minify = (proxy.get("minify") if isinstance(proxy, dict) else {}) or {}

    queue = _read_json(_STATE_DIR / "overseer_queue.json", default=[]) or []
    schedule = _read_json(_STATE_DIR / "overseer_schedule.json", default=[]) or []
    pq = _read_json(_STATE_DIR / "prompt_queue.json", default={}) or {}
    wf = _read_json(_STATE_DIR / "workflow_state.json", default={}) or {}
    plan = _read_json(_STATE_DIR / "overseer_plan.json", default={}) or {}

    units, unit_pids = _systemd_units()
    vbp = (daemon.get("vram_by_proc") if isinstance(daemon.get("vram_by_proc"), dict)
           else {})
    gv = _gpu_vram() or {}
    used_mb = (int(vbp.get("big_mib", 0)) + int(vbp.get("tiny_mib", 0))
               + int(vbp.get("other_mib", 0))) if vbp else int(gv.get("used_mb", 0))
    total_mb = int(gv.get("total_mb", 0)) if vbp else int(gv.get("total_mb", 0))
    free_mb = int(gv.get("free_mb", 0)) if vbp else int(gv.get("free_mb", 0))
    vram_card = {
        "used_mb": used_mb,
        "free_mb": free_mb,
        "total_mb": total_mb,
        "big_mb": int(vbp.get("big_mib", 0)) if vbp else 0,
        "tiny_mb": int(vbp.get("tiny_mib", 0)) if vbp else 0,
        "other_mb": int(vbp.get("other_mib", 0)) if vbp else 0,
        "by_pid": vbp.get("by_pid", []) if vbp else [],
    }

    pending = sum(1 for q in queue
                  if isinstance(q, dict) and q.get("status") == "pending")
    overseer_card = {
        "running": bool(units.get("cortexagent-overseer.service", False)),
        "pid": unit_pids.get("cortexagent-overseer.service"),
        "started_at": ov_state.get("started_at"),
        "ticks": ov_state.get("total_ticks"),
        "model": str((daemon.get("big") or {}).get("alias", "")),
        "memory": ov_state.get("memory") or {},
        "last_compact": ov_state.get("last_compact"),
        "last_distill": ov_state.get("last_distill"),
        "queue": ov_state.get("queue") or {"total": len(queue), "pending": pending},
        "schedule_entries": len(schedule),
        "last_llm_summary": ov_state.get("last_llm_summary"),
    }
    daemon_card = {
        "big": daemon.get("big") or {},
        "tiny": daemon.get("tiny") or {},
        "proxy": daemon.get("proxy") or {},
        "active_sessions": daemon.get("active_sessions", 0),
        "idle_sec": daemon.get("idle_sec"),
        "idle_unload_sec": daemon.get("idle_unload_sec"),
        "sessions": daemon.get("sessions") or [],
        "session": daemon.get("session") or {},
        "model_alias": daemon.get("model_alias") or "",
        "profile": daemon.get("profile") or "",
        "vram_by_proc": vbp,
    }
    logs = {
        "overseer": _log_tail(_STATE_DIR / "logs" / "overseer.log"),
        "daemon": _log_tail(_STATE_DIR / "logs" / "daemon.log"),
    }
    return {
        "overseer": overseer_card,
        "daemon": daemon_card,
        "vram": vram_card,
        "queue": queue,
        "schedule": schedule,
        "workflow": wf,
        "plan": plan,
        "prompt_queue": pq if isinstance(pq, dict) else {"items": pq},
        "health_events": ov_state.get("health_events") or [],
        "config": _read_json(_STATE_DIR / "cortexagent.conf", default={}) or {},
        "constants": ov_state.get("constants") or {},
        "processes": _active_cortexagent_procs(),
        "ollama_loaded": [],
        "logs": logs,
        "units": units,
        "unit_pids": unit_pids,
        "minify": minify,
        "steps": steps_state,
        "proxy": {
            "running": bool(proxy),
            "sessions": proxy.get("sessions") or {},
            "current_tok_s": float(proxy.get("current_out_tps",
                                             proxy.get("current_tok_s", 0.0)) or 0.0),
            "current_in_tps": float(proxy.get("current_in_tps", 0.0) or 0.0),
            "current_out_tps": float(proxy.get("current_out_tps", 0.0) or 0.0),
            "vram_used_mib": int(proxy.get("vram_used_mib", 0) or 0),
            "vram_total_mib": int(proxy.get("vram_total_mib", 0) or 0),
        },
        "timestamp": datetime.now().isoformat(),
    }


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
        if not _check_auth(self.headers, self.path):
            self._send_json(401, {"ok": False, "reason": "auth required"})
            return False
        return True

    def _handle_webui_send(self) -> None:
        """POST /webui-send: forward a webui message to TUI via session bridge."""
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
        # Write to session bridge — TUI picks it up and responds.
        # `username=User` lets the chat pane render this under the user
        # regardless of which UI typed it.
        ev = {
            "id": str(uuid.uuid4()),
            "username": "User",
            "type": "message",
            "content": message,
            "ts": datetime.now().isoformat(),
            "seq": 0,  # TUI assigns seq
        }
        BRIDGE.write("webui", ev)

        # If TUI is not running, fall back to direct claude call so webui works standalone
        agent = os.environ.get("CORTEXAGENT_CLI", "claude")
        try:
            result = subprocess.run(
                [agent, "-p", message],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                resp = result.stdout.strip()
                resp_ev = {
                    "id": str(uuid.uuid4()),
                    "from": "tui",
                    "username": "Big Model",
                    "type": "response",
                    "content": resp,
                    "ts": datetime.now().isoformat(),
                    "seq": 0,
                }
                BRIDGE.write("tui", resp_ev)
                return self._send_json(200, {"ok": True, "response": resp})
            else:
                resp = result.stderr.strip() or f"exit {result.returncode}"
                self._send_json(200, {"ok": False, "response": resp, "reason": resp})
                return
        except FileNotFoundError:
            # claude not available — still try TUI bridge (might be running elsewhere)
            self._send_json(200, {"ok": True, "id": ev["id"]})
            return
        except subprocess.TimeoutExpired:
            self._send_json(200, {"ok": True, "id": ev["id"]})
            return
        except Exception:
            # Non-critical — still let SSE carry the response
            self._send_json(200, {"ok": True, "id": ev["id"]})
            return

    # ── Backend dispatch helpers (replaces the dead tray-proxy stubs) ─────
    #
    # Each one is a real implementation now — the original `_tray_fetch` /
    # `_tray_stream` were meant to proxy to a tray chat backend on :8095 that
    # doesn't exist in this deployment. We dispatch by path to the right
    # backend: daemon control socket, in-process diffusion, local filesystem,
    # or the grammar proxy :8081 for chat (with shared session-id header).

    _MEDIA_DIR = _STATE_DIR / "media"
    _UPLOAD_DIR = _STATE_DIR / "state" / "uploads"
    _MEDIA_MIME = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".txt": "text/plain; charset=utf-8", ".json": "application/json",
    }

    def _stream_ndjson(self, gen) -> None:
        """Open a 200 NDJSON stream and yield each generator item as one JSON
        line. Closes cleanly on client disconnect."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for obj in gen:
                self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.wfile.write((json.dumps({"error": str(e)}) + "\n").encode())
                self.wfile.flush()
            except Exception:
                pass

    def _handle_tray_post(self, path: str) -> None:
        """Dispatch buffered POST handlers: /api/active, /api/schedule/*."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"ok": False, "reason": f"parse error: {e}"})
            return
        if path == "/api/active":
            # Persist active model pointer so the next chat knows what to use.
            try:
                model = str(body.get("model") or "").strip()
                if not model:
                    self._send_json(400, {"ok": False, "reason": "missing model"})
                    return
                out_path = (_STATE_DIR / "state" / "active_model.json")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = out_path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"model": model, "ts": time.time()}))
                os.replace(tmp, out_path)
                self._send_json(200, {"ok": True, "model": model})
            except Exception as e:
                self._send_json(500, {"ok": False, "reason": str(e)})
            return
        if path in ("/api/schedule/add", "/api/schedule/remove"):
            self._handle_schedule(path, body)
            return
        self._send_json(404, {"ok": False, "reason": "not found"})

    def _handle_tray_stream(self, path: str) -> None:
        """Dispatch NDJSON streamers: /api/chat, /api/image, /api/video, /api/load."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"ok": False, "reason": f"parse error: {e}"})
            return
        if path == "/api/chat":
            self._handle_chat_stream(body)
            return
        if path == "/api/image":
            self._stream_ndjson(self._gen_diffusion(body, kind="image"))
            return
        if path == "/api/video":
            self._stream_ndjson(self._gen_diffusion(body, kind="video"))
            return
        if path == "/api/load":
            self._stream_ndjson(self._gen_load(body))
            return
        self._send_json(404, {"ok": False, "reason": "not found"})

    def _handle_tray_upload(self, path: str) -> None:
        """POST /api/upload (multipart): persist files to ~/.cortexagent/state/uploads/
        and return per-file metadata so the chat composer can inline text and
        attach images via /media/."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        ctype = self.headers.get("Content-Type", "")
        boundary = None
        if "boundary=" in ctype:
            boundary = "--" + ctype.split("boundary=", 1)[1].split(";", 1)[0].strip()
        if not boundary:
            self._send_json(400, {"ok": False, "reason": "multipart required"})
            return
        body = self.rfile.read(length)
        try:
            self._UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            files_out: List[Dict] = []
            parts = body.split(boundary.encode())
            text_exts = {".txt", ".md", ".py", ".json", ".csv", ".log",
                         ".yaml", ".yml", ".toml", ".ini", ".sh", ".html", ".xml"}
            for p in parts:
                if not p or p.strip() in (b"", b"--"):
                    continue
                if b"\r\n\r\n" not in p:
                    continue
                head, _, data = p.partition(b"\r\n\r\n")
                # Drop trailing \r\n
                if data.endswith(b"\r\n"):
                    data = data[:-2]
                # Parse Content-Disposition
                name = ""
                fname = ""
                for hl in head.split(b"\r\n"):
                    hl_l = hl.lower()
                    if hl_l.startswith(b"content-disposition"):
                        # form-data; name="…"; filename="…"
                        for tok in hl.decode("utf-8", "replace").split(";"):
                            tok = tok.strip()
                            if tok.startswith('name='):
                                name = tok.split("=", 1)[1].strip('"')
                            elif tok.startswith('filename='):
                                fname = tok.split("=", 1)[1].strip('"')
                        break
                if not fname:
                    continue
                # Sanitize filename — strip path traversal
                safe = Path(fname).name or f"upload-{int(time.time())}"
                dst = self._UPLOAD_DIR / safe
                # Disambiguate on collision
                i = 1
                while dst.exists():
                    stem = Path(safe).stem
                    ext = Path(safe).suffix
                    dst = self._UPLOAD_DIR / f"{stem}-{i}{ext}"
                    i += 1
                dst.write_bytes(data)
                ext = Path(safe).suffix.lower()
                kind = ("image" if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")
                        else "video" if ext in (".mp4", ".webm", ".mov")
                        else "text" if ext in text_exts
                        else "binary")
                content_preview = None
                if kind == "text" and len(data) <= 200_000:
                    try:
                        content_preview = data.decode("utf-8", "replace")
                    except Exception:
                        content_preview = None
                files_out.append({
                    "name": dst.name,
                    "url": f"/media/{dst.name}",
                    "kind": kind,
                    "size": len(data),
                    "content": content_preview,
                })
            self._send_json(200, {"ok": True, "files": files_out})
        except Exception as e:
            self._send_json(500, {"ok": False, "reason": str(e)})

    def _handle_stt(self) -> None:
        """POST /api/stt — raw audio body → {ok, text}. Transcribes + cleans."""
        import tempfile
        from lib import stt
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid audio size"})
            return
        audio = self.rfile.read(length)
        tmp = Path(tempfile.gettempdir()) / f"stt_{int(time.time())}.webm"
        tmp.write_bytes(audio)
        try:
            text = stt.transcribe_and_cleanup(tmp)
        except Exception as e:
            self._send_json(500, {"ok": False, "reason": str(e)})
            return
        finally:
            tmp.unlink(missing_ok=True)
        self._send_json(200, {"ok": True, "text": text})

    def _handle_tray_media(self, path: str) -> None:
        """Serve files from the upload dir AND generated media."""
        rel = path[len("/media/"):]
        base = (self._UPLOAD_DIR.resolve()
                if "upload" in rel
                else self._MEDIA_DIR.resolve())
        # Try both dirs — uploads/ first, then media/
        candidates = [self._UPLOAD_DIR / rel, self._MEDIA_DIR / rel]
        target = None
        for c in candidates:
            try:
                c_resolved = c.resolve()
                # Confine each base
                for b in (self._UPLOAD_DIR.resolve(), self._MEDIA_DIR.resolve()):
                    if b in c_resolved.parents and c_resolved.is_file():
                        target = c_resolved
                        break
                if target:
                    break
            except Exception:
                continue
        if not target:
            self._send_json(404, {"ok": False, "reason": "not found"})
            return
        ext = target.suffix.lower()
        mime = self._MEDIA_MIME.get(ext, "application/octet-stream")
        try:
            data = target.read_bytes()
        except Exception as e:
            self._send_json(500, {"ok": False, "reason": str(e)})
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _handle_chat_stream(self, body: Dict) -> None:
        """POST /api/chat → stream NDJSON chunks from the grammar proxy.

        The proxy is the shared session chokepoint: every CLI message already
        passes through it, so we POST the webui message to it with the same
        OpenAI shape (and the same session-id header) the CLI uses. The proxy
        forwards to llama-server and streams SSE back; we re-shape SSE into
        NDJSON {message:{content,thinking},error} per chunk so the front-end
        can render incrementally."""
        msgs = body.get("messages") or []
        if not isinstance(msgs, list) or not msgs:
            self._send_json(400, {"ok": False, "reason": "messages required"})
            return
        # Pull the active session id from the daemon so CLI + webui share
        # the same proxy context. Falls back to a uuid if no live CLI session.
        session_id = ""
        try:
            ds = _daemon_status()
            sess = ds.get("session") or {}
            session_id = str(sess.get("pid") or "")
        except Exception:
            pass
        if not session_id:
            session_id = f"webui-{uuid.uuid4().hex[:12]}"

        # Build OpenAI chat completion request (stream=true)
        proxy_body = json.dumps({
            "model": str((_daemon_status().get("big") or {}).get("alias") or "cortexagent"),
            "messages": msgs,
            "stream": True,
            "temperature": float(body.get("temperature", 0.7) or 0.7),
        }).encode("utf-8")

        def _gen():
            try:
                req = _urlreq.Request(
                    f"{_PROXY_URL}/v1/chat/completions",
                    data=proxy_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-CortexAgent-Session": session_id,
                        "X-CortexAgent-Origin": "webui",
                    },
                    method="POST",
                )
                with _urlreq.urlopen(req, timeout=300) as resp:
                    for raw in resp:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            yield {"done": True}
                            return
                        try:
                            j = json.loads(payload)
                        except Exception:
                            continue
                        choice = (j.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield {"message": {"content": content,
                                               "thinking": bool(delta.get("thinking"))}}
            except _urlreq.error.HTTPError as e:
                yield {"error": f"proxy {e.code}: {e.reason}"}
            except Exception as e:
                yield {"error": str(e)}
            finally:
                # Mirror the response into the session bridge so the SSE stream
                # at /webui-events picks it up and the CLI side sees the same
                # message (and vice versa). `username=Big Model` so the chat
                # pane labels this as the model's voice.
                try:
                    BRIDGE.write("webui", {
                        "id": str(uuid.uuid4()),
                        "username": "Big Model",
                        "type": "response_done",
                        "content": "",
                        "ts": datetime.now().isoformat(),
                        "seq": 0,
                    })
                except Exception:
                    pass

        self._stream_ndjson(_gen())

    def _gen_diffusion(self, body: Dict, kind: str):
        """NDJSON generator wrapping in-process diffusion_backend.gen_image /
        gen_video. Yields {status: "…"} progress events and a final {url,
        media} when the file lands on disk."""
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            yield {"error": "prompt required"}
            return
        # Lazy-import — torch/diffusers are heavy and the webui shouldn't
        # pay the cost unless someone actually clicks Generate.
        try:
            from lib import diffusion_backend as _db
        except Exception as e:
            yield {"error": f"diffusion backend unavailable: {e}"}
            return
        try:
            yield {"status": f"checking {kind} backend…"}
            if not _db.is_running(timeout=3):
                yield {"status": "loading diffusion backend (first run, ~30s)…"}
            ext = ".mp4" if kind == "video" else ".png"
            self._MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            out = self._MEDIA_DIR / f"{kind}-{ts}{ext}"
            yield {"status": "generating…"}
            if kind == "image":
                ok = _db.gen_image(prompt, output=str(out),
                                   timeout=int(body.get("timeout") or 600))
            else:
                ok = _db.gen_video(prompt, output=str(out),
                                   timeout=int(body.get("timeout") or 1200))
            if ok and out.exists():
                yield {"status": "done", "url": f"/media/{out.name}",
                       "media": kind}
            else:
                yield {"error": f"{kind} generation failed (check ~/.cortexagent/logs/diffusion.log)"}
        except Exception as e:
            yield {"error": str(e)}

    def _gen_load(self, body: Dict):
        """NDJSON generator that triggers a model load via the daemon control
        socket and polls status until ready."""
        which = str(body.get("which") or "big")
        model = body.get("model")
        yield {"status": f"requesting {which} load…"}
        try:
            params: Dict[str, Any] = {"which": which}
            if model:
                params["model"] = str(model)
            r = _ctl.send_request("load", timeout=3, **params)
            yield {"status": f"load triggered: {json.dumps(r)[:120]}"}
            # Poll for up to 60s waiting for healthy
            for i in range(60):
                time.sleep(1.0)
                s = _daemon_status()
                b = (s.get("big") or {}) if which == "big" else (s.get("tiny") or {})
                if b.get("healthy") and b.get("running"):
                    yield {"status": "ready", "model": b.get("model"),
                           "alias": b.get("alias")}
                    return
                if i % 5 == 4:
                    yield {"status": f"waiting… ({i + 1}s)"}
            yield {"error": "load timeout (60s)"}
        except Exception as e:
            yield {"error": str(e)}

    def _handle_schedule(self, path: str, body: Dict) -> None:
        """POST /api/schedule/{add,remove} → subprocess to lib.overseer.

        Maps the front-end's flat body schema (schedule_type="every", value
        "1h") to the overseer's flag-based subcommand: `overseer schedule
        add --name X --cron|--daily|--weekly|--date V [--prompt|--command Y]`.
        """
        try:
            cmd_args = ["python3", "-m", "lib.overseer", "schedule"]
            if path == "/api/schedule/add":
                name = str(body.get("name") or "").strip()
                if not name:
                    self._send_json(400, {"ok": False, "reason": "name required"})
                    return
                sched_type = str(body.get("schedule_type") or "every").lower()
                sched_val = str(body.get("schedule_value") or "1h")
                cmd_args += ["add", "--name", name]
                # The overseer recognises these four --<type>=V flag forms.
                # Anything else falls back to --cron (which accepts the value
                # verbatim — "every 1h" works as cron syntax too).
                flag = {"cron": "--cron", "daily": "--daily",
                        "weekly": "--weekly", "date": "--date"}.get(sched_type)
                if flag:
                    cmd_args += [flag, sched_val]
                else:
                    cmd_args += ["--cron", sched_val]
                if body.get("prompt"):
                    cmd_args += ["--prompt", str(body["prompt"])]
                if body.get("command"):
                    cmd_args += ["--command", str(body["command"])]
            else:
                name = str(body.get("name") or "").strip()
                if not name:
                    self._send_json(400, {"ok": False, "reason": "name required"})
                    return
                cmd_args += ["remove", name]
            r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=15,
                               cwd=str(_REPO_ROOT))
            ok = (r.returncode == 0)
            self._send_json(200 if ok else 500,
                            {"ok": ok, "message": (r.stdout or r.stderr).strip()[:300]})
        except Exception as e:
            self._send_json(500, {"ok": False, "reason": str(e)})

    def do_GET(self):
        parsed = urlparse(self.path)
        # ── SSE stream for webui chat events ──────────────────────────────────
        if parsed.path == "/webui-events":
            self._handle_events()
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "cortexagent-webui"})
            return
        if parsed.path in ("/", "/index.html"):
            self._send_html(_load_template())
            return
        if parsed.path == "/status":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _status_payload())
            return
        # ── Merged UI: local API endpoints (no tray proxy) ──────────────────
        if parsed.path == "/api/state":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _api_state())
            return
        if parsed.path == "/api/tps":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _api_tps())
            return
        if parsed.path == "/api/overseer":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _api_overseer())
            return
        if parsed.path == "/api/models":
            if not self._check_auth_or_401():
                return
            self._send_json(200, _api_models())
            return
        if parsed.path.startswith("/media/"):
            self._handle_tray_media(parsed.path)
            return
        if parsed.path == "/assets/logo":
            self._send_logo()
            return
        if parsed.path.startswith("/static/"):
            self._send_static(parsed.path[len("/static/"):])
            return
        self._send_json(404, {"ok": False, "reason": "not found"})

    # ── SSE event streaming ────────────────────────────────────────────────
    def _handle_events(self):
        """SSE endpoint: stream session bridge events to the webui frontend.

        Reads ALL bridge events (origin=None) — the webui shows every voice in
        the unified session (you, big model, overseer) under their `username`.
        Events we authored (origin=webui) are echoed so the chat pane can
        render the local user's own message immediately; the front-end
        dedupes by event id so we don't double-print.
        """
        if not self._check_auth_or_401():
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        cursor = 0
        last_heartbeat = time.time()
        try:
            # Initial tail — replay last 50 events so the page renders history.
            for ev in BRIDGE.tail(50):
                try:
                    self.wfile.write(f"data: {json.dumps(ev, separators=(',', ':'))}\n\n".encode())
                except Exception:
                    return
                cursor += 1
            self.wfile.flush()
            # Mark our cursor so we only stream NEW events from this point on.
            cursor = BRIDGE.mark_read("webui", cursor) if hasattr(BRIDGE, "mark_read") else cursor

            seen_ids = {ev.get("id") for ev in (BRIDGE.tail(50) or []) if ev.get("id")}
            while True:
                new_events = BRIDGE.read_new(None)  # ALL origins (unified session)
                if new_events:
                    for ev in new_events:
                        eid = ev.get("id")
                        if eid and eid in seen_ids:
                            continue
                        if eid:
                            seen_ids.add(eid)
                        try:
                            self.wfile.write(f"data: {json.dumps(ev, separators=(',', ':'))}\n\n".encode())
                        except Exception:
                            return
                    cursor += len(new_events)
                    last_heartbeat = time.time()
                elif time.time() - last_heartbeat > 15:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        last_heartbeat = time.time()
                    except Exception:
                        break
                try:
                    self.wfile.flush()
                except Exception:
                    break
                time.sleep(2)
        except Exception:
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        # ── Session send: webui → TUI message forward ────────────────────────
        if parsed.path == "/webui-send":
            self._handle_webui_send()
            return
        # ── Merged UI: proxy tray endpoints (chat/active/image/video) ───────
        if parsed.path == "/api/active":
            if not self._check_auth_or_401():
                return
            self._handle_tray_post(parsed.path)
            return
        if parsed.path in ("/api/schedule/add", "/api/schedule/remove"):
            if not self._check_auth_or_401():
                return
            self._handle_tray_post(parsed.path)
            return
        if parsed.path == "/api/upload":
            if not self._check_auth_or_401():
                return
            self._handle_tray_upload(parsed.path)
            return
        if parsed.path == "/api/stt":
            if not self._check_auth_or_401():
                return
            self._handle_stt()
            return
        if parsed.path in ("/api/chat", "/api/image", "/api/video", "/api/load"):
            if not self._check_auth_or_401():
                return
            self._handle_tray_stream(parsed.path)
            return
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
            assert "CORTEXAGENT" in body
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
