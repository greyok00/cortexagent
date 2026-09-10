
from __future__ import annotations

import re
from typing import List

_STRIP = re.compile(r"[()\[\]{}]")
_WS = re.compile(r"\s+")


def normalize_cron(expr: str) -> str:

    if not expr:
        return ""
    s = _STRIP.sub(" ", expr)
    s = s.replace(",", " ")
    s = _WS.sub(" ", s).strip()
    fields = s.split()
    if len(fields) != 5:
        return ""

    for f in fields:
        if not re.fullmatch(r"[0-9*/\-,]+", f):
            return ""
    return " ".join(fields)


def humanize_cron(expr: str) -> str:

    norm = normalize_cron(expr)
    if not norm:
        return ""
    f = norm.split()
    minute, hour, dom, month, dow = f


    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "hourly"

    if dom == "*" and month == "*" and dow == "*":
        return f"daily {hour.zfill(2)}:{minute.zfill(2)}"

    if dom == "*" and month == "*" and dow != "*":
        day = _DOW.get(dow, dow)
        return f"weekly {day} {hour.zfill(2)}:{minute.zfill(2)}"

    if dom != "*" and month == "*" and dow == "*":
        return f"monthly day {dom} {hour.zfill(2)}:{minute.zfill(2)}"
    return norm


_DOW = {
    "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
    "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun",
}


def dedupe_tasks(tasks: List[dict]) -> List[dict]:

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
