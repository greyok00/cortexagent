#!/usr/bin/env python3
"""Session Injector — resume stalled/idle CLAUDE CODE sessions as secondary work.

Retargeted from OpenClaw (removed permanently) to Claude Code. When the injector
is enabled and a Claude Code session transcript goes idle (no changes for
idle_sec) AND is not currently held open by a running `claude` process, it fires
ONE headless `claude -p --resume` turn into that session so the stalled work is
pushed to a stable checkpoint. The moment a transcript shows fresh activity it
is skipped.

Controlled the same way as the STT daemon (state file + start/stop CLI), so the
STT tray can toggle it:
  python -m lib.session_injector start|stop|status|scan|once|dry-run

Safety rails (HARD):
  - Only resumes transcripts that are STALE and NOT locked by a live `claude`
    process (detected via /proc/<pid>/fd). Never writes to an open window.
  - Primary overrides secondary: a transcript with fresh activity is never touched.
  - Life/legal transcripts (slug path contains a life folder) are NEVER candidates.
  - Headless `-p` only, one turn; no interactive takeover, no `--continue` loop.
  - Flock-guarded, idempotent, cooldown so a transcript isn't re-fired before it
    advances.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

STATE_FILE = Path.home() / ".cortexagent" / "state" / "session_injector.json"
LOG_FILE = Path.home() / ".cortexagent" / "state" / "session_injector.log"
LOCK_FILE = Path.home() / ".cortexagent" / "state" / "session_injector.lock"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

DEFAULT_MODEL = "deepseek-v4-flash:cloud"

# Real coding projects the injector may feed to a resumed session. Order =
# default priority. Each entry: (path, resume-folder-name). Resume note = the
# project's resume file content, attached to the injected turn when the stale
# transcript maps to (or lives under) one of these project folders.
DEFAULT_PROJECTS = [
    "reframing-engine",
    "osint-portal",
    "legal-framework",
    "wordpress-plugins",
]

# Life/legal — NEVER a candidate, by hard rule. Blocked on the FOLDER NAME /
# slug path segment, so real projects whose names merely contain a fragment
# (e.g. "legal-framework") are NOT hit (their own slug segment is
# "legal-framework", not one of these).
LIFE_FOLDER_NAMES = frozenset({
    "wreck", "wreck-case", "claim", "records", "record-relief",
    "pii", "court", "court-records", "vehicle", "medical", "finance",
    "identity", "aml", "employment", "personal-legal-matters",
    "legal-cases", "Personal Legal Matters",
})

RESUME_FILENAMES = ("god.md", "preprompt.md", "RESUME.md", "README.md", "README.rst")

COOLDOWN_SEC = 3600  # don't re-resume the same transcript within an hour unless it moved


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(msg: str, lvl: str = "INFO") -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{_now_iso()}] [{lvl}] {msg}\n")
    except Exception:
        pass
    print(f"[session-injector] {msg}", file=sys.stderr, flush=True)


def _default_state() -> dict:
    return {
        "enabled": False,
        "idle_sec": 600,
        "max_age_sec": 604800,   # skip sessions idle longer than 7 days (finished/abandoned)
        "interval_sec": 300,
        "model": DEFAULT_MODEL,
        "projects": list(DEFAULT_PROJECTS),
        "last_inject_ts": None,
        "last_fired": None,
        "resumed": {},  # session_id -> (ts, mtime) of last resume, for cooldown
    }


def _read_state() -> dict:
    st = _default_state()
    try:
        saved = json.loads(STATE_FILE.read_text())
        if isinstance(saved, dict):
            st.update(saved)
    except Exception:
        pass
    return st


def _write_state(**updates) -> dict:
    st = _read_state()
    st.update(updates)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=2))
    return st


# ---------------------------------------------------------------------------
# Live-transcript locking (SAFETY FLOOR) — never write to an open window
# ---------------------------------------------------------------------------


def _active_session_ids() -> set:
    """Session ids currently bound to a running `claude` process.

    Claude Code writes one file per live process at ~/.claude/sessions/<pid>.json
    containing the sessionId that process is actively driving. Those transcripts
    are OFF-LIMITS: a running process owns them and a second writer corrupts the
    file. This is what keeps the injector away from the terminal window the user
    has open. Stale files for dead pids are ignored (pid must still be alive).
    """
    active = set()
    sdir = CLAUDE_PROJECTS.parent / "sessions"
    if not sdir.is_dir():
        return active
    for f in sdir.glob("*.json"):
        pid = f.stem
        if not pid.isdigit():
            continue
        try:
            os.kill(int(pid), 0)
        except (ProcessLookupError, ValueError, OSError):
            continue  # process gone → stale file, ignore
        try:
            data = json.loads(f.read_text())
            sid = data.get("sessionId")
            if sid:
                active.add(sid)
        except Exception:
            continue
    return active


# ---------------------------------------------------------------------------
# Scanner (shelved projects) + resumable-transcript discovery
# ---------------------------------------------------------------------------


def _is_life_path(path: Path) -> bool:
    """True if any slug path segment names a life/legal folder."""
    for seg in path.parts:
        if seg.lower() in LIFE_FOLDER_NAMES:
            return True
    return False


def _slug_to_cwd(slug: str, home: Path) -> Path:
    """Reverse Claude Code's slug encoding → candidate working dir. Verified."""
    guess = Path("/" + slug.replace("-", "/"))
    if guess.is_dir():
        return guess
    return home


