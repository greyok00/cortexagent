#!/usr/bin/env python3
"""supervisor-sidecar.py — no-authority stats consumer for the supervision
plane (spec 2026-11-11 §4) + the cross-session playbook distiller (§6).

Reads supervision_events.jsonl only; writes stats.json / playbook.json /
sidecar.state.json (offset). NEVER injects, blocks, or cancels — a dead
sidecar degrades the runtime to nothing. Absent or corrupt inputs are not
errors (exit 0, zeroed stats); partial JSON is never written (tmp + replace).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

STATE = Path.home() / "cortex-agent" / "state" / "supervision"
RESOLVED_AFTER = 30   # stream events: no same-class fire within window = settled
FIRE_THRESHOLD = 3    # distill: fires needed before a playbook entry
AGE_OUT = 5           # sessions without a firing before an entry ages out

# Distiller-owned per-class playbook texts (prose rule: one plain sentence,
# [supervisor] prefix, no codes, no em dashes).
PLAYBOOK_TEXTS = {
    "F1": "[supervisor] past sessions hit malformed call arguments often; re-check the argument shape before every structured call.",
    "F2": "[supervisor] past sessions hit bursts of tool errors and empty turns; verify one assumption (path, flag, environment) before the next call.",
    "F3": "[supervisor] past sessions repeated the same refused action; when a reason arrives, change the route instead of retrying.",
    "F4": "[supervisor] past sessions repeated identical work many times; run iteration as one compound command or a background job and read a single result.",
}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(STATE / "supervision_events.jsonl"))
    ap.add_argument("--stats", default=str(STATE / "stats.json"))
    ap.add_argument("--state", default=str(STATE / "sidecar.state.json"))
    ap.add_argument("--rulebook", default=str(STATE / "rulebook.json"))
    ap.add_argument("--sd-dir", default=str(STATE), help="dir for playbook.json")
    ap.add_argument("--distill", action="store_true")
    ap.add_argument("--age", action="store_true", help="one idle session: bump sessionsUnfired")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--once", action="store_true")
    return ap.parse_args()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json(path: Path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, str(path))


def collect(events_path: Path, offset: int):
    """Append-only read with rotation resync (supervised-steer lesson
    2026-11-09: a shrunken file resyncs to EOF, never replays history)."""
    try:
        size = events_path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        return [], size          # rotated/truncated: resync, no replay
    if size <= offset:
        return [], offset
    with events_path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(size - offset).decode("utf-8", errors="replace")
    return chunk.splitlines(), size


def fresh_acc(rulebook_version: int = 1) -> dict:
    return {"failureCounts": {}, "detailCounts": {}, "classesUnfired": {},
            "steerEffectiveness": {}, "_pending": {}, "_total": 0,
            "rulebookVersion": rulebook_version, "_since_settle": {}}


def aggregate(lines, acc: dict):
    """Fold stream lines into the stats accumulator. Sidecar stats are
    CUMULATIVE across rotations (counts never reset); offset only tracks
    the read position. Effectiveness is resolved per class: a fire that is
    not followed by a same-class fire within RESOLVED_AFTER records counts
    as resolved; a later same-class fire is a refire."""
    pending = acc.setdefault("_pending", {})
    since = acc.setdefault("_since_settle", {})
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        acc["_total"] += 1
        det = rec.get("detector") or {}
        cls = det.get("class") or (rec.get("detector_class") if rec.get("detector_class") else None)
        # advance settle counters for classes pending resolution
        for c in list(pending.keys()):
            if c == cls:
                pending[c] = 0                      # refire observed: reset window
                if c in acc["steerEffectiveness"]:
                    acc["steerEffectiveness"][c]["refired"] += 1
            else:
                pending[c] += 1
            if c in pending and pending[c] >= RESOLVED_AFTER:
                se = acc["steerEffectiveness"].setdefault(
                    c, {"fired": 0, "resolved": 0, "refired": 0})
                se["resolved"] += 1
                del pending[c]
        if not cls:
            continue
        fc = acc["failureCounts"]
        fc[cls] = fc.get(cls, 0) + 1
        dc = acc["detailCounts"].setdefault(cls, {})
        d = (det.get("detail") or "").strip()
        if d:
            dc[d] = dc.get(d, 0) + 1
        se = acc["steerEffectiveness"].setdefault(cls, {"fired": 0, "resolved": 0, "refired": 0})
        se["fired"] += 1
        # a fire opens a settle window (counting stops at RESOLVED_AFTER)
        pending.setdefault(cls, 0)
        # fired-classes stop aging
        acc["classesUnfired"].pop(cls, None)


def finalize(acc: dict) -> dict:
    out = {k: acc[k] for k in ("failureCounts", "detailCounts",
                               "classesUnfired", "steerEffectiveness",
                               "rulebookVersion", "ts") if k in acc}
    # end-of-stream: each still-open settle window resolves exactly ONCE
    # (the class settled its last fire). In-loop expiry already deleted
    # settled windows, so this adds one per open class, never double-counts.
    pending = acc.get("_pending", {})
    for c, n in pending.items():
        se = acc["steerEffectiveness"].setdefault(
            c, {"fired": 0, "resolved": 0, "refired": 0})
        if se["fired"]:
            se["resolved"] += 1
    out["ts"] = int(time.time())
    out["totalEvents"] = acc.get("_total", 0)
    return out


def distill(sd_dir: Path, acc: dict):
    """§6: one prose rule per recurring failure class (threshold 3),
    learnedFrom provenance; distiller owns the texts."""
    pb_path = sd_dir / "playbook.json"
    pb = _read_json(pb_path, {"entries": []})
    entries = pb.get("entries", [])
    by_cls = {e.get("cls"): e for e in entries}
    for cls, n in sorted(acc.get("failureCounts", {}).items()):
        if n < FIRE_THRESHOLD:
            continue
        e = by_cls.get(cls)
        if e is None:
            e = {"cls": cls, "text": PLAYBOOK_TEXTS.get(
                     cls, f"[supervisor] past sessions kept hitting {cls}; "
                          "change approach when a note arrives."),
                 "learnedFrom": f"sidecar ledger: {n} fires of {cls}",
                 "ts": int(time.time()), "sessionsUnfired": 0}
            entries.append(e)
            by_cls[cls] = e
    _write_json(pb_path, {"entries": entries})


def age_entries(sd_dir: Path):
    """§6: idle sessions bump sessionsUnfired; 5 without firing = age out."""
    pb_path = sd_dir / "playbook.json"
    pb = _read_json(pb_path, {"entries": []})
    kept = []
    for e in pb.get("entries", []):
        e["sessionsUnfired"] = int(e.get("sessionsUnfired", 0)) + 1
        if e["sessionsUnfired"] < AGE_OUT:
            kept.append(e)
    _write_json(pb_path, {"entries": kept})


def main() -> int:
    a = parse_args()
    events_path = Path(a.events)
    stats_path = Path(a.stats)
    state_path = Path(a.state)
    sd_dir = Path(a.sd_dir)
    st = _read_json(state_path, None) or {"offset": 0, "acc": None, "rulebookVersion": 1}
    acc = st.get("acc") or fresh_acc(st.get("rulebookVersion", 1))
    rb = _read_json(Path(a.rulebook), {}) or {}
    version = int(rb.get("version", st.get("rulebookVersion", 1)))
    acc["rulebookVersion"] = version

    while True:
        lines, st["offset"] = collect(events_path, st.get("offset", 0))
        aggregate(lines, acc)
        if a.distill:
            distill(sd_dir, acc)
        if a.age:
            age_entries(sd_dir)
        out = finalize(acc)
        _write_json(stats_path, out)
        _write_json(state_path, {"offset": st["offset"], "acc": acc,
                                 "rulebookVersion": version})
        if a.once or not a.watch:
            break
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
