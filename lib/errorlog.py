

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

_PROC_START = time.time()


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
        pass
    return path


def _append(log_file: Path | None, line: str) -> None:
    if log_file is None:
        print(line, file=sys.stderr)
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
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
