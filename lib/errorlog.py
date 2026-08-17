"""Structured error logging + crash dumps for CortexAgent components.

Every long-running component (overseer, daemon, grammar_proxy) routes its
uncaught exceptions and shutdown events through this module so a failure
carries enough context to resolve it quickly:

- A concise, structured one-line log entry:
  ``ERROR <Type>: <msg> (crashdump: <path>)``
- A full crash dump (JSON) with traceback, component, pid, uptime, and optional
  caller-supplied state.

Usage:
    from lib.errorlog import log_exception, close_dump

    try:
        ...
    except Exception as e:
        log_exception(e, component="overseer", context={"tick": tick}, log_file=LOG_FILE)

    # on clean shutdown (SIGINT/SIGTERM):
    close_dump(component="overseer", reason="SIGINT", context={"ticks": tick}, log_file=LOG_FILE)

Crash dumps land in ``~/.cortexagent/crashdumps/`` (override via
``CORTEXAGENT_CRASH_DIR``). Stdlib only — safe to import from any component.
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

_PROC_START = time.time()

# Crash dumps land here (override via CORTEXAGENT_CRASH_DIR).
CRASH_DIR = Path(os.environ.get("CORTEXAGENT_CRASH_DIR", "~/.cortexagent/crashdumps")).expanduser()


def _dump_path(component: str) -> Path:
    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    return CRASH_DIR / f"{component}-{ts}-{os.getpid()}.json"


def _write_dump(dump: dict) -> Path:
    path = _dump_path(dump["component"])
    try:
        path.write_text(json.dumps(dump, indent=2, default=str))
    except Exception:
        pass  # never let dump-writing mask the original error
    return path


def _append(log_file: Path | None, line: str) -> None:
    if log_file is None:
        print(line, file=sys.stderr)
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n")
    except Exception:
        pass


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def log_exception(exc: BaseException, component: str, context: dict | None = None,
                  log_file: Path | None = None) -> Path:
    """Log a structured error entry + write a crash dump. Returns the dump path."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    dump = {
        "component": component,
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid(),
        "uptime_seconds": round(time.time() - _PROC_START, 2),
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
        "context": context or {},
    }
    path = _write_dump(dump)
    _append(log_file, f"ERROR {type(exc).__name__}: {exc} (crashdump: {_rel(path)})")
    return path


def close_dump(component: str, reason: str, context: dict | None = None,
               log_file: Path | None = None) -> Path:
    """Write a close dump for a normal shutdown (SIGINT/SIGTERM). Returns the dump path."""
    dump = {
        "component": component,
        "timestamp": datetime.now().isoformat(),
        "pid": os.getpid(),
        "uptime_seconds": round(time.time() - _PROC_START, 2),
        "reason": reason,
        "context": context or {},
    }
    path = _write_dump(dump)
    _append(log_file, f"CLOSE {reason} (dump: {_rel(path)})")
    return path
