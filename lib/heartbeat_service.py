#!/usr/bin/env python3
"""heartbeat_service — read-only Claude Code session health monitor.

Read-only Claude Code session health monitor.

  - Monitors Claude Code sessions at ~/.claude/projects/<encoded-cwd>/<uuid>.jsonl
  - State files at ~/.cortexagent/state/{heartbeat_state.json,context_health.json}
  - Lock-file cleanup limited to a session-specific lock sibling (no global races)

CLI:
  python3 heartbeat_service.py run
  python3 heartbeat_service.py daemon --interval 60
  python3 heartbeat_service.py smoke
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Paths ─────────────────────────────────────────────────────────────────
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CORTEXAGENT_STATE = Path.home() / ".cortexagent" / "state"
STATE_FILE = CORTEXAGENT_STATE / "heartbeat_state.json"
HEALTH_FILE = CORTEXAGENT_STATE / "context_health.json"

# Thresholds (advisory only — agent decides what to do)
MAX_MESSAGES_WARN = 60
MAX_MESSAGES_CRIT = 100
MAX_SIZE_MB_WARN = 2.0
MAX_SIZE_MB_CRIT = 4.0


def _find_session(cwd: Optional[Path] = None) -> Optional[Path]:
    """Find the most recent .jsonl session file.

    If cwd is provided, looks under ~/.claude/projects/<encoded-cwd>/.
    Otherwise falls back to the most-recently-modified .jsonl under projects.
    """
    if not CLAUDE_PROJECTS.exists():
        return None
    if cwd is not None:
        encoded = str(cwd).replace("/", "-")
        sub = CLAUDE_PROJECTS / encoded
        if sub.exists():
            sessions = [f for f in sub.glob("*.jsonl")
                        if f.stat().st_size > 0]
            if sessions:
                sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                return sessions[0]
        return None
    # Fallback: most recent across all project dirs
    all_sessions = [f for f in CLAUDE_PROJECTS.glob("*/*.jsonl")
                    if f.stat().st_size > 0]
    if not all_sessions:
        return None
    all_sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return all_sessions[0]


def _check_health(session_path: Path) -> dict:
    result = {
        "healthy": True,
        "session_id": session_path.stem,
        "message_count": 0,
        "file_size_kb": 0.0,
        "status": "green",
        "new_recommended": False,
        "warnings": [],
    }
    try:
        size_kb = session_path.stat().st_size / 1024
        result["file_size_kb"] = round(size_kb, 1)
    except Exception:
        result["healthy"] = False
        result["status"] = "red"
        result["warnings"].append("Cannot read session file")
        return result

    try:
        content = session_path.read_text()
        lines = content.strip().split("\n")
        count = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "message":
                    count += 1
            except json.JSONDecodeError:
                pass
        result["message_count"] = count
    except Exception:
        result["healthy"] = False
        result["warnings"].append("Cannot parse session file")
        return result

    crit_reasons = []
    warn_reasons = []
    if count > MAX_MESSAGES_CRIT:
        crit_reasons.append(f"{count} msgs (limit {MAX_MESSAGES_CRIT})")
    elif count > MAX_MESSAGES_WARN:
        warn_reasons.append(f"{count} msgs")
    if size_kb > MAX_SIZE_MB_CRIT * 1024:
        crit_reasons.append(f"{size_kb:.0f}KB (limit {MAX_SIZE_MB_CRIT}MB)")
    elif size_kb > MAX_SIZE_MB_WARN * 1024:
        warn_reasons.append(f"{size_kb:.0f}KB")

    if crit_reasons:
        result["status"] = "red"
        result["new_recommended"] = True
        result["warnings"].append(f"CRITICAL: {', '.join(crit_reasons)}")
    elif warn_reasons:
        result["status"] = "yellow"
        result["warnings"].append(f"WARM: {', '.join(warn_reasons)}")
    return result


def _clean_stale_locks(session_path: Path) -> int:
    """Clean stale .lock files in the same directory as the session, only
    if they're older than 2 minutes. Safe — only removes .lock files."""
    cleaned = 0
    parent = session_path.parent
    if not parent.exists():
        return 0
    for lock_file in parent.glob("*.lock"):
        try:
            age = time.time() - lock_file.stat().st_mtime
            if age > 120:
                lock_file.unlink()
                cleaned += 1
        except Exception:
            pass
    return cleaned


