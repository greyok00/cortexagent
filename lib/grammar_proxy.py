#!/usr/bin/env python3
"""grammar_proxy.py — strips grammar field from Anthropic API requests.

Claude Code sends a `grammar` parameter that llama-server can't parse.
This proxy strips it and forwards everything else, including streaming.

Usage:
  python3 lib/grammar_proxy.py [port] [target]
  # Default: port=8081, target=http://127.0.0.1:8080
"""
import json, os, sys, socket, select, threading

# ── Diagnostics (DIAGNOSTIC — safe to remove once 400 root cause is fixed) ──
# Logs per-request structure to stderr (→ proxy.log) and optionally dumps the
# forwarded (grammar-stripped) JSON to a local transient file for replay.
_DUMP = os.environ.get("CORTEXAGENT_PROXY_DUMP", "")  # set to a path to enable body dump


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


def pipe(src, dst, stop):
    while not stop.is_set():
        r, _, _ = select.select([src], [], [], 0.3)
        if r:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)


class ProxyHandler:
    def __init__(self, conn, addr, target):
        self.conn = conn
        self.addr = addr
        self.target = target

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
            # Honor Expect: 100-continue so large-body clients will send the body.
            if "100-continue" in hdr.get("expect", "").lower():
                try:
                    self.conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                except Exception:
                    pass

            te = hdr.get("transfer-encoding", "").lower()
            cl = hdr.get("content-length")
            if "chunked" in te or cl is None:
                # Unknown length: forward raw, streaming any remaining bytes.
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
                # Not JSON or unparseable — forward the buffered body untouched.
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
        self._send_and_pipe(data)

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
