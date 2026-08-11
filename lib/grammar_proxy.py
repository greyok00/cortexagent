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
import json, os, sys, socket, threading, time, errno
from datetime import datetime
from pathlib import Path
import urllib.request


# ── Tray dashboard state (consumed by lib/tray_dashboard.py) ───────────────
# We approximate the big model's "Step N of M" progress by counting distinct
# tool calls in the response body — each tool call represents a reasoning
# step. The popout dashboard polls ~/.cortexagent/big_model_steps.json every
# 1s and renders this. Writes are atomic (tmp + rename) so a half-written
# file can't crash the dashboard reader.
_DASHBOARD_STEPS = Path.home() / ".cortexagent" / "big_model_steps.json"


def _emit_dashboard_step(body: bytes, elapsed: float) -> None:
    """Count tool calls in the proxy response and write the dashboard state
    file. Called once per forwarded response (non-streaming path).
    """
    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return
    # OpenAI / Anthropic responses carry tool_calls on choices[].message
    steps: list = []
    try:
        choices = parsed.get("choices") or []
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            tcs = msg.get("tool_calls") or []
            for i, tc in enumerate(tcs):
                fn = (tc.get("function") or {}).get("name") or f"tool_{i+1}"
                steps.append({"label": f"call {fn}", "status": "done"})
            if not steps and msg.get("content"):
                # Plain text reply — single step
                steps = [{"label": "respond", "status": "done"}]
    except Exception:
        steps = []
    payload = {
        "steps": steps,
        "current": max(len(steps) - 1, 0) if steps else 0,
        "elapsed_s": round(elapsed, 2),
        "updated_at": time.time(),
    }
    try:
        _DASHBOARD_STEPS.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DASHBOARD_STEPS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(_DASHBOARD_STEPS)
    except Exception:
        pass

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib import control  # reload-aware: trigger big-model reload via the daemon

# ── Minification pipeline (opt-out via CORTEXAGENT_MINIFY=off) ────────────────
# On by default. Prefers the user's slimtoken engine (real compression:
# dedup of repeated tool output + distill of old turns + budget backstop),
# falls back to the conservative lib.minify (whitespace/tool-def noise only).
# A parse failure in any stage is caught and never blocks inference.
try:
    from slimtoken.pipeline import minify_request, MinifyConfig
    _MINIFY_BACKEND = "slimtoken"
    _MINIFY_OK = True
except Exception:  # pragma: no cover — slimtoken is optional
    try:
        from lib.minify.pipeline import minify_request, MinifyConfig
        _MINIFY_BACKEND = "lib.minify"
        _MINIFY_OK = True
    except Exception as _e:  # pragma: no cover — minify is optional
        _MINIFY_OK = False
        print(f"[proxy] minify unavailable (continuing without): {_e}",
              file=sys.stderr)


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _build_minify_cfg():
    if not _MINIFY_OK or not _bool_env("CORTEXAGENT_MINIFY", True):
        return None
    stages = set()
    if _bool_env("CORTEXAGENT_MINIFY_TOOLS", True):
        stages.add("tools")
    if _bool_env("CORTEXAGENT_MINIFY_SYSTEM", True):
        stages.add("system")
    if _bool_env("CORTEXAGENT_MINIFY_MESSAGES", True):
        stages.add("messages")
        # Real compression: dedup repeated tool results + distill old turns.
        # (lib.minify ignores unknown stage names — safe to add either way.)
        stages.update(("dedup", "distill"))
    skip = {s.strip() for s in os.environ.get(
        "CORTEXAGENT_MINIFY_TOOL_SKIP", "").split(",") if s.strip()}
    # slimtoken default = 131072: a HARD backstop at the server ceiling. If a
    # request ever exceeds it (the 400-class bug: context grows to the ceiling,
    # server rejects), history is dropped to fit instead of erroring. Auto-
    # compact at 124k keeps normal traffic well under, so this rarely engages.
    _default_budget = 131072 if _MINIFY_BACKEND == "slimtoken" else 0
    try:
        budget = int(os.environ.get("CORTEXAGENT_MINIFY_BUDGET", "") or _default_budget)
    except ValueError:
        budget = _default_budget
    try:
        keep_last = int(os.environ.get("CORTEXAGENT_MINIFY_KEEP_LAST", "8") or 8)
    except ValueError:
        keep_last = 8
    kw = dict(
        token_budget=budget,           # slimtoken: 0→off, 131072→backstop
        enabled_stages=stages,
        tool_skip=skip,
        keep_last=keep_last,
    )
    if _MINIFY_BACKEND == "slimtoken":
        kw["dedup_min_chars"] = int(os.environ.get(
            "CORTEXAGENT_MINIFY_DEDUP_MIN", "200") or 200)
        kw["distill_max_chars"] = int(os.environ.get(
            "CORTEXAGENT_MINIFY_DISTILL_MAX", "240") or 240)
    else:  # lib.minify fallback keeps its conservative defaults
        kw["minify_dom"] = _bool_env("CORTEXAGENT_MINIFY_DOM", False)
    return MinifyConfig(**kw)


