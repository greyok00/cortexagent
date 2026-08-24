#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _emit(obj: Any, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return code


def _schedule() -> List[dict]:
    from lib.overseer import schedule_list
    return schedule_list()


def _queue() -> List[dict]:
    from lib.overseer import queue_list
    return queue_list()


def _plan() -> dict:
    from lib.overseer import plan_status
    return plan_status()


def _smoke() -> int:
    fails = 0
    try:
        s = _schedule()
        print(f"✅ schedule OK ({len(s)} tasks)")
    except Exception as e:
        print(f"❌ schedule: {e}")
        fails += 1
    try:
        q = _queue()
        print(f"✅ queue OK ({len(q)} entries)")
    except Exception as e:
        print(f"❌ queue: {e}")
        fails += 1
    try:
        p = _plan()
        print(f"✅ plan OK ({p.get('name', 'none')})")
    except Exception as e:
        print(f"❌ plan: {e}")
        fails += 1
    print("schedule_bridge smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] == "--smoke":
        return _smoke()
    cmd = argv[0]
    try:
        if cmd == "list":
            return _emit({"ok": True, "schedule": _schedule()})
        if cmd == "queue":
            return _emit({"ok": True, "queue": _queue()})
        if cmd == "plan":
            return _emit({"ok": True, "plan": _plan()})
        return _emit({"ok": False, "error": f"unknown command: {cmd}"}, 1)
    except Exception as e:
        return _emit({"ok": False, "error": str(e)}, 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
