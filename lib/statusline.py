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


def _get_token_metrics() -> str:
    """Fetch token metrics from the grammar proxy /metrics endpoint."""
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
            cur = data.get("current_tok_s", 0)
            avg = data.get("avg_tok_s", 0)
            if ct:
                parts.append(f"{ct} tok")
            if cur:
                parts.append(f"{cur} t/s")
            if reqs:
                parts.append(f"{reqs} req")
            vu = data.get("vram_used_mib")
            vt = data.get("vram_total_mib")
            if vu is not None and vt:
                parts.append(f"{vu/1024:.1f}/{vt/1024:.0f} GB")
            return " · ".join(parts) if parts else ""
    except Exception:
        return ""


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
    print(" · ".join(str(p) for p in parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(f"CortexAgent · {CFG.author}")