_MINIFY_CFG = _build_minify_cfg()
_MINIFY_CHUNKED = _bool_env("CORTEXAGENT_MINIFY_CHUNKED", True)
_MINIFY_RESPONSE = _bool_env("CORTEXAGENT_MINIFY_RESPONSE", True)

# ── Output-side minify (R4) ──────────────────────────────────────────────────
# Slimtoken has no response minify, so we run a thin local helper. Strips
# model-generated filler ("Sure!", "Here is the code:", "Let me know if…")
# from the assistant message content. Operates on already-buffered response
# chunks AFTER upstream sends a "data: [DONE]" sentinel — never on a live
# stream (would corrupt partial tokens). Bounded to ~16 KB scan per call.
_FILLER_PATTERNS = (
    "Sure!\n", "Sure!\n\n", "Sure, ", "Sure.\n",
    "Here is the code:\n", "Here is the code:\n\n",
    "Here is your code:\n", "Here is your code:\n\n",
    "Let me know if you need anything else.\n",
    "Let me know if you have any questions.\n",
    "I hope this helps!\n", "I hope this helps.\n",
    "Feel free to ask if you have any questions.\n",
)


def minify_response(body: bytes) -> bytes:
    """Strip model-generated filler phrases from a buffered response.

    No-op for streams (SSE chunks have no [DONE] yet); caller must buffer
    the full response first. Returns body unchanged on any parse error so a
    malformed payload still reaches the client.
    """
    if not _MINIFY_RESPONSE or not body:
        return body
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return body
    # SSE responses are line-delimited; only touch data: lines (object schema).
    out_lines = []
    changed = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith("data: ") and stripped != "data: [DONE]"):
            out_lines.append(line)
            continue
        payload = stripped[6:]
        try:
            obj = json.loads(payload)
        except Exception:
            out_lines.append(line)
            continue
        # OpenAI-style choices[].delta.content / choices[].message.content
        try:
            choices = obj.get("choices") or []
            for ch in choices:
                delta = ch.get("delta") or {}
                msg = ch.get("message") or {}
                c = delta.get("content")
                if not c:
                    c = msg.get("content")
                if isinstance(c, str):
                    new = c
                    for pat in _FILLER_PATTERNS:
                        if new.startswith(pat):
                            new = new[len(pat):]
                            changed = True
                            break
                    if new != c:
                        if "delta" in ch:
                            ch["delta"]["content"] = new
                        else:
                            ch["message"]["content"] = new
        except Exception:
            pass
        out_lines.append("data: " + json.dumps(obj, ensure_ascii=False))
    if not changed:
        return body
    return ("\n".join(out_lines)).encode("utf-8")

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
    src.settimeout(0.3)
    while not stop.is_set():
        try:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            if resp_buf is not None:
                resp_buf.append(data)
        except socket.timeout:
            continue
        except OSError:
            break


