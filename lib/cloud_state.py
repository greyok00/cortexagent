"""Status-strip state: the messenger area leads, then the ops indicators.

2026-10-04 (owner order): the cloud readout that used to head this strip is
gone. It counted `route == "cloud"` records in ~/dispatcher/data/queue.jsonl,
and after that file went empty it had nothing to report, so the strip sat on a
stale "100% local" that never moved. The messenger took the slot it held: the
letter `M`, then how many texts and how many emails are waiting.

The dispatcher's `q{queued} r{running}` segment went with it — it read that
MCP server's status block with a regex for "queued"/"running" while the block
writes "waiting"/"busy", so it rendered q0 r0 no matter what the queue did.

Waiting counts come from ~/.config/messenger/unreplied.json: one entry per open
inbound message, each tagged `channel` ("sms" = text, "email" = email).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple

DISPATCHER_DIR = pathlib.Path.home() / "dispatcher" / "data"
METRICS_LOG = DISPATCHER_DIR / "metrics.jsonl"
TRIAGE_LOG = DISPATCHER_DIR / "secops-triage.log"
UNREPLIED = pathlib.Path.home() / ".config" / "messenger" / "unreplied.json"

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
    items = unr.get("unreplied")
    if not isinstance(items, list):
        items = []
    out["messaging"] = {
        "texts": sum(1 for e in items
                     if isinstance(e, dict) and e.get("channel") == "sms"),
        "emails": sum(1 for e in items
                      if isinstance(e, dict) and e.get("channel") == "email"),
        "checked": str(unr.get("ts", "—")),
    }
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

    # Messenger leads: the letter M sits where the cloud icon used to, then one
    # count per channel. Red with a "!" means something is waiting on a reply.
    m = d["messaging"]

    def waiting(n: int, noun: str) -> str:
        if n:
            return red(f"{n} {noun}{'s' if n != 1 else ''}!")
        return green(f"{noun}s ✓")

    segs.append("M")
    segs.append(waiting(m["texts"], "text"))
    segs.append(waiting(m["emails"], "email"))

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
