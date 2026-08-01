#!/usr/bin/env python3
"""scheduler — minimal stdlib cron/interval/at scheduler.

A focused, no-deps scheduler for cortexagent. Stores jobs in a JSON file
at ~/.cortexagent/state/scheduler_jobs.json. Supports:

  - interval: every N seconds
  - at:       run once at a specific ISO timestamp
  - cron:     standard 5-field cron expression (minute hour dom mon dow)

Run as a foreground daemon (blocks), or run a single job once, or list jobs.

CLI:
  python3 scheduler.py add --name "nightly distill" --interval 86400 \
      --command "python3 lib/cold_distiller.py run"
  python3 scheduler.py add --name "evenings" --cron "0 18 * * *" \
      --command "echo 'evening'"
  python3 scheduler.py add --name "one-shot" --at "2026-08-01T09:00:00" \
      --command "echo done"
  python3 scheduler.py list
  python3 scheduler.py remove --name "nightly distill"
  python3 scheduler.py run-now --name "nightly distill"
  python3 scheduler.py daemon --tick 30
  python3 scheduler.py smoke
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


# ── Storage ───────────────────────────────────────────────────────────────
_JOBS_FILE = Path.home() / ".cortexagent" / "state" / "scheduler_jobs.json"
_LOCK = threading.Lock()


def _ensure_jobs_file() -> None:
    _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _JOBS_FILE.exists():
        _JOBS_FILE.write_text(json.dumps({"jobs": []}, indent=2))


def _load_jobs() -> Dict:
    _ensure_jobs_file()
    try:
        return json.loads(_JOBS_FILE.read_text())
    except Exception:
        return {"jobs": []}


def _save_jobs(data: Dict) -> None:
    _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _JOBS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Cron parser (5-field standard) ────────────────────────────────────────
def _cron_matches(expr: str, now: datetime) -> bool:
    """Check if `now` matches a 5-field cron expression."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, mon, dow = fields
    values = [now.minute, now.hour, now.day, now.month, now.weekday()]
    for fld, val in zip([minute, hour, dom, mon, dow], values):
        if fld == "*":
            continue
        if "," in fld:
            opts = [int(x) for x in fld.split(",")]
            if val not in opts:
                return False
        elif "/" in fld:
            base, step = fld.split("/")
            start = 0 if base == "*" else int(base)
            if val < start or (val - start) % int(step) != 0:
                return False
        elif "-" in fld:
            lo, hi = [int(x) for x in fld.split("-")]
            if val < lo or val > hi:
                return False
        else:
            if int(fld) != val:
                return False
    return True


# ── Job lifecycle ─────────────────────────────────────────────────────────
def add_job(name: str, command: str, schedule_type: str,
            schedule_value: str, profile: str = "default") -> Dict:
    """Add a job. schedule_type: 'interval' | 'at' | 'cron'."""
    if not name or not command or schedule_type not in ("interval", "at", "cron"):
        raise ValueError("invalid input: need name, command, and schedule_type in {interval, at, cron}")
    if schedule_type == "interval":
        try:
            interval = int(schedule_value)
            if interval <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("interval must be a positive integer (seconds)")
    elif schedule_type == "at":
        try:
            datetime.fromisoformat(schedule_value)
        except ValueError:
            raise ValueError("at must be an ISO timestamp (e.g. 2026-08-01T09:00:00)")
    elif schedule_type == "cron":
        if len(schedule_value.split()) != 5:
            raise ValueError("cron must have 5 fields: minute hour dom mon dow")
    with _LOCK:
        data = _load_jobs()
        # Replace existing job with the same name
        data["jobs"] = [j for j in data["jobs"] if j.get("name") != name]
        job = {
            "name": name,
            "command": command,
            "schedule_type": schedule_type,
            "schedule_value": schedule_value,
            "profile": profile,
            "created_at": datetime.now().isoformat(),
            "last_run": None,
            "last_status": None,
            "enabled": True,
        }
        if schedule_type == "interval":
            job["next_run"] = (datetime.now() + timedelta(seconds=int(schedule_value))).isoformat()
        elif schedule_type == "at":
            job["next_run"] = schedule_value
        else:
            job["next_run"] = None
        data["jobs"].append(job)
        _save_jobs(data)
    return job


