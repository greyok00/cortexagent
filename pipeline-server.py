#!/usr/bin/env python3
"""Pipeline Visualization Server — standalone 3D prompt pipeline visualizer.

Serves the pipeline visualization HTML at port 8093.

Connects to the existing CortexAgent webui at :8090 for live data via:
  - /webui-events (SSE) — prompt/response events
  - /api/state          — model state
  - /status             — system status

Usage:
  python3 pipeline-server.py [port]     # start server
  python3 pipeline-server.py serve      # explicit
  python3 pipeline-server.py test       # connectivity check
"""
import http.server
import json
import os
import sys
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("CORTEXAGENT_PIPELINE_PORT", "8093"))
BIND = "127.0.0.1"
WEBUI_PORT = int(os.environ.get("CORTEXAGENT_WEBUI_PORT", "8090"))

STATIC_DIR = Path(__file__).resolve().parent / "pipeline-viz-assets"
HTML_PATH = Path(__file__).resolve().parent / "pipeline-viz.html"
ROOT_DIR = Path(__file__).resolve().parent  # for pipeline-viz.html

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "text/javascript; charset=utf-8",
    ".mjs":  "text/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".gif":  "image/gif",
    ".svg":  "image/svg+xml",
}


class PipelineHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler serving the pipeline visualization."""

    def log_message(self, format, *args):
        """Silence request logging (cleaner terminal)."""
        pass

    def do_GET(self):
        """Serve static files or proxy API requests to webui."""
        path = self.path

        # Serve static files
        if path == "/":
            # Serve pipeline-viz.html from root
            file_path = ROOT_DIR / "pipeline-viz.html"
            if file_path.is_file():
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"404 Not Found\n")
                return
        elif path == "/status":
            self._proxy_status()
            return
        elif path == "/api/state":
            self._proxy_api_state()
            return
        elif path.startswith("/webui-events"):
            self._proxy_sse()
            return
        elif path.startswith("/api/"):
            self._proxy_api(path)
            return

        # Serve from static dir
        file_path = STATIC_DIR / path.lstrip("/")
        if not file_path.is_file():
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found\n")
            return

        mime = MIME_TYPES.get(Path(file_path).suffix, "application/octet-stream")
        try:
            data = file_path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _proxy_status(self):
        """Proxy /status to the webui."""
        try:
            url = f"http://127.0.0.1:{WEBUI_PORT}/status"
            req = urllib.request.Request(url, headers={"X-Proxy": "pipeline"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _proxy_api_state(self):
        """Proxy /api/state to the webui."""
        try:
            url = f"http://127.0.0.1:{WEBUI_PORT}/api/state"
            req = urllib.request.Request(url, headers={"X-Proxy": "pipeline"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def _proxy_sse(self):
        """Proxy SSE events from webui."""
        try:
            url = f"http://127.0.0.1:{WEBUI_PORT}/webui-events"
            req = urllib.request.Request(url, headers={"X-Proxy": "pipeline"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                reader = resp.read(4096)
                while reader:
                    self.wfile.write(reader)
                    reader = resp.read(4096)
        except Exception:
            pass

    def _proxy_api(self, path):
        """Proxy other /api/* to webui."""
        try:
            url = f"http://127.0.0.1:{WEBUI_PORT}{path}"
            req = urllib.request.Request(url, headers={"X-Proxy": "pipeline"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


def check_webui():
    """Check if the webui is running."""
    try:
        url = f"http://127.0.0.1:{WEBUI_PORT}/status"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            model = data.get("model", "unknown")
            profile = data.get("profile", "unknown")
            print(f"✅ WebUI running — model: {model}, profile: {profile}")
            return True
    except Exception as e:
        print(f"❌ WebUI not accessible: {e}")
        print(f"   Make sure webui.py is running on port {WEBUI_PORT}")
        return False


def main():
    """Main entry point."""
    global PORT
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Pipeline Visualization Server — Connectivity Check")
        print("=" * 50)
        if check_webui():
            print("✅ Pipeline visualization is ready at http://127.0.0.1:" + str(PORT))
        else:
            print("\nTo start the webui:")
            print(f"  cd ~/cortexagent && python3 lib/webui.py")
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        check_webui()
    elif len(sys.argv) > 1:
        PORT = int(sys.argv[1])

    print(f"🔮 CortexAgent Pipeline Visualization")
    print(f"📍 http://{BIND}:{PORT}")
    print(f"📡 Proxies data from webui on :{WEBUI_PORT}")
    print(f"   Press Ctrl+C to stop")
    print()

    server = http.server.ThreadingHTTPServer((BIND, PORT), PipelineHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