def _resume_point(path: Path):
    """Return the best resume file (Path) or None for a shelved project folder."""
    for fn in RESUME_FILENAMES:
        p = path / fn
        if p.is_file():
            return p
    for sub in ("cases", "docs"):
        d = path / sub
        if d.is_dir():
            for fn in ("god.md", "preprompt.md"):
                found = sorted(d.rglob(fn))
                if found:
                    return found[0]
    return None


def _has_code(path: Path) -> bool:
    try:
        for ext in (".py", ".ts", ".js", ".jsx", ".tsx", ".php", ".go", ".rs"):
            if list(path.rglob(f"*{ext}")):
                return True
    except Exception:
        pass
    return False


def scan() -> list[dict]:
    """Workable shelved coding projects (resume file + code + not-life)."""
    st = _read_state()
    candidates = []
    for name in st["projects"]:
        path = Path.home() / name
        if not path.is_dir():
            continue
        if _is_life_path(path):
            _log(f"skip (blocked) {name}", "WARN")
            continue
        resume = _resume_point(path)
        code = _has_code(path)
        if resume is None or not code:
            _log(f"skip (not workable: resume={bool(resume)} code={code}) {name}", "WARN")
            continue
        try:
            mtime = resume.stat().st_mtime
        except Exception:
            mtime = 0
        candidates.append({
            "name": name,
            "path": str(path),
            "resume": str(resume),
            "oldest_mtime": mtime,
        })
    candidates.sort(key=lambda c: c["oldest_mtime"])
    return candidates


def project_for_slug(slug: str, projects: list[dict]) -> dict | None:
    """Map a transcript slug back to a shelved project folder if it's under one.

    Claude slug for /home/grey/reframing-engine is -home-grey-reframing-engine
    (path separators and the leading slash become '-'). Match exactly so the
    shelved project's resume note is attached to the resumed turn.
    """
    for cand in projects:
        pdir = Path(cand["path"])
        if slug == "-" + str(pdir).replace("/", "-"):
            return cand
    return None


