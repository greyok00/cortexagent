from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple

DISPATCHER_DIR = pathlib.Path.home() / "dispatcher" / "data"
QUEUE_LOG = DISPATCHER_DIR / "queue.jsonl"
METRICS_LOG = DISPATCHER_DIR / "metrics.jsonl"
TRIAGE_LOG = DISPATCHER_DIR / "secops-triage.log"
MCP_STATUS = pathlib.Path.home() / ".cortexagent" / "mcp-status" / "dispatcher.json"
UNREPLIED = pathlib.Path.home() / ".config" / "messenger" / "unreplied.json"

_QUEUE_TAIL = 600
_METRICS_TAIL = 200

def _tail_lines(path: pathlib.Path, n: int) -> List[str]:
    try:
        with path.open("r", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []

def _read_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None

def collect() -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    cloud = local = 0
    for line in _tail_lines(QUEUE_LOG, _QUEUE_TAIL):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("op") != "add":
            continue
        if rec.get("route") == "cloud":
            cloud += 1
        else:
            local += 1
    total = cloud + local
    out["routes"] = {"cloud": cloud, "local": local,
                     "pct_cloud": round(100 * cloud / total, 1) if total else None}

    events: List[Tuple[str, str, str]] = []
    for line in _tail_lines(METRICS_LOG, _METRICS_TAIL):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        kind = rec.get("event", "")
        if kind in ("struggle", "escalated", "error", "blocked"):
            detail = (rec.get("detail") or rec.get("failure")
                      or rec.get("kind") or "")
            events.append((str(rec.get("ts", "")), str(kind),
                           str(detail)[:60]))
    out["alerts"] = events[-3:]

    tri_lines = [ln.rstrip("\n") for ln in _tail_lines(TRIAGE_LOG, 12)]
    verdict = next((ln.strip() for ln in reversed(tri_lines)
                    if "→ triage" in ln), "")
    action = next((ln.strip()[:80] for ln in reversed(tri_lines)
                   if ln.strip() and "→ triage" not in ln), "")
    out["secops"] = {"verdict": verdict, "action": action}

    unr = _read_json(UNREPLIED) or {}
    out["messaging"] = {"unreplied": int(unr.get("count", 0)),
                        "checked": str(unr.get("ts", "—"))}

    st = _read_json(MCP_STATUS) or {}
    out["dispatch"] = [str(x) for x in st.get("lines", [])][:2]
    return out

def strip_text() -> str:
    try:
        d = collect()
    except Exception:
        return ""

    def dim(s: str) -> str:
        return f"\x1b[2m{s}\x1b[0m" if s else ""

    def cyan(s: str) -> str:
        return f"\x1b[36m{s}\x1b[0m" if s else ""

    def red(s: str) -> str:
        return f"\x1b[31m{s}\x1b[0m" if s else ""

    def green(s: str) -> str:
        return f"\x1b[32m{s}\x1b[0m" if s else ""

    segs: List[str] = []

    r = d["routes"]
    pct = r["pct_cloud"]
    if pct is not None:
        segs.append(f"☁{pct:.0f}%·⬢{100 - pct:.0f}%")
    else:
        segs.append(dim("☁—"))

    disp = d["dispatch"]
    if disp:
        import re
        m = re.findall(r"(\d+)\s+(queued|running)", disp[0])
        counts = {k: v for v, k in m}
        segs.append(dim(f"q{counts.get('queued', 0)} "
                        f"r{counts.get('running', 0)}"))

    un = d["messaging"]["unreplied"]
    segs.append(red(f"✉{un}!") if un else green("✉✓"))

    v = d["secops"]["verdict"]
    if v:
        try:
            n = v.split("·")[-1].strip().split()[0]
        except Exception:
            n = ""
        if "needs-attention" in v.lower():
            segs.append(red(f"🔒{n} attention"))
        else:
            segs.append(green(f"🔒{n}"))

    alerts = d["alerts"]
    if alerts:
        ts, kind, detail = alerts[-1]
        short = {"escalated": "escalated", "struggle": "struggle",
                 "error": "failed", "blocked": "blocked"}.get(kind, kind)
        segs.append(red(f"⚠{short}"))
    else:
        segs.append(dim("⚠✓"))

    return " · ".join(s for s in segs if s)
