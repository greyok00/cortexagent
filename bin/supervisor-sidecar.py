#!/usr/bin/env python3
"""supervisor-sidecar.py - no-authority stats consumer for the supervision
plane (spec 2026-11-11 section 4) + the playbook distiller (section 6).
Reads supervision_events.jsonl only; writes stats.json / playbook.json /
sidecar.state.json (read offset). Never injects, blocks, or cancels: a dead
sidecar just degrades the runtime to nothing. Absent or corrupt input is
zero-data, not an error (exit 0). Writes are tmp + os.replace, so a partial
stats.json / playbook.json is never observable.

Effectiveness semantics (for the pruner): each fire of a (class, detail)
streak opens a settle window of RESOLVED_AFTER ticks. A same-key fire while
the window is open counts the previous fire as refired and refreshes the
window. A window reaching zero ticks with no refire counts as resolved. When
the sidecar stops observing (once mode, or the watch loop ends), every
still-open window closes exactly once as resolved: that is the clean-tail
settle, so a streak of N consecutive fires is N-1 refires + 1 resolve.
Windows are pass-local: they do not survive across runs, and a streak is
measured within one observation.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

STATE = Path.home() / "cortex-agent" / "state" / "supervision"
RESOLVED_AFTER = 30   # ticks (stream passes): no same-key refire = resolved
FIRE_THRESHOLD = 3    # distill: fires needed before a playbook entry

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
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1))
        os.replace(tmp, path)
    except OSError:
        pass


def collect(events_path: Path, offset: int):
    """Append-only read with rotation resync (supervised-steer lesson
    2026-11-09: a shrunken file resyncs to EOF, never replays history).
    A trailing partial line is withheld until its newline arrives, so a torn
    record is never consumed and dropped."""
    try:
        size = events_path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        return [], size                      # rotated/truncated: resync
    if size <= offset:
        return [], offset
    with events_path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(size - offset).decode("utf-8", errors="replace")
    if not chunk.endswith("\n"):
        cut = chunk.rfind("\n")
        if cut < 0:
            return [], offset                # no complete line yet
        return chunk[:cut].splitlines(), offset + cut + 1
    return chunk.splitlines(), size


def aggregate(lines, acc: dict):
    """Fold stream records into the accumulator. Counts are cumulative
    across rotations (the offset tracks position, never resets counts).
    Each fire opens or refreshes its streak window; a fire on an open
    window counts the previous fire as refired."""
    pending = acc["_pending"]
    fired_now = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        det = rec.get("detector")
        if not det or not det.get("class"):
            continue
        cls = det["class"]
        detail = str(det.get("detail", ""))[:80]
        fired_now.add(cls)
        acc["failureCounts"][cls] = acc["failureCounts"].get(cls, 0) + 1
        dc = acc["detailCounts"].setdefault(cls, {})
        dc[detail] = dc.get(detail, 0) + 1
        se = acc["steerEffectiveness"].setdefault(cls, {"fired": 0, "resolved": 0, "refired": 0})
        se["fired"] += 1
        key = f"{cls}|{detail[:48]}"
        if key in pending:
            se["refired"] += 1               # previous fire counts as refired
        pending[key] = {"remaining": RESOLVED_AFTER, "se": se, "cls": cls}
    acc["_firedNow"] = fired_now


def tick_windows(acc: dict):
    """One observation tick elapsed: advance every open streak window; a
    window hitting zero with no refire counts as resolved."""
    pending = acc["_pending"]
    for key in list(pending):
        w = pending[key]
        w["remaining"] -= 1
        if w["remaining"] <= 0:
            w["se"]["resolved"] += 1
            del pending[key]


def settle(acc: dict):
    """End of observation: each still-open streak window closes exactly once
    as resolved (clean tail), then windows are dropped (pass-local)."""
    pending = acc["_pending"]
    for w in pending.values():
        w["se"]["resolved"] += 1
    pending.clear()


def distill(sd_dir: Path, acc: dict, age: bool, rulebook_path: Path):
    """Section 6: one prose rule per recurring failure class (threshold 3);
    the distiller owns the texts and records provenance. With --age, one
    idle session bumps sessionsUnfired on entries whose class did not fire
    this pass; an entry past playbookAgeSessions (default 5) ages out."""
    pb_path = sd_dir / "playbook.json"
    pb = _read_json(pb_path, {"entries": []})
    entries = pb.get("entries", [])
    fired = acc.get("_firedNow", set())
    have = {e.get("cls") for e in entries}
    for cls, counts in acc["detailCounts"].items():
        if acc["failureCounts"].get(cls, 0) >= FIRE_THRESHOLD and cls not in have:
            top = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
            entries.append({
                "cls": cls,
                "text": PLAYBOOK_TEXTS.get(cls, f"[supervisor] past sessions hit {cls} often; stay alert for the pattern."),
                "learnedFrom": f"replay ledger: {acc['failureCounts'][cls]} fires of {cls} (top: {top[:40]})",
                "ts": int(time.time()),
                "sessionsUnfired": 0,
            })
            have.add(cls)
    try:
        max_age = int(_read_json(rulebook_path, {}).get("playbookAgeSessions", 5))
    except Exception:
        max_age = 5
    if age:
        for e in entries:
            if e.get("cls") not in fired:
                e["sessionsUnfired"] = e.get("sessionsUnfired", 0) + 1
    entries = [e for e in entries if e.get("sessionsUnfired", 0) < max_age]
    _write_json(pb_path, {"entries": entries})


def emit(stats_path: Path, acc: dict, rulebook_path: Path):
    version = _read_json(rulebook_path, {}).get("version", 0)
    out = {"ts": int(time.time()),
           "rulebookVersion": version,
           "failureCounts": acc["failureCounts"],
           "detailCounts": acc["detailCounts"],
           "steerEffectiveness": acc["steerEffectiveness"],
           "classesUnfired": acc.get("classesUnfired", {})}
    _write_json(stats_path, out)


def main() -> int:
    args = parse_args()
    acc = {"failureCounts": {}, "detailCounts": {}, "steerEffectiveness": {},
           "classesUnfired": {}, "_pending": {}, "_firedNow": set()}
    prev = _read_json(Path(args.stats), None)
    if isinstance(prev, dict):
        for k in ("failureCounts", "detailCounts", "steerEffectiveness", "classesUnfired"):
            if isinstance(prev.get(k), dict):
                acc[k] = prev[k]
    offset = 0
    st = _read_json(Path(args.state), None)
    if isinstance(st, dict) and isinstance(st.get("offset"), int):
        offset = st["offset"]
    try:
        while True:
            acc["_firedNow"] = set()
            lines, offset = collect(Path(args.events), offset)
            if lines:
                aggregate(lines, acc)
            _write_json(Path(args.state), {"offset": offset})
            if args.distill:
                distill(Path(args.sd_dir), acc, args.age, Path(args.rulebook))
            tick_windows(acc)
            emit(Path(args.stats), acc, Path(args.rulebook))
            if args.once or not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        settle(acc)
        emit(Path(args.stats), acc, Path(args.rulebook))
    return 0


if __name__ == "__main__":
    sys.exit(main())