def discover_resumable(idle_sec: int) -> list[dict]:
    """Claude Code transcripts that are stale, unlocked, and not life/legal.

    Returns sorted most-stale-first. Each entry carries the fields the loop and
    tray need (age, idle, locked, live, slug, cwd, session_id, path).
    """
    active = _active_session_ids()
    result = []
    if not CLAUDE_PROJECTS.is_dir():
        return result
    now = time.time()
    for pdir in CLAUDE_PROJECTS.iterdir():
        if not pdir.is_dir():
            continue
        slug = pdir.name
        cwd = _slug_to_cwd(slug, Path.home())
        if _is_life_path(cwd):
            continue
        for f in pdir.glob("*.jsonl"):
            if "trajectory" in f.name:
                continue
            try:
                mtime = f.stat().st_mtime
                size = f.stat().st_size
            except Exception:
                continue
            session_id = f.stem
            is_locked = session_id in active
            age = now - mtime
            result.append({
                "slug": slug,
                "session_id": session_id,
                "path": str(f),
                "cwd": str(cwd),
                "age_sec": round(age, 1),
                "idle": age > idle_sec,
                "locked": is_locked,       # a live claude owns it right now
                "live": is_locked,         # keep tray vocabulary: live == owned open
                "size": size,
            })
    result.sort(key=lambda s: s["age_sec"], reverse=True)  # most-idle first
    return result


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def _build_resume_text(sess: dict, project: dict | None) -> str:
    header = (
        f"[session-injector] Secondary fallback — your session went idle.\n"
        f"Finish the current work to a stable checkpoint, then STOP and give a "
        f"one-line status. You are fallback/secondary work: if primary work is "
        f"happening, yield and stop. Do not keep looping.\n"
        f"Shelf: {sess['slug']}\n" + ("=" * 40) + "\n"
    )
    if project:
        try:
            note = Path(project["resume"]).read_text(errors="ignore")[:4000]
        except Exception:
            note = ""
        header += (
            f"This session maps to shelved project '{project['name']}'. Continue it "
            f"from its resume note:\n{note or '(no resume content)'}\n"
        )
    return header


def inject(sess: dict, project: dict | None, model: str) -> dict:
    """Fire ONE headless turn into a stale Claude transcript via --resume."""
    text = _build_resume_text(sess, project)
    msg_path = LOG_FILE.parent / f"inject-{sess['session_id'][:8]}.txt"
    try:
        msg_path.write_text(text)
    except Exception as e:
        return {"ok": False, "reason": f"write msg: {e}"}

    cmd = [
        "claude", "-p", text,
        "--resume", sess["session_id"],
        "--model", model,
        "--permission-mode", "acceptEdits",
        "--output-format", "text",
    ]
    _log(f"resume -> slug={sess['slug']} session={sess['session_id'][:8]} "
         f"cwd={sess['cwd']} project={project['name'] if project else 'generic'}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=sess["cwd"], timeout=1500)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return {"ok": r.returncode == 0, "rc": r.returncode, "out": out[:500]}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def run_loop(once: bool = False, dry_run: bool = False) -> int:
    st = _read_state()
    cooldown = st.get("resumed", {})

    while True:
        st = _read_state()
        if not st["enabled"] and not dry_run:
            if once:
                return 0
            time.sleep(st.get("interval_sec", 300))
            continue

        projects = scan()
        sessions = discover_resumable(st.get("idle_sec", 600))
        # Only stale, not-live, not-finished transcripts are targets (safety floor).
        max_age = st.get("max_age_sec", 604800)
        targets = [s for s in sessions
                   if s["idle"] and not s["locked"] and s["age_sec"] < max_age]

        if not targets:
            live_n = sum(1 for s in sessions if s["locked"])
            _log(f"no resumable stale targets (live/owned open: {live_n}) — stepping back", "DEBG")
        else:
            for t in targets:
                # cooldown: skip a transcript we already resumed unless it advanced
                prev = cooldown.get(t["session_id"])
                if prev:
                    try:
                        if abs(t["age_sec"] - prev["mtime"]) < 5 and \
                           (time.time() - prev["ts"]) < COOLDOWN_SEC:
                            continue
                    except Exception:
                        continue
                project = project_for_slug(t["slug"], projects)
                if dry_run:
                    _log(f"[dry-run] would resume -> slug={t['slug']} "
                         f"session={t['session_id'][:8]} "
                         f"age={t['age_sec']}s locked={t['locked']} "
                         f"project={project['name'] if project else 'generic'}")
                    continue
                res = inject(t, project, st.get("model", DEFAULT_MODEL))
                cooldown[t["session_id"]] = {"ts": time.time(), "mtime": t["age_sec"]}
                _write_state(resumed=cooldown,
                             last_inject_ts=_now_iso(),
                             last_fired=f"{t['slug']}/{t['session_id'][:8]}")
                _log(f"inject result ok={res.get('ok')} "
                     f"{str(res.get('out', res.get('reason', '')))[:200]}")
                break  # one resume per tick
        if once:
            return 0
        time.sleep(st.get("interval_sec", 300))


# ---------------------------------------------------------------------------
# Daemon lifecycle (state file + pid + flock)
# ---------------------------------------------------------------------------


def is_running() -> bool:
    try:
        if LOCK_FILE.exists():
            pid = int(LOCK_FILE.read_text().strip().split("\n")[0])
            os.kill(pid, 0)
            return True
    except (ValueError, ProcessLookupError, OSError, FileNotFoundError):
        pass
    return False


def _acquire() -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOCK_FILE, "w") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            lf.truncate()
            lf.write(str(os.getpid()))
            lf.flush()
        return True
    except Exception:
        return False


