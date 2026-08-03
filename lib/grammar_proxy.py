#!/usr/bin/env python3
"""grammar_proxy.py — strips grammar field from Anthropic API requests.

Claude Code sends a `grammar` parameter that llama-server can't parse.
This proxy strips it and forwards everything else, including streaming.

Also tracks token usage and exposes a /metrics endpoint for real-time
token/s monitoring in the Claude Code status line.

Usage:
  python3 lib/grammar_proxy.py [port] [target]
  # Default: port=8081, target=http://127.0.0.1:8080
"""
import json, os, sys, socket, select, threading, time
from datetime import datetime
from pathlib import Path
import urllib.request

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib import control  # reload-aware: trigger big-model reload via the daemon

# ── Token Tracking ───────────────────────────────────────────────────────────
_token_lock = threading.Lock()
_token_metrics = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "requests": 0,
    "total_time_s": 0.0,
    "started_at": datetime.now().isoformat(),
    "current_tok_s": 0.0,  # tokens/s for the last request
    "avg_tok_s": 0.0,      # running average
    "last_request_ts": 0.0,  # unix ts of the last completed inference (0 = none yet)
}


def _record_tokens(prompt_tokens: int, completion_tokens: int, elapsed: float):
    with _token_lock:
        _token_metrics["prompt_tokens"] += prompt_tokens
        _token_metrics["completion_tokens"] += completion_tokens
        _token_metrics["total_tokens"] += prompt_tokens + completion_tokens
        _token_metrics["requests"] += 1
        _token_metrics["total_time_s"] += elapsed
        _token_metrics["last_request_ts"] = time.time()
        if elapsed > 0 and completion_tokens > 0:
            _token_metrics["current_tok_s"] = round(completion_tokens / elapsed, 1)
        if _token_metrics["total_time_s"] > 0 and _token_metrics["completion_tokens"] > 0:
            _token_metrics["avg_tok_s"] = round(
                _token_metrics["completion_tokens"] / _token_metrics["total_time_s"], 1
            )


# ── VRAM cache (throttled nvidia-smi) ────────────────────────────────────────
# The statusline is a fresh process per render, so a per-render nvidia-smi
# would be too slow. The proxy is long-lived: one nvidia-smi per _VRAM_TTL s,
# cached in-process and served to every /metrics poll.
_VRAM_TTL = 3.0
_vram_cache = {"ts": 0.0, "used": None, "total": None}


def _vram_mib():
    """Return (used_mib, total_mib), cached for _VRAM_TTL seconds. None on failure."""
    now = time.time()
    if now - _vram_cache["ts"] < _VRAM_TTL:
        return _vram_cache["used"], _vram_cache["total"]
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().split(", ")
        used, total = int(out[0]), int(out[1])
        _vram_cache.update(ts=now, used=used, total=total)
        return used, total
    except Exception:
        _vram_cache["ts"] = now  # backoff so a failing GPU doesn't spam nvidia-smi
        return _vram_cache["used"], _vram_cache["total"]


def _get_metrics() -> str:
    with _token_lock:
        m = dict(_token_metrics)
    used, total = _vram_mib()
    if used is not None:
        m["vram_used_mib"] = used
        m["vram_total_mib"] = total
    return json.dumps(m, indent=2)


# ── Diagnostics ──────────────────────────────────────────────────────────────
_DUMP = os.environ.get("CORTEXAGENT_PROXY_DUMP", "")


def _has_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def _diag(method, path, cl, chunked, body_len, parsed, parse_err):
    keys = list(parsed.keys()) if isinstance(parsed, dict) else None
    ntools = len(parsed.get("tools", [])) if isinstance(parsed, dict) else None
    has_grammar = _has_key(parsed, "grammar") if parsed is not None else None
    has_rf = ("response_format" in parsed) if isinstance(parsed, dict) else None
    nmsgs = len(parsed.get("messages", [])) if isinstance(parsed, dict) else None
    print(f"[proxy] DIAG method={method} path={path} cl={cl} chunked={chunked} "
          f"body={body_len} keys={keys} ntools={ntools} nmsgs={nmsgs} "
          f"grammar_present={has_grammar} response_format={has_rf} parse_err={parse_err}",
          file=sys.stderr)
    if parsed is not None and _DUMP:
        try:
            with open(_DUMP, "w") as f:
                f.write(json.dumps(parsed)[:400000])
        except Exception as e:
            print(f"[proxy] DIAG dump failed: {e}", file=sys.stderr)