def remove_job(name: str) -> bool:
    with _LOCK:
        data = _load_jobs()
        before = len(data["jobs"])
        data["jobs"] = [j for j in data["jobs"] if j.get("name") != name]
        if len(data["jobs"]) == before:
            return False
        _save_jobs(data)
    return True


def list_jobs() -> List[Dict]:
    with _LOCK:
        return list(_load_jobs().get("jobs", []))


def get_job(name: str) -> Optional[Dict]:
    with _LOCK:
        for j in _load_jobs().get("jobs", []):
            if j.get("name") == name:
                return j
    return None


def run_job(name: str, timeout: int = 600) -> Dict:
    """Run a job's command once. Records last_run / last_status."""
    job = get_job(name)
    if not job:
        return {"ok": False, "reason": f"no such job: {name}"}
    if not job.get("enabled", True):
        return {"ok": False, "reason": "job disabled"}
    try:
        result = subprocess.run(
            job["command"], shell=True, capture_output=True, text=True,
            timeout=timeout,
        )
        ok = result.returncode == 0
        status = "ok" if ok else f"exit {result.returncode}"
        with _LOCK:
            data = _load_jobs()
            for j in data["jobs"]:
                if j.get("name") == name:
                    j["last_run"] = datetime.now().isoformat()
                    j["last_status"] = status
                    if j["schedule_type"] == "interval":
                        j["next_run"] = (datetime.now() + timedelta(
                            seconds=int(j["schedule_value"]))).isoformat()
                    _save_jobs(data)
                    break
        return {
            "ok": ok,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _compute_next_run(job: Dict) -> Optional[str]:
    """Compute the next run time for a job, or None if past for 'at' jobs."""
    if job["schedule_type"] == "interval":
        if not job.get("last_run"):
            return datetime.now().isoformat()
        return (datetime.fromisoformat(job["last_run"]) +
                timedelta(seconds=int(job["schedule_value"]))).isoformat()
    if job["schedule_type"] == "at":
        return job["schedule_value"]
    return None  # cron: computed at tick time


def tick_due_jobs() -> List[str]:
    """Run any jobs that are due. Returns list of names that fired."""
    fired = []
    now = datetime.now()
    for job in list_jobs():
        if not job.get("enabled", True):
            continue
        due = False
        if job["schedule_type"] == "interval":
            next_run = job.get("next_run")
            if next_run and datetime.fromisoformat(next_run) <= now:
                due = True
        elif job["schedule_type"] == "at":
            at_time = datetime.fromisoformat(job["schedule_value"])
            if at_time <= now:
                due = True
                # Disable one-shot after firing
                with _LOCK:
                    data = _load_jobs()
                    for j in data["jobs"]:
                        if j.get("name") == job["name"]:
                            j["enabled"] = False
                            _save_jobs(data)
                            break
        elif job["schedule_type"] == "cron":
            if _cron_matches(job["schedule_value"], now):
                due = True
        if due:
            fired.append(job["name"])
            run_job(job["name"])
    return fired


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
    if cmd == "add":
        name = kwargs.get("name")
        command = kwargs.get("command")
        schedule_type = kwargs.get("type")
        schedule_value = kwargs.get("value") or kwargs.get("schedule")
        profile = kwargs.get("profile", "default")
        if not (name and command and schedule_type and schedule_value):
            print("required: --name --command --type --value", file=sys.stderr)
            return 2
        try:
            job = add_job(name, command, schedule_type, schedule_value, profile=profile)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(job, indent=2))
        return 0
    if cmd == "remove":
        name = kwargs.get("name")
        if not name:
            print("required: --name", file=sys.stderr)
            return 2
        ok = remove_job(name)
        print("removed" if ok else "not found")
        return 0 if ok else 1
    if cmd == "list":
        jobs = list_jobs()
        if not jobs:
            print("(no jobs)")
            return 0
        for j in jobs:
            print(f"{'✓' if j.get('enabled') else '✗'} {j['name']:30s} "
                  f"{j['schedule_type']:8s} {j['schedule_value']:20s} "
                  f"last={j.get('last_status') or '—'}")
        return 0
    if cmd == "run-now":
        name = kwargs.get("name")
        if not name:
            print("required: --name", file=sys.stderr)
            return 2
        result = run_job(name)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if cmd == "daemon":
        tick = int(kwargs.get("tick", "30"))
        print(f"scheduler daemon started (tick: {tick}s)")
        while True:
            fired = tick_due_jobs()
            if fired:
                print(f"fired: {', '.join(fired)}")
            time.sleep(tick)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def _smoke() -> int:
    # Use a temp file to avoid polluting user state
    global _JOBS_FILE
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "jobs.json"
    tmp.write_text(json.dumps({"jobs": []}))
    _JOBS_FILE = tmp

    # add_job (interval)
    job = add_job("test-interval", "echo hi", "interval", "60")
    assert job["schedule_type"] == "interval"
    assert get_job("test-interval") is not None
    print(f"  add interval: {job['name']} next_run={job['next_run'][:19]}")

    # add_job (cron)
    job = add_job("test-cron", "echo cron", "cron", "0 9 * * *")
    assert job["schedule_type"] == "cron"
    print(f"  add cron: {job['name']} schedule={job['schedule_value']}")

    # add_job (at)
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    job = add_job("test-at", "echo at", "at", future)
    assert job["schedule_type"] == "at"
    print(f"  add at: {job['name']} at={future[:19]}")

    # list_jobs
    jobs = list_jobs()
    assert len(jobs) == 3
    print(f"  list: {len(jobs)} jobs")

    # _cron_matches
    now = datetime(2026, 7, 31, 9, 0)  # Friday 9:00 AM
    assert _cron_matches("0 9 * * *", now)
    assert not _cron_matches("0 10 * * *", now)
    assert _cron_matches("*/5 * * * *", now)  # any minute divisible by 5
    assert _cron_matches("0 9 * * 4,5", now)  # Thu or Fri (4=Thu, 5=Fri)
    assert not _cron_matches("0 9 * * 1-3", now)  # Mon-Wed
    print(f"  cron_matches: wildcards, steps, ranges, lists all work")

    # run_job (real subprocess)
    result = run_job("test-interval")
    assert result["ok"]
    assert "hi" in result["stdout"]
    print(f"  run_job: ok={result['ok']} stdout={result['stdout'].strip()!r}")

    # run_job with failing command
    job = add_job("test-fail", "exit 7", "interval", "60")
    result = run_job("test-fail")
    assert not result["ok"] and result["returncode"] == 7
    print(f"  run_job fail: ok={result['ok']} rc={result['returncode']}")

    # remove_job
    assert remove_job("test-cron")  # remove cron
    assert remove_job("nonexistent-job-xyz") is False  # remove non-existent
    jobs = list_jobs()
    assert len(jobs) == 3  # interval, fail, at — cron removed
    print(f"  remove: {len(list_jobs())} jobs after remove")

    # tick_due_jobs: nothing should fire (no due jobs)
    fired = tick_due_jobs()
    assert fired == []
    print(f"  tick: no jobs due")

    # add immediate-fire job then tick
    past = (datetime.now() - timedelta(seconds=10)).isoformat()
    add_job("test-past", "echo fired", "at", past)
    # The 'at' job fires and disables itself
    fired = tick_due_jobs()
    assert "test-past" in fired
    assert get_job("test-past").get("enabled") is False
    print(f"  tick: at-job fired and disabled itself")

    # input validation
    try:
        add_job("", "x", "interval", "60")
        assert False, "should have raised"
    except ValueError:
        print(f"  validation: empty name rejected")

    print("scheduler: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))