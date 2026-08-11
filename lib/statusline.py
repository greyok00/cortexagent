#!/usr/bin/env python3
"""cortexagent statusline — branded bottom bar for the agent TUI.

Reads the agent's status JSON on stdin and fetches token metrics from the
grammar proxy. Prints a single branded line:
    CortexAgent · <author> · <model> · <cwd> · <ctx tokens> · <tok/s>

The agent CLI calls this on every render. Output is plain text (one line).
Fails soft: on any error, prints a minimal branded line so the TUI never
loses its status bar.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib.config import CFG  # author tag is configurable (CORTEXAGENT_AUTHOR)


def _read_minify_snapshot() -> dict:
    """Read the proxy's persisted minify snapshot, if any. Used to surface
    savings% in the statusline so the user sees minification in the TUI bar."""
    try:
        p = Path.home() / ".cortexagent" / "minify_stats.json"
        if not p.exists():
            return {}
        d = json.loads(p.read_text() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _get_token_metrics() -> str:
    """Fetch token metrics from the grammar proxy /metrics endpoint.

    Splits the rate into input + output tokens/s so the user can see prompt
    eval (input) vs decode (output) separately — the two saturate the GPU
    differently and it's the decode rate that decides perceived speed.
    """
    proxy_port = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/metrics",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            parts = []
            ct = data.get("completion_tokens", 0)
            pt = data.get("prompt_tokens", 0)
            reqs = data.get("requests", 0)
            in_tps = data.get("current_in_tps", 0)
            out_tps = data.get("current_out_tps") or data.get("current_tok_s", 0)
            if ct:
                parts.append(f"{ct} tok")
            # Show both rates when both are non-zero (decode is the user-visible
            # speed, prompt-eval matters for big-context workflows); show only
            # the non-zero one when only one side fired.
            if in_tps and out_tps:
                parts.append(f"in {in_tps:.0f} t/s · out {out_tps:.0f} t/s")
            elif out_tps:
                parts.append(f"{out_tps} t/s")
            elif in_tps:
                parts.append(f"in {in_tps} t/s")
            if reqs:
                parts.append(f"{reqs} req")
            return " · ".join(parts) if parts else ""
    except Exception:
        return ""


def _get_vram_breakdown() -> str:
    """Per-process VRAM breakdown pulled from the daemon control socket.

    Daemon's status payload exposes vram_by_proc = {big_mib, tiny_mib,
    other_mib, by_pid}. The statusline renders it as "big 14.3 GB + tiny 0.9
    GB / 16 GB" so the user sees who's holding the GPU (big vs tiny vs
    external consumers like a browser or game). Falls back to a single total
    if the daemon is unreachable.
    """
    import socket as _socket  # local import: not always needed
    sock = Path.home() / ".cortexagent" / "control.sock"
    if not sock.exists():
        return ""
    try:
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(1.2)
        s.connect(str(sock))
        s.sendall(b'{"cmd":"status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        if not buf:
            return ""
        payload = json.loads(buf.decode("utf-8", "replace").strip() or "{}")
    except Exception:
        return ""
    vbp = payload.get("vram_by_proc") or {}
    if not vbp.get("ok"):
        return ""
    big = int(vbp.get("big_mib", 0) or 0)
    tiny = int(vbp.get("tiny_mib", 0) or 0)
    other = int(vbp.get("other_mib", 0) or 0)
    used = big + tiny + other
    if used <= 0:
        return ""
    # Show breakdown only when at least one of big/tiny is non-zero (i.e. we
    # have something to attribute). When a non-cortexagent consumer (browser /
    # game / diffusion) is also on the GPU, append it so the user knows.
    parts = []
    if big:
        parts.append(f"big {big/1024:.1f} GB")
    if tiny:
        parts.append(f"tiny {tiny/1024:.1f} GB")
    if other and not (big and tiny):
        parts.append(f"other {other/1024:.1f} GB")
    if not parts:
        return f"{used/1024:.1f} GB"
    # Combine into a single compact segment with a forward slash to keep the
    # statusline scannable. "big 14.3 + tiny 0.9 GB" reads better than the
    # prior opaque "14.9/16 GB".
    total_used = f"{used/1024:.1f} GB"
    body = " + ".join(parts)
    return f"{body} / {total_used}"


def main():
    raw = sys.stdin.read()
    d = {}
    try:
        d = json.loads(raw) if raw.strip() else {}
    except Exception:
        d = {}

    model = ""
    m = d.get("model")
    if isinstance(m, dict):
        model = m.get("display_name") or m.get("id") or ""
    elif isinstance(m, str):
        model = m

    cwd = d.get("cwd") or d.get("workspace", {}).get("current_dir") or ""
    if cwd:
        home = os.path.expanduser("~")
        if cwd == home:
            cwd = "~"
        elif cwd.startswith(home + os.sep):
            cwd = "~" + cwd[len(home):]

    # Context usage
    ctx_str = ""
    cw = d.get("context_window") or {}
    if isinstance(cw, dict):
        used = cw.get("used") or cw.get("used_tokens") or cw.get("current")
        total = cw.get("total") or cw.get("limit") or cw.get("max")
        if used and total:
            ctx_str = f"{used}/{total} tok"
    if not ctx_str:
        ex = d.get("exceeds_200k_tokens")
        if isinstance(ex, dict):
            ctx_str = f"{ex.get('token_count','?')} tok"

    # Token metrics from proxy
    tok_metrics = _get_token_metrics()

    # VRAM breakdown from daemon (per-process: big / tiny / other)
    vram_breakdown = _get_vram_breakdown()

    # Minify savings — pulled from the proxy snapshot (separate from the
    # proxy /metrics endpoint so a stale proxy doesn't black out the savings
    # display). Shown only when there is actually a recorded run.
    minify_snapshot = _read_minify_snapshot()
    minify_str = ""
    try:
        runs = int(minify_snapshot.get("runs", 0) or 0)
        if runs > 0:
            ratio = float(minify_snapshot.get("ratio_pct", 0.0) or 0.0)
            saved = int(minify_snapshot.get("tokens_saved", 0) or 0)
            if saved > 0 and ratio > 0:
                # Truncate large numbers for scannability in the statusline.
                shown = (f"{saved // 1000}k" if saved >= 1000
                         else f"{saved}")
                minify_str = f"minify -{ratio:.0f}% ({shown})"
    except Exception:
        minify_str = ""

    # Use the author tag as the brand; drop the leading literal "CortexAgent"
    # (author already defaults to "CortexAgent"). Also skip the model field
    # when it duplicates the brand (e.g. local alias "cortexagent").
    brand = str(CFG.author) or "CortexAgent"
    parts = [brand]
    if model and model.strip().lower() != brand.strip().lower():
        parts.append(model)
    if cwd:
        parts.append(cwd)
    if ctx_str:
        parts.append(ctx_str)
    if tok_metrics:
        parts.append(tok_metrics)
    if vram_breakdown:
        parts.append(vram_breakdown)
    if minify_str:
        parts.append(minify_str)
    print(" · ".join(str(p) for p in parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(f"CortexAgent · {CFG.author}")