def pipe(src, dst, stop, resp_buf=None):
    while not stop.is_set():
        r, _, _ = select.select([src], [], [], 0.3)
        if r:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            if resp_buf is not None:
                resp_buf.append(data)


class ProxyHandler:
    def __init__(self, conn, addr, target):
        self.conn = conn
        self.addr = addr
        self.target = target

    # ── Reload-aware target management ──────────────────────────────────────
    def _target_healthy(self, timeout=2):
        try:
            h, p = self.target
            req = urllib.request.Request(f"http://{h}:{p}/health", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _touch_activity(self):
        # Reset the daemon idle timer (best-effort; daemon may be absent in
        # legacy per-session mode — a failed ping is silently ignored).
        try:
            control.send_request("activity", timeout=2)
        except Exception:
            pass

    def _ensure_target(self):
        # If the big model is idle-unloaded, ask the daemon to reload it, then
        # wait for /health. Returns True once the target is reachable.
        if self._target_healthy(timeout=2):
            return True
        print(f"[proxy] target {self.target} down — requesting reload...", file=sys.stderr)
        try:
            control.send_request("load", which="big", timeout=300)
        except Exception as e:
            print(f"[proxy] reload request failed (daemon absent?): {e}", file=sys.stderr)
        deadline = time.time() + 300
        while time.time() < deadline:
            if self._target_healthy(timeout=2):
                print("[proxy] target back up — forwarding", file=sys.stderr)
                return True
            time.sleep(1)
        print("[proxy] target still down after reload — returning 503", file=sys.stderr)
        return False

    def _respond_503(self):
        body = b'{"error":"model unavailable"}'
        resp = ("HTTP/1.1 503 Service Unavailable\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

    def handle(self):
        try:
            head_bytes, body = self._read_request()
            if not head_bytes:
                return
            self._forward(head_bytes, body)
        except Exception as e:
            print(f"[proxy] handle error: {e}", file=sys.stderr)
        finally:
            try:
                self.conn.close()
            except Exception:
                pass

    def _read_request(self):
        """Read full HTTP request headers + body. Returns (head_bytes, body)."""
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                return None, b""
            buf += chunk
            if len(buf) > (1 << 20):  # 1 MB header guard
                return None, b""
        head_bytes, body = buf.split(b"\r\n\r\n", 1)
        return head_bytes, body

    def _forward(self, head_bytes, body):
        headers_text = head_bytes.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        parts = lines[0].split(" ", 2)
        if len(parts) < 2:
            return
        method = parts[0].upper()

        # ── Handle /metrics endpoint ──
        if method == "GET" and len(parts) > 1 and parts[1] == "/metrics":
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(_get_metrics())}\r\n\r\n{_get_metrics()}"
            try:
                self.conn.sendall(resp.encode())
            except Exception:
                pass
            return

        # Parse headers into an ordered map (lowercased keys, original case kept).
        order, hdr, orig = [], {}, {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            raw = k.strip()
            k = raw.lower()
            order.append(k)
            hdr[k] = v.strip()
            orig[k] = raw

        if method == "POST":
            # Reload-aware: ensure the big model is up before forwarding, and
            # reset the daemon idle timer. Only POSTs are inference requests —
            # GET /health probes must NOT trigger a reload (or idle-unload breaks).
            if not self._ensure_target():
                self._respond_503()
                return
            self._touch_activity()
            # Honor Expect: 100-continue so large-body clients will send the body.
            if "100-continue" in hdr.get("expect", "").lower():
                try:
                    self.conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                except Exception:
                    pass

            te = hdr.get("transfer-encoding", "").lower()
            cl = hdr.get("content-length")
            if "chunked" in te or cl is None:
                _diag(method, parts[1] if len(parts) > 1 else "?",
                      cl, True, len(body), None,
                      "raw/no-strip (chunked or no content-length)")
                self._forward_raw(head_bytes, body)
                return

            cl = int(cl)
            while len(body) < cl:
                chunk = self.conn.recv(min(65536, cl - len(body)))
                if not chunk:
                    break
                body += chunk

            parse_err = None
            parsed = None
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict) and "grammar" in parsed:
                    del parsed["grammar"]
                body = json.dumps(parsed).encode()
            except Exception as e:
                parse_err = str(e)
                print(f"[proxy] strip skipped: {e}", file=sys.stderr)
            _diag(method, parts[1] if len(parts) > 1 else "?",
                  cl, "chunked" in te, len(body), parsed, parse_err)

            # Rebuild headers with corrected Content-Length.
            new_lines = [lines[0]]
            for k in order:
                if k in ("host", "content-length", "expect", "transfer-encoding"):
                    continue
                if k == "user-agent":
                    new_lines.append("User-Agent: cortexagent/1.0")
                else:
                    new_lines.append(f"{orig[k]}: {hdr[k]}")
            new_lines.append(f"Content-Length: {len(body)}")
            new_lines.append("Host: 127.0.0.1")
            head_bytes = ("\r\n".join(new_lines)).encode()

        data = head_bytes + b"\r\n\r\n" + body
        _t0 = time.time()
        self._send_and_pipe(data)
        _elapsed = time.time() - _t0
        if _elapsed > 0.1:
            print(f"[proxy] completed in {_elapsed:.2f}s", file=sys.stderr)

    def _forward_raw(self, head_bytes, body):
        """Forward headers + body and stream any further client bytes, then pipe response."""
        data = head_bytes + b"\r\n\r\n" + body
        dst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dst.settimeout(30)
        try:
            dst.connect(self.target)
            dst.sendall(data)
        except Exception as e:
            print(f"[proxy] connect error: {e}", file=sys.stderr)
            dst.close()
            return
        stop = threading.Event()
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop), daemon=True)
        t1.start()
        try:
            while True:
                r, _, _ = select.select([self.conn], [], [], 0.5)
                if r:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    dst.sendall(chunk)
        except Exception:
            pass
        finally:
            stop.set()
            t1.join(timeout=3)
            try:
                dst.close()
            except Exception:
                pass

    def _send_and_pipe(self, data):
        """Send the full (already-stripped) request, then relay the response.

        Tears down when either the client or the server closes — matching the
        pre-strip behavior so streaming and keep-alive responses both drain.
        """
        dst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dst.settimeout(30)
        _t0 = time.time()
        try:
            dst.connect(self.target)
            dst.sendall(data)
        except Exception as e:
            print(f"[proxy] connect error: {e}", file=sys.stderr)
            dst.close()
            return
        stop = threading.Event()
        resp_buf: list[bytes] = []
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop, resp_buf), daemon=True)
        t1.start()
        try:
            while True:
                r, _, _ = select.select([self.conn], [], [], 0.5)
                if r:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    dst.sendall(chunk)
        except Exception:
            pass
        finally:
            stop.set()
            # Extract token usage from response
            pt, ct = 0, 0
            if resp_buf:
                full = b"".join(resp_buf).decode("utf-8", errors="replace")
                for line in full.split("\n"):
                    if "usage" in line.lower() or "completion_tokens" in line:
                        try:
                            if line.startswith("data: "):
                                line = line[6:]
                            usage = json.loads(line).get("usage", {})
                            pt = usage.get("prompt_tokens", 0) or pt
                            ct = usage.get("completion_tokens", 0) or ct
                        except Exception:
                            pass
            _elapsed = time.time() - _t0
            if ct:
                _record_tokens(pt, ct, _elapsed)
                tok_s = round(ct / _elapsed, 1) if _elapsed > 0 else 0
                print(f"[proxy] tokens: {pt} in → {ct} out ({tok_s} tok/s, {_elapsed:.1f}s)", file=sys.stderr)
            t1.join(timeout=3)
            try:
                dst.close()
            except Exception:
                pass


def main():
    port = int(os.environ.get("CORTEXAGENT_PROXY_PORT", sys.argv[1] if len(sys.argv) > 1 else "8081"))
    target_url = os.environ.get("CORTEXAGENT_PROXY_TARGET", sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8080")
    host = target_url.split("://")[-1].split(":")[0]
    port_target = int(target_url.split(":")[-1])
    target = (host, port_target)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(10)
    print(f"[proxy] listening on {port} -> {target_url}", file=sys.stderr)

    while True:
        conn, addr = server.accept()
        handler = ProxyHandler(conn, addr, target)
        threading.Thread(target=handler.handle, daemon=True).start()


if __name__ == "__main__":
    main()
