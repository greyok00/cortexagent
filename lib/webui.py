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
from lib import overseer as _ov  # noqa: E402


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
    return {
        "profile": profile,
        "model": model,
        "context_used_tokens": ctx_used,
        "context_max_tokens": ctx_max,
        "last_response": last_response,
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
        # Write to session bridge — TUI picks it up and responds
        ev = {
            "id": str(uuid.uuid4()),
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
                    "id": ev["id"],
                    "from": "tui",
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

    def _handle_tray_get(self, path: str) -> None:
        """Buffered proxy for a tray JSON endpoint (GET)."""
        status, headers, data = _tray_fetch(path)
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_tray_post(self, path: str) -> None:
        """Buffered proxy for a tray JSON endpoint (POST)."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        body = self.rfile.read(length)
        status, headers, data = _tray_fetch(path, method="POST", body=body)
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_tray_stream(self, path: str) -> None:
        """Streaming proxy for NDJSON endpoints (/api/chat, /api/image, /api/video)."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        body = self.rfile.read(length)
        try:
            chunks = _tray_stream(path, method="POST", body=body)
        except IOError as e:
            self._send_json(502, {"ok": False, "reason": str(e)})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_tray_upload(self, path: str) -> None:
        """Raw multipart passthrough to the tray (/api/upload) — forwards the
        incoming Content-Type (incl. boundary) and body bytes unchanged."""
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
            self._send_json(400, {"ok": False, "reason": "invalid body"})
            return
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "application/octet-stream")
        status, headers, data = _tray_fetch(path, method="POST", body=body, content_type=ctype, timeout=120)
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_tray_media(self, path: str) -> None:
        """Proxy binary media (generated images/videos) from the tray."""
        status, headers, data = _tray_fetch(path, timeout=30)
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

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
        """SSE endpoint: stream session bridge events to the webui frontend."""
        if not self._check_auth_or_401():
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_seq = 0
        start = time.time()
        try:
            while True:
                # Read current file
                try:
                    lines = BRIDGE._path.read_text(encoding="utf-8").splitlines()
                except Exception:
                    lines = []
                new_events = [l for l in lines[last_seq:] if l.strip()]
                for line in new_events:
                    try:
                        self.wfile.write(f"data: {line}\n\n".encode())
                    except Exception:
                        return
                last_seq = max(last_seq, len(lines))

                # Heartbeat every 15s (in case client dies)
                if time.time() - start > 15:
                    self.wfile.write(b": heartbeat\n\n")
                    start = time.time()

                # Wait for new events (poll every 2s)
                try:
                    self.wfile.flush()
                except Exception:
                    break
                time.sleep(2)
        except Exception:
            pass
        finally:
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