def _release() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CortexAgent Session Injector (Claude Code)")
    ap.add_argument("command", nargs="?", default="status",
                    choices=["start", "stop", "status", "dry-run", "scan", "once"])
    ap.add_argument("--project", action="append", help="add a project folder name")
    ap.add_argument("--idle", type=int, help="idle seconds threshold")
    ap.add_argument("--model", help="claude --model to route the resume through")
    args = ap.parse_args(argv)

    if args.project:
        st = _read_state()
        projects = list(st["projects"])
        for p in args.project:
            if p not in projects:
                projects.append(p)
        _write_state(projects=projects)
        print(f"projects now: {projects}")
        return 0
    if args.idle:
        _write_state(idle_sec=args.idle)
        print(f"idle_sec now: {args.idle}")
        return 0
    if args.model:
        _write_state(model=args.model)
        print(f"model now: {args.model}")
        return 0

    cmd = args.command
    if cmd == "start":
        if is_running():
            print("already running")
            return 0
        if not _acquire():
            print("could not acquire lock")
            return 1
        _write_state(enabled=True)
        _log("daemon started (enabled=True)")
        try:
            return run_loop()
        finally:
            _release()
    elif cmd == "once":
        return run_loop(once=True)
    elif cmd == "dry-run":
        return run_loop(once=True, dry_run=True)
    elif cmd == "scan":
        print(f"active (owned-open) session ids: {sorted(_active_session_ids())}")
        print("shelved projects:")
        for c in scan():
            print(f"  ✓ {c['name']:20s} resume={c['resume']}")
        print("claude transcripts (across all slugs):")
        for s in discover_resumable(_read_state().get("idle_sec", 600)):
            print(f"  {'LOCKED ' if s['locked'] else ('idle ' if s['idle'] else 'busy ')} "
                  f"{s['slug']}/{s['session_id'][:8]} age={s['age_sec']}s ")
        return 0
    elif cmd == "stop":
        _write_state(enabled=False)
        pid = None
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip().split("\n")[0])
            except Exception:
                pid = None
        _release()
        if pid:
            try:
                os.kill(pid, 2)
            except ProcessLookupError:
                pass
        _log("stopped (enabled=False)")
        print("stopped")
        return 0
    else:  # status
        st = _read_state()
        print(json.dumps({"running": is_running(), **st}, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