def _dechunk(data: bytes):
    """Decode an HTTP chunked-transfer body. Returns bytes, or None if the
    body is incomplete / malformed (caller falls back to raw passthrough)."""
    out = b""
    i = 0
    n = len(data)
    while True:
        crlf = data.find(b"\r\n", i)
        if crlf < 0:
            return None
        size_field = data[i:crlf].split(b";")[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError:
            return None
        i = crlf + 2
        if size == 0:
            break
        if i + size + 2 > n:
            return None  # incomplete data chunk
        out += data[i:i + size]
        i += size + 2  # data + trailing CRLF
    return out


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

    def _respond_502(self):
        body = b'{"error":"bad gateway - backend connection failed"}'
        resp = ("HTTP/1.1 502 Bad Gateway\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

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
        """Read full HTTP request headers + body. Returns (head_bytes, body).

        30s timeout prevents handler threads from blocking forever on a client
        that connects but never sends data (the root cause of CLOSE-WAIT leaks).
        """
        self.conn.settimeout(30)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                chunk = self.conn.recv(65536)
                if not chunk:
                    return None, b""
                buf += chunk
                if len(buf) > (1 << 20):  # 1 MB header guard
                    return None, b""
        except socket.timeout:
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
            is_chunked = "chunked" in te
            if is_chunked and _MINIFY_CFG is not None and _MINIFY_CHUNKED:
                _diag(method, parts[1] if len(parts) > 1 else "?",
                      cl, True, len(body), None,
                      "chunked → buffer+minify (raw fallback on parse fail)")
                self._forward_chunked(head_bytes, body)
                return
            if is_chunked or cl is None:
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
                if isinstance(parsed, dict):
                    if "grammar" in parsed:
                        del parsed["grammar"]
                    if _MINIFY_CFG is not None:
                        parsed, mstats = minify_request(parsed, _MINIFY_CFG)
                        print(f"[proxy] minify: {mstats.summary()}", file=sys.stderr)
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
        # R3: thinking-bottom-line (CLI) — emit divider + reflection via stderr
        # so a CLI front-end can render "_ divider / ▎ thinking: ..." as a
        # bottom task bar. Skipped for non-streaming clients; only meaningful
        # when the call path is interactive.
        if os.isatty(sys.stderr.fileno()) if hasattr(sys.stderr, "fileno") else False:
            print("\n_\n▎ thinking: completion in {:.2f}s\n".format(_elapsed), file=sys.stderr)
        # Tray dashboard state: emit a small JSON file with step counters
        # so the popout overseer dashboard can show "Step N of M" + progress
        # bar. We approximate step count by the number of distinct tool
        # calls (rough heuristic — the big model emits a tool call per
        # reasoning step), then mark the request as complete. No-op if the
        # file path isn't writable. See lib/tray_dashboard.py.
        try:
            _emit_dashboard_step(body, _elapsed)
        except Exception:
            pass

    def _forward_chunked(self, head_bytes, body):
        """Buffer a chunked request, de-chunk, minify, re-send with Content-Length.

        Falls back to raw passthrough (``_forward_raw``) if the chunked body
        can't be fully read within the size cap or fails to de-chunk/parse.
        The request body is one JSON object (only the *response* is streamed),
        so buffering it fully is safe and lets us minify + strip grammar.
        """
        cap = int(os.environ.get("CORTEXAGENT_MINIFY_CHUNKED_MAX", str(16 * 1024 * 1024)))
        buf = body
        terminator = b"\r\n0\r\n\r\n"
        while terminator not in buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap:
                # Too large to buffer safely → give up on minify, raw-passthrough.
                self._forward_raw(head_bytes, buf)
                return
        dechunked = _dechunk(buf)
        if dechunked is None:
            self._forward_raw(head_bytes, buf)
            return
        try:
            parsed = json.loads(dechunked)
            if isinstance(parsed, dict):
                if "grammar" in parsed:
                    del parsed["grammar"]
                parsed, mstats = minify_request(parsed, _MINIFY_CFG)
                print(f"[proxy] minify(chunked): {mstats.summary()}", file=sys.stderr)
                dechunked = json.dumps(parsed).encode()
        except Exception as e:
            print(f"[proxy] chunked minify skipped: {e}", file=sys.stderr)
            self._forward_raw(head_bytes, buf)
            return
        # Rebuild headers: drop TE/CL/expect/host, set a fresh Content-Length.
        headers_text = head_bytes.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        new_lines = [lines[0]]
        for line in lines[1:]:
            if not line:
                continue
            k = line.split(":", 1)[0].strip().lower()
            if k in ("transfer-encoding", "content-length", "expect", "host"):
                continue
            if k == "user-agent":
                new_lines.append("User-Agent: cortexagent/1.0")
            else:
                new_lines.append(line)
        new_lines.append(f"Content-Length: {len(dechunked)}")
        new_lines.append("Host: 127.0.0.1")
        head = ("\r\n".join(new_lines)).encode()
        self._send_and_pipe(head + b"\r\n\r\n" + dechunked)

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
            self._respond_502()
            return
        stop = threading.Event()
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop), daemon=True)
        t1.start()
        self.conn.settimeout(0.5)
        _idle_since = time.monotonic()
        try:
            while True:
                try:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    _idle_since = time.monotonic()
                    dst.sendall(chunk)
                except socket.timeout:
                    if time.monotonic() - _idle_since > 30:
                        break
                    continue
        except Exception:
            pass
        finally:
            stop.set()
            t1.join(timeout=3)
            try:
                dst.close()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass

    def _send_and_pipe(self, data):
        """Send the full (already-stripped) request, then relay the response.

        Tears down when either the client or the server closes — matching the
        pre-strip behavior so streaming and keep-alive responses both drain.

        Idle timeout (30s) prevents CLOSE-WAIT accumulation: if the client
        stops sending data after the backend has closed, the loop exits and
        the socket is cleaned up.
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
            self._respond_502()
            return
        stop = threading.Event()
        resp_buf: list[bytes] = []
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop, resp_buf), daemon=True)
        t1.start()
        self.conn.settimeout(0.5)
        _idle_since = time.monotonic()
        try:
            while True:
                try:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    _idle_since = time.monotonic()
                    dst.sendall(chunk)
                except socket.timeout:
                    if time.monotonic() - _idle_since > 30:
                        break
                    continue
        except Exception:
            pass
        finally:
            stop.set()
            # Extract token usage from response. Run minify_response on the
            # buffered response (no-op for live SSE — we already piped live
            # bytes to the client; this only feeds token accounting / metrics).
            pt, ct = 0, 0
            if resp_buf:
                full = b"".join(resp_buf)
                minified = minify_response(full)
                if minified is not full:
                    # update in-place so subsequent accounting sees the minified form
                    resp_buf.clear()
                    resp_buf.append(minified)
                full_text = (minified if minified is not full else full).decode("utf-8", errors="replace")
                for line in full_text.split("\n"):
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
            try:
                self.conn.close()
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
    # Retry bind with backoff: a freshly-killed predecessor may still hold the
    # port for a moment even with SO_REUSEADDR (live process, not TIME_WAIT).
    bound = False
    for attempt in range(20):
        try:
            server.bind(("127.0.0.1", port))
            bound = True
            break
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            print(f"[proxy] :{port} busy (attempt {attempt+1}/20), retrying…", file=sys.stderr)
            time.sleep(0.5)
    if not bound:
        raise OSError(errno.EADDRINUSE, f"port {port} still in use after 10s of retries")
    server.listen(10)
    print(f"[proxy] listening on {port} -> {target_url}", file=sys.stderr)

    while True:
        conn, addr = server.accept()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # TCP keepalive: 10s idle → 3 probes at 3s intervals → drop
        if hasattr(socket, "TCP_KEEPIDLE"):
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            except Exception:
                pass
        handler = ProxyHandler(conn, addr, target)
        threading.Thread(target=handler.handle, daemon=True).start()


if __name__ == "__main__":
    main()
