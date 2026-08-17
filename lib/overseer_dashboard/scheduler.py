"""lib/overseer_dashboard/scheduler.py — scheduler state helpers.

Cron normalization per the spec:
  - strip accidental ``()`` ``[]`` ``{}``
  - replace commas with spaces
  - collapse whitespace
  - validate exactly five Unix cron fields
  - humanize recognized schedules
  - deduplicate tasks by stable ID
"""
from __future__ import annotations

import re
from typing import List, Optional

_STRIP = re.compile(r"[()\[\]{}]")
_WS = re.compile(r"\s+")


def normalize_cron(expr: str) -> str:
    """Return a normalized 5-field cron string, or '' if invalid."""
    if not expr:
        return ""
    s = _STRIP.sub(" ", expr)
    s = s.replace(",", " ")
    s = _WS.sub(" ", s).strip()
    fields = s.split()
    if len(fields) != 5:
        return ""
    # Each field must be a valid cron token (digits, *, /, -, ranges).
    for f in fields:
        if not re.fullmatch(r"[0-9*/\-,]+", f):
            return ""
    return " ".join(fields)


def humanize_cron(expr: str) -> str:
    """Humanize a normalized 5-field cron. Returns '' if not recognized."""
    norm = normalize_cron(expr)
    if not norm:
        return ""
    f = norm.split()
    minute, hour, dom, month, dow = f

    # Hourly: 0 * * * * → "hourly"
    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "hourly"
    # Daily: 0 9 * * * → "daily 09:00"
    if dom == "*" and month == "*" and dow == "*":
        return f"daily {hour.zfill(2)}:{minute.zfill(2)}"
    # Weekly: 0 9 * * 1 → "weekly Mon 09:00"
    if dom == "*" and month == "*" and dow != "*":
        day = _DOW.get(dow, dow)
        return f"weekly {day} {hour.zfill(2)}:{minute.zfill(2)}"
    # Monthly: 0 9 1 * * → "monthly day 1 09:00"
    if dom != "*" and month == "*" and dow == "*":
        return f"monthly day {dom} {hour.zfill(2)}:{minute.zfill(2)}"
    return norm


_DOW = {
    "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
    "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun",
}


def dedupe_tasks(tasks: List[dict]) -> List[dict]:
    """Deduplicate scheduler tasks by stable ID, keeping the first occurrence."""
    seen: set = set()
    out: List[dict] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or t.get("name") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(t)
    return out