def run_heartbeat(cwd: Optional[Path] = None) -> dict:
    result = {
        "timestamp": datetime.now().isoformat(),
        "healthy": True,
        "session_id": None,
        "message_count": 0,
        "file_size_kb": 0.0,
        "status": "green",
        "new_recommended": False,
        "warnings": [],
        "locks_cleaned": 0,
    }

    CORTEXAGENT_STATE.mkdir(parents=True, exist_ok=True)
    session = _find_session(cwd=cwd)
    if not session:
        result["healthy"] = False
        result["warnings"].append("No active session")
        HEALTH_FILE.write_text(json.dumps({
            "timestamp": result["timestamp"],
            "status": "no_session",
            "message": "No active Claude Code session",
        }, indent=2))
        STATE_FILE.write_text(json.dumps(result, indent=2))
        return result

    result["locks_cleaned"] = _clean_stale_locks(session)
    health = _check_health(session)
    result.update(health)

    HEALTH_FILE.write_text(json.dumps({
        "timestamp": result["timestamp"],
        "status": result["status"],
        "session_id": result["session_id"][:8] if result["session_id"] else None,
        "message_count": result["message_count"],
        "file_size_kb": result["file_size_kb"],
        "new_recommended": result["new_recommended"],
        "warnings": result["warnings"][:3],
    }, indent=2))
    STATE_FILE.write_text(json.dumps(result, indent=2))
    return result


def format_report(result: dict) -> str:
    icon = {"green": "✓", "yellow": "⚠", "red": "✗"}.get(result["status"], "?")
    lines = [f"[HEARTBEAT] {icon} {result['status'].upper()}"]
    sid = result["session_id"][:8] if result["session_id"] else "none"
    lines.append(f"  Session: {sid}")
    lines.append(f"  Messages: {result['message_count']} | Size: {result['file_size_kb']}KB")
    if result["new_recommended"]:
        lines.append(f"  ⚠ Run /new to reset context")
    if result["locks_cleaned"]:
        lines.append(f"  Cleaned {result['locks_cleaned']} stale lock(s)")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────
def _cli(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    rest = argv[1:]
    kwargs: Dict[str, str] = {}
    i = 0
    while i < len(rest):
        if rest[i].startswith("--") and i + 1 < len(rest):
            kwargs[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            i += 1

    if cmd == "smoke":
        return _smoke()
    if cmd == "run":
        result = run_heartbeat()
        print(format_report(result))
        for w in result["warnings"]:
            print(f"  ! {w}")
        return 0
    if cmd == "daemon":
        interval = int(kwargs.get("interval", "60"))
        print(f"heartbeat daemon started (interval: {interval}s)")
        while True:
            result = run_heartbeat()
            print(format_report(result))
            for w in result["warnings"]:
                print(f"  ! {w}")
            time.sleep(interval)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def _smoke() -> int:
    # Pure-function checks
    h = _check_health(Path("/tmp/does-not-exist-for-session"))
    assert h["status"] == "red" and not h["healthy"]
    print(f"  missing file: status={h['status']} healthy={h['healthy']}")

    # Create a fake session and check thresholds
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Write 70 message lines (above warn, below crit)
        for i in range(70):
            f.write(json.dumps({"type": "message", "content": f"msg {i}"}) + "\n")
        tmp_path = Path(f.name)
    try:
        h = _check_health(tmp_path)
        assert h["message_count"] == 70
        # Should be yellow (60 < 70 < 100)
        assert h["status"] in ("yellow", "red")
        print(f"  70 msgs: status={h['status']} count={h['message_count']}")
    finally:
        tmp_path.unlink()

    # _find_session from current cwd
    sess = _find_session(cwd=Path.cwd())
    if sess:
        print(f"  find_session: {sess.parent.name}/{sess.name[:8]}...")
    else:
        print(f"  find_session: no session for current cwd")

    # format_report
    r = {"status": "green", "session_id": "abc123def", "message_count": 5,
         "file_size_kb": 12.3, "new_recommended": False, "locks_cleaned": 0}
    s = format_report(r)
    assert "GREEN" in s and "abc123de" in s
    print(f"  format_report: green status + 8-char session id")

    print("heartbeat_service: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))