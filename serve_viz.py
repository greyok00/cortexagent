#!/usr/bin/env python3
"""serve_viz.py — disposable static server for the 3D pipeline mockup.
Binds 127.0.0.1:8090, serves files with no-store so edits show immediately.
This is NOT webui.py — a throwaway viewer, not a product UI.

Adds /api/prompts — returns last N user prompts from hot memory for the
prompt-source dropdown. Falls back to inline sample list if hot memory
is unreachable (no daemon, no file).
"""
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOT_MEMORY = Path("/home/grey/.config/cortexllm/memory/hot/claude.jsonl")
FALLBACK_PROMPTS = [
    "fix the slider speed",
    "build api and write tests",
    "use react for the frontend",
    "why isn't it actually compressing anything",
    "the compression square sticks out too far on the bottom",
    "remove 8093 — only one webui on 8090",
    "stay on UD model — no fallback",
    "compressor should snapshot runs",
    "show me the staging list at the top",
    "show full chain prompt → output",
]


def _load_user_prompts(limit: int = 25) -> list[str]:
    """Read most-recent user-role entries from hot memory, newest first."""
    if not HOT_MEMORY.is_file():
        return list(FALLBACK_PROMPTS)
    out: list[str] = []
    try:
        with HOT_MEMORY.open("rb") as f:
            try:
                f.seek(0, os.SEEK_END)
            except OSError:
                pass
            size = f.tell()
            block = 256 * 1024  # ~256KB tail
            if size > block:
                f.seek(size - block)
                f.readline()  # discard partial first line
            data = f.read().decode("utf-8", errors="replace")
        for line in reversed(data.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("role") != "user":
                continue
            content = rec.get("content", "")
            if isinstance(content, str) and content.startswith("{"):
                try:
                    inner = json.loads(content)
                    content = inner.get("content", content)
                except json.JSONDecodeError:
                    pass
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            if len(content) > 160:
                content = content[:157] + "…"
            out.append(content)
            if len(out) >= limit:
                break
    except OSError:
        return list(FALLBACK_PROMPTS)
    return out or list(FALLBACK_PROMPTS)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")  # local-only LAN-safe
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — http.server override
        if self.path.split("?", 1)[0] == "/api/prompts":
            prompts = _load_user_prompts()
            self._json({"prompts": prompts, "source": "hot" if HOT_MEMORY.is_file() else "fallback"})
            return
        return super().do_GET()

    def end_headers(self):
        # no-store: browser must never heuristically cache the mockup
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):
        pass


def main():
    port = int(os.environ.get("SERVE_VIZ_PORT", "8090"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # localhost-only
    print(f"[serve_viz] http://127.0.0.1:{port}/  (Ctrl-C to stop)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
