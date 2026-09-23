#!/usr/bin/env python3

import json
import os
import sys
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib.config import CFG

def _get_token_metrics() -> str:

    metrics_port = 11436
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{metrics_port}/metrics",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            parts = []
            ct = data.get("completion_tokens", 0)
            reqs = data.get("requests", 0)
            in_tps = data.get("current_in_tps", 0)
            out_tps = data.get("current_out_tps") or data.get("current_tok_s", 0)
            if ct:
                parts.append(f"{ct} tok")

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

    tok_metrics = _get_token_metrics()

    brand = str(CFG.author) or "Cortex"
    parts = [brand]
    try:
        from lib.cloud_state import strip_text
        strip = strip_text()
        if strip:
            parts.append(strip)
    except Exception:
        pass
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
        print(f"Cortex · {CFG.author}")
