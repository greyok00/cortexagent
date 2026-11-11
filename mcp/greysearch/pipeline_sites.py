"""pipeline_sites.py: Greysearch site tiers + task-slot registry.

SITES/EXCLUDED load from research/data/sites.json and
the task-slot registry (who owns which task-N browser lane) lives in this
repo's research/task-registry.json. Each process claims slots through live
port state; the registry file has a single writer. Lanes auto-scale:
the browser-ports slot map decides which task-N
lanes exist (task-1..task-13 and any later spawned lane), so the registry
accepts every task-N the map can hold, not a frozen task-1..task-4 range.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

SITES = json.loads(
    (_REPO_ROOT / "research" / "data" / "sites.json").read_text())
EXCLUDED = set(SITES.get("excluded", []))

# Same shape the binder's _TASK_RE allows (1 to 4 digits): a claim is valid
# for any lane the slot map can hold or spawn, not just task-1..task-4.
TASK_RE = re.compile(r"\b(?:task[-_ ]?)?([1-9][0-9]{0,3})\b")

def task_key(task_id) -> str:
    """Normalize task_id (1|"1"|"task-1"|"task_3") -> canonical "task-N"."""
    if task_id is not None and str(task_id).strip() != "":
        m = TASK_RE.search(str(task_id))
        if m:
            return f"task-{m.group(1)}"
    return ""

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

_TASK_REG_PATH = os.path.join(_REPO_ROOT, "research", "task-registry.json")

def _session_id() -> str:
    return (os.environ.get("GREYSEARCH_SESSION_ID")
            or "unknown-session")

def task_registry(assign: str | None = None, task_id=None,
                  forget: str | None = None) -> dict:
    """Read the whole registry, or (assign="task-N") register caller's session.
    Assigns only via EXPLICIT task_id in the same call; env alone never steals.
    Assign writes hold a cross-process flock on <registry>.write.lock (a file
    distinct from the mcp bind lock, so no same-file relock can deadlock) and
    land as a temp-file os.replace: two writers cannot lose each other's
    entries and a reader can never catch a half-written file (the old
    in-place json.dump could leave readers with an empty registry on a tear).
    forget="task-N" removes one slot entry under the same write lock:
    the binder's sweep for dead claimants uses it to drop claims whose
    owning pid is
    gone and whose port has no live browser, so a stale claim can never keep
    a free lane looking busy. Write failures raise (loud, never silent)."""
    import fcntl
    reg: dict = {}
    if forget and not assign:
        tk = task_key(forget)
        if not tk:
            raise ValueError(f"unknown task slot: {forget!r} "
                             "(name a lane like 'task-3')")
        os.makedirs(os.path.dirname(_TASK_REG_PATH), exist_ok=True)
        with open(_TASK_REG_PATH + ".write.lock", "a+") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                try:
                    with open(_TASK_REG_PATH) as f:
                        reg = json.load(f)
                except Exception:
                    reg = {}
                reg.pop(tk, None)
                tmp = _TASK_REG_PATH + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(reg, f, indent=1)
                os.replace(tmp, _TASK_REG_PATH)
                out_reg = dict(reg)
                out_reg["_last_assignment"] = {"slot": tk, "forgotten": True}
                return out_reg
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
    if not assign:
        try:
            with open(_TASK_REG_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    tk = task_key(assign)
    if not tk:
        raise ValueError(f"unknown task slot: {assign!r} "
                         "(name a lane like 'task-3')")
    os.makedirs(os.path.dirname(_TASK_REG_PATH), exist_ok=True)
    with open(_TASK_REG_PATH + ".write.lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            try:
                with open(_TASK_REG_PATH) as f:
                    reg = json.load(f)
            except Exception:
                reg = {}
            import socket
            prev_owner = (reg.get(tk) or {}).get("owner_session", "")
            sid = _session_id()
            reg[tk] = {"owner_session": sid,
                       "assigned_at": _now(),
                       "pid": os.getpid(), "host": socket.gethostname(),
                       "pages_dir": os.environ.get("RESEARCH_PAGES", "")}
            try:
                tmp = _TASK_REG_PATH + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(reg, f, indent=1)
                os.replace(tmp, _TASK_REG_PATH)
            except Exception:
                pass
            out_reg = dict(reg)
            out_reg["_last_assignment"] = {
                "slot": tk, "owner_session": sid,
                "reassigned_from": prev_owner,
                "note": ("slot was previously held by " + prev_owner
                         if prev_owner and prev_owner != sid
                         else "fresh claim"),
            }
            return out_reg
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)