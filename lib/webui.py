#!/usr/bin/env python3
"""webui — minimal HTTP UI for cortexagent.

Stdlib only (http.server). Mobile-friendly HTML. Endpoints:

  GET  /            — HTML chat interface
  POST /message     — Send a message (proxies to claude-code subprocess)
  GET  /status      — JSON: profile, model, context, current task
  GET  /health      — Quick liveness

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
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse


# ── Config ────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8090
DEFAULT_BIND = "127.0.0.1"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "cortexagentsquarelogo.jpg"
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CORTEXAGENT</title>
<style>
  /* ── Design Tokens (UI Framework — Luxury Brand Audit) ── */
  :root {
    --bg-primary: #000000;
    --bg-secondary: #0A0A0A;
    --bg-tertiary: #141414;
    --surface: #1A1A1A;
    --text-primary: #FFFFFF;
    --text-secondary: #A0A0A0;
    --text-tertiary: #666666;
    --accent: #C9A84C;
    --accent-hover: #D4B85C;
    --border: rgba(128,128,128,0.15);
    --border-strong: rgba(128,128,128,0.3);
    --success: #2E7D32;
    --error: #D32F2F;
    --warning: #F57F17;
    --radius: 0;
    --font: 'Helvetica Neue', Arial, sans-serif;
    --transition: 600ms cubic-bezier(0.25, 0.1, 0.25, 1);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--font); background: var(--bg-primary);
         color: var(--text-primary); font-weight: 300;
         letter-spacing: 0.04em; line-height: 1.6;
         height: 100vh; display: flex; flex-direction: column; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { color: var(--accent-hover); }

  /* ── Header ── */
  header { background: var(--bg-secondary); padding: 16px 24px;
           border-bottom: 1px solid var(--border); display: flex;
           align-items: center; gap: 16px; flex-shrink: 0; }
  h1 { font-size: 14px; font-weight: 700; letter-spacing: 0.1em;
       text-transform: uppercase; color: var(--accent); margin: 0; }
  .logo { width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0; }
  .status { font-size: 12px; color: var(--text-tertiary);
            letter-spacing: 0.08em; text-transform: uppercase;
            margin-left: auto; transition: color var(--transition); }
  .status.online { color: var(--success); }
  .status.offline { color: var(--error); }

  /* ── Main ── */
  main { flex: 1; max-width: 800px; margin: 0 auto; padding: 24px;
         width: 100%; display: flex; flex-direction: column; }
  .messages { flex: 1; overflow-y: auto; min-height: 60vh;
              scroll-behavior: smooth; }

  /* ── Messages ── */
  .msg { padding: 12px 16px; margin: 8px 0; border-radius: var(--radius);
         white-space: pre-wrap; word-break: break-word;
         font-weight: 300; letter-spacing: 0.04em;
         transition: opacity var(--transition); }
  .msg.user { background: rgba(201, 168, 76, 0.1);
              border-left: 2px solid var(--accent); }
  .msg.assistant { background: var(--bg-secondary);
                   border: 1px solid var(--border); }
  .msg.error { background: rgba(211, 47, 47, 0.1);
               border-left: 2px solid var(--error); color: var(--error); }
  .msg.system { background: var(--bg-tertiary);
                border: 1px solid var(--border);
                color: var(--text-tertiary); font-style: italic; }
  .msg .meta { font-size: 11px; color: var(--text-tertiary);
               margin-top: 4px; letter-spacing: 0.08em;
               text-transform: uppercase; }
  .msg .prefix { color: var(--accent); font-weight: 700; margin-right: 8px; }
  .msg.assistant .prefix { color: var(--success); }

  /* ── Skeleton Loading ── */
  .skeleton { padding: 12px 16px; margin: 8px 0; }
  .skeleton-line { height: 12px; background: var(--bg-tertiary);
                    margin: 8px 0; position: relative; overflow: hidden; }
  .skeleton-line::after { content: ''; position: absolute; top: 0; left: -100%;
    width: 100%; height: 100%;
    background: linear-gradient(90deg, transparent 0%,
                rgba(255,255,255,0.05) 50%, transparent 100%);
    animation: shimmer 1.5s infinite; }
  @keyframes shimmer { 0% { left: -100%; } 100% { left: 100%; } }
  .skeleton-line:first-child { width: 80%; }
  .skeleton-line:nth-child(2) { width: 60%; }
  .skeleton-line:nth-child(3) { width: 70%; }

  /* ── Input Area ── */
  form { display: flex; gap: 12px; margin-top: 16px; padding: 12px;
         background: var(--bg-secondary);
         border: 1px solid var(--border); border-radius: var(--radius);
         position: sticky; bottom: 0; flex-shrink: 0; }
  textarea { flex: 1; background: var(--bg-primary); color: var(--text-primary);
             border: 1px solid var(--border-strong);
             border-radius: var(--radius); padding: 12px 16px;
             resize: vertical; min-height: 60px; max-height: 200px;
             font-family: var(--font); font-size: 14px; font-weight: 300;
             letter-spacing: 0.04em; line-height: 1.6;
             transition: border-color var(--transition); }
  textarea:focus { outline: none; border-color: var(--accent); }
  textarea::placeholder { color: var(--text-tertiary); }
  button { background: var(--accent); color: var(--bg-primary);
           border: none; padding: 12px 24px; border-radius: var(--radius);
           cursor: pointer; font-weight: 700; font-size: 13px;
           letter-spacing: 0.1em; text-transform: uppercase;
           transition: background var(--transition); }
  button:hover { background: var(--accent-hover); }
  button:disabled { opacity: 0.3; cursor: not-allowed; }

  /* ── Code ── */
  code { background: var(--bg-tertiary); padding: 2px 8px;
         border: 1px solid var(--border); font-size: 13px; }
  pre { background: var(--bg-tertiary); padding: 16px; margin: 8px 0;
        border: 1px solid var(--border); overflow-x: auto;
        font-size: 13px; line-height: 1.6; }

  /* ── Responsive ── */
  @media (max-width: 600px) {
    header { padding: 12px 16px; }
    main { padding: 12px; }
    form { flex-direction: column; gap: 8px; padding: 8px; }
    button { width: 100%; }
    h1 { font-size: 12px; }
  }
</style>
</head>
<body>
<header>
  <img src="/assets/logo" alt="CortexAgent" class="logo">
  <h1>CORTEXAGENT</h1>
  <div class="status offline" id="status">OFFLINE</div>
</header>
<main>
  <div class="messages" id="messages">
    <div class="skeleton" id="skeleton">
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
    </div>
  </div>
  <form id="form">
    <textarea id="input" placeholder="Type a message..." autofocus></textarea>
    <button id="send" type="submit">SEND</button>
  </form>
</main>
<script>
const TOKEN = new URLSearchParams(location.search).get("token") || "";
const messages = document.getElementById("messages");
const status = document.getElementById("status");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const skeleton = document.getElementById("skeleton");

function authHeaders() {
  const h = {"Content-Type": "application/json"};
  if (TOKEN) h["Authorization"] = "Bearer " + TOKEN;
  return h;
}

async function loadStatus() {
  try {
    const r = await fetch("/status", {headers: authHeaders()});
    if (!r.ok) { status.textContent = "AUTH REQUIRED"; status.className = "status offline"; return; }
    const j = await r.json();
    status.textContent = `${j.profile} · ${j.model}`;
    status.className = "status online";
  } catch (e) {
    status.textContent = "OFFLINE";
    status.className = "status offline";
  }
}

function append(role, text, cls) {
  // Remove skeleton on first message
  if (skeleton) skeleton.remove();
  const div = document.createElement("div");
  div.className = "msg " + (cls || role);
  const prefix = role === "user" ? "▸" : role === "assistant" ? "✓" : "!";
  div.innerHTML = `<span class="prefix">${prefix}</span>${escHtml(text)}`;
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  append("user", text);
  input.value = "";
  send.disabled = true;
  // Show skeleton while loading
  if (skeleton) skeleton.style.display = "block";
  try {
    const r = await fetch("/message", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({message: text}),
    });
    const j = await r.json();
    if (j.ok) {
      append("assistant", j.response || "(no response)");
    } else {
      append("error", j.reason || "request failed");
    }
    loadStatus();
  } catch (e) {
    append("error", String(e));
  } finally {
    send.disabled = false;
    if (skeleton) skeleton.style.display = "none";
    input.focus();
  }
});

// Initial load
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
        print(f"  /: HTML served (mobile-friendly + textarea)")

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