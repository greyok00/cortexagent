#!/usr/bin/env python3
"""Task-scoped browser port resolver - Greysearch fork slots.

Greysearch task slots, numbers only: task-1 -> 9351, task-2 -> 9352,
task-3 -> 9353, task-4 -> 9354 (the greysearch instances in cortexagent keep
9331-9334; the two families are fully port-isolated). One browser per task,
own port/profile.
This module is the single resolution point every fetch script must use:
no script hardcodes a port, resolves a window, or sweeps by pattern.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

TREE_MAP_PATH = str(Path(__file__).resolve().parent / "research"
                    / "browser-ports.json")
# Dynamic lanes live in ONE home-dir map shared by every greysearch tree
# (portal, core twin): two trees spawning lanes in private copies would
# allocate the same (task-N, port) pairs against each other.
SHARED_MAP_PATH = os.path.join(os.path.expanduser("~/.cache/greysearch"),
                               "browser-ports.json")
CANDIDATE_MAPS = (TREE_MAP_PATH, SHARED_MAP_PATH)
def _find_chrome() -> str:
    """Portable chromium discovery: patchright cache (newest first), then
    system installs. patchright_headless.py owns the full launch ladder; this
    constant is informational/fallback and never load-bearing."""
    import glob
    cands = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")), reverse=True)
    cands += ["/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/usr/bin/google-chrome-stable"]
    return next((c for c in cands if os.path.exists(c)), "/usr/bin/chromium")

CHROME_BIN = _find_chrome()

def load_map() -> Dict[str, Any]:
    """Merged slot map: each tree map first (its fixed slots win on key
    collisions), then the shared dynamic map. Unreadable or task-less
    files are skipped; raising only when no task map exists anywhere."""
    merged: Dict[str, Any] = {}
    tasks: Dict[str, Any] = {}
    found = False
    for p in CANDIDATE_MAPS:
        try:
            with open(p) as f:
                m = json.load(f)
        except Exception:
            continue
        if not isinstance(m, dict) or not isinstance(m.get("tasks"), dict):
            continue
        found = True
        if not merged:
            merged = m
        for k, v in m["tasks"].items():
            tasks.setdefault(k, v)
    if not found:
        raise RuntimeError("browser-ports.json not found in any known location")
    merged["tasks"] = tasks
    return merged

def slot_ids(m: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every task-N slot in the (merged) map, sorted numerically: task-2
    sorts before task-10. The map is the only source: no caller hardcodes
    a slot range any more."""
    m = m if m is not None else load_map()
    seen: Dict[int, str] = {}
    for key in (m.get("tasks") or {}):
        mt = re.match(r"^(?:task-)?(\d+)$", str(key))
        if mt and int(mt.group(1)) > 0:
            seen[int(mt.group(1))] = f"task-{mt.group(1)}"
    return [seen[n] for n in sorted(seen)]

def max_slot_num(m: Optional[Dict[str, Any]] = None) -> int:
    m = m if m is not None else load_map()
    return max((int(k.split("-")[1]) for k in slot_ids(m)), default=0)

DYN_PORT_MIN = 9351          # first port a dynamic lane may ever take
DYN_PORT_PROBE_LIMIT = 400   # honest exhaustion, never an endless scan

def port_in_use(port: int) -> bool:
    """True when ANY listener (ours or foreign) holds the TCP port. A
    strict bind probe: a port someone just vacated can still read busy on
    a leftover socket, so a fresh lane never launches onto a risky port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", int(port)))
            return False
        except OSError:
            return True

def next_free_port(start: int) -> int:
    """First port at/after start that no listener holds."""
    n = int(start)
    for _ in range(DYN_PORT_PROBE_LIMIT):
        if not port_in_use(n):
            return n
        n += 1
    raise RuntimeError("no free TCP port for a new browser lane "
                       f"(probed {DYN_PORT_PROBE_LIMIT} ports from {start})")

def bind_new_slot(num: Optional[int] = None) -> Dict[str, Any]:
    """Create a brand-new lane under the shared map lock: task-<num>
    (default one past the highest known slot number) on the first TCP
    port at/after one past the highest known port that no listener holds.
    Atomic (tmp + os.replace) and idempotent: a lane registered by a
    racing process is returned as-is. The port probe happens INSIDE the
    lock so concurrent spawners can never pick the same port."""
    import fcntl
    os.makedirs(os.path.dirname(SHARED_MAP_PATH), exist_ok=True)
    lock = SHARED_MAP_PATH + ".lock"
    with open(lock, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            m: Dict[str, Any] = {}
            if os.path.exists(SHARED_MAP_PATH):
                try:
                    with open(SHARED_MAP_PATH) as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict) and \
                            isinstance(loaded.get("tasks"), dict):
                        m = loaded
                except Exception:
                    m = {}
            if not m:
                m = {"version": "greysearch-dynamic-r1",
                     "slot_rule": "Dynamic Greysearch lanes spawned at "
                     "runtime by the auto-scaling slot binder: one browser "
                     "per task, own port, own profile. Fixed slots stay in "
                     "each tree's browser-ports.json; every consumer merges "
                     "both maps.",
                     "tasks": {}}
            tasks = m["tasks"]
            known: set = set()
            floor = DYN_PORT_MIN
            for p in CANDIDATE_MAPS:
                try:
                    with open(p) as f:
                        mm = json.load(f)
                except Exception:
                    continue
                if not isinstance(mm, dict):
                    continue
                for k, v in (mm.get("tasks") or {}).items():
                    mt = re.match(r"^task-(\d+)$", str(k))
                    if not mt:
                        continue
                    n2 = int(mt.group(1))
                    known.add(n2)
                    port2 = (v or {}).get("port")
                    if isinstance(port2, int):
                        floor = max(floor, port2 + 1)
            if num is None:
                num = (max(known) if known else 0) + 1
            else:
                num = int(num)
            key = f"task-{num}"
            if isinstance(tasks.get(key), dict) and \
                    tasks[key].get("port"):
                entry = dict(tasks[key])
                entry["key"] = key
                return entry
            port = next_free_port(floor)
            entry = {"port": int(port),
                     "aliases": [key, str(int(num))],
                     "profile": os.path.join(
                         "~/.cache/greysearch", f"task-{int(num)}-profile"),
                     "key": key}
            tasks[key] = {
                "port": int(port),
                "aliases": [key, str(int(num))],
                "profile": entry["profile"],
            }
            _shared_map_write(m, SHARED_MAP_PATH)
            return entry
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)

def _shared_map_write(m: Dict[str, Any], path: str) -> None:
    tmp = path + f".tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")

def resolve(task: str = "", pages_env: str = "") -> Dict[str, Any]:
    """Resolve task -> {key, port, profile, displays}.

    Priority is STRICT and ordered: an explicit `task` argument always wins
    before the RESEARCH_TASK env is ever consulted. (Mixing them into one
    haystack let whichever map key matched first win: passing task-3 with a
    stale env task-1 returned task-1's port, a real port-conflict generator.)
    Accepts: explicit task ("task-3", "2", "greysearch"), the RESEARCH_TASK
    env, or the RESEARCH_PAGES env value (dir path) the caller writes into.
    Raises instead of guessing a port."""
    m = load_map()

    def _match(name_value: str):
        n = _norm(name_value)
        if not n:
            return None
        for key, cfg in m.get("tasks", {}).items():
            for alias in [key] + cfg.get("aliases", []):
                if n == _norm(alias):
                    cfg2 = dict(cfg)
                    if "profile" in cfg2:
                        cfg2["profile"] = os.path.expanduser(str(cfg2["profile"]))
                    cfg2["key"], cfg2["name"] = key, alias
                    return cfg2
        if pages_env and name_value == pages_env:
            return None
        for key, cfg in m.get("tasks", {}).items():
            for alias in [key] + cfg.get("aliases", []):
                a = _norm(alias)
                if a and a in n:
                    cfg2 = dict(cfg)
                    cfg2["key"], cfg2["name"] = key, alias
                    return cfg2
        return None

    for stage in (
        {"task": task, "ok_if": bool(task)},
        {"task": os.environ.get("RESEARCH_TASK", ""), "ok_if": True},
        {"task": pages_env, "ok_if": bool(pages_env)},
    ):
        if not stage["ok_if"]:
            continue
        cfg2 = _match(stage["task"])
        if cfg2:
            return cfg2
    raise RuntimeError(
        "no task identified for this fetch: set RESEARCH_TASK "
        "(any task-N lane in the slot map) "
        "or pass the task's pages dir; refusing to guess a port")

def task_cfg(task: str = "", pages_env: str = "") -> Dict[str, Any]:
    return resolve(task=task, pages_env=pages_env)

ORPHAN_MIN_AGE_S = 2.0

def _ps_snapshot() -> List[Dict[str, Any]]:
    """Process table via ps. Isolated so tests can monkeypatch it."""
    r = subprocess.run(["ps", "-eo", "pid=,comm=,etimes=,args="],
                       capture_output=True, text=True, timeout=10)
    procs: List[Dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        try:
            etimes = float(parts[2])
        except (ValueError, IndexError):
            etimes = None
        procs.append({"pid": pid, "comm": parts[1],
                      "etimes": etimes,
                      "args": parts[3] if len(parts) > 3 else ""})
    return procs

def _xvfb_pids(n: int, snapshot: Sequence[Dict[str, Any]]) -> List[int]:
    """PIDs whose command is Xvfb, whose cmdline names display :n, and that
    are old enough to be a leaked server (not a just-spawned one)."""
    pat = re.compile(rf"(?:^|\s):{int(n)}(?:\s|$)")
    pids: List[int] = []
    for proc in snapshot or []:
        if os.path.basename(str(proc.get("comm") or "")) != "Xvfb":
            continue
        age = proc.get("etimes")
        if age is not None:
            try:
                if float(age) < ORPHAN_MIN_AGE_S:
                    continue
            except (TypeError, ValueError):
                pass
        if pat.search(str(proc.get("args") or "")):
            pids.append(int(proc["pid"]))
    return pids

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

def inspect_display(n: int,
                    *,
                    ps_snapshot: Optional[List[Dict[str, Any]]] = None,
                    socket_path: Optional[str] = None,
                    lock_path: Optional[str] = None) -> Dict[str, Any]:
    """State of one candidate display: Xvfb PIDs, socket, lock, orphan flag."""
    display = int(n)
    sock = (socket_path if socket_path is not None
            else f"/tmp/.X11-unix/X{display}")
    lock = (lock_path if lock_path is not None else f"/tmp/.X{display}-lock")
    snap = ps_snapshot if ps_snapshot is not None else _ps_snapshot()
    pids = _xvfb_pids(display, snap)
    has_socket = os.path.exists(sock)
    has_lock = os.path.exists(lock)
    return {"display": display, "pids": pids,
            "socket": has_socket, "lock": has_lock,
            "socket_path": sock, "lock_path": lock,
            "orphan": bool(pids) and not (has_socket or has_lock)}

def reap_orphan_display(
        n: int,
        *,
        ps_snapshot: Optional[List[Dict[str, Any]]] = None,
        socket_path: Optional[str] = None,
        lock_path: Optional[str] = None,
        kill: Optional[Callable[[int, int], Any]] = None,
        alive: Optional[Callable[[int], bool]] = None,
        wait_s: float = 1.5) -> Dict[str, Any]:
    """Terminate an orphan Xvfb on display :n and report what was reclaimed.

    An orphan is an Xvfb process on :n with NEITHER an X11 socket nor a lock
    file. Anything with a live socket/lock belongs to another session and is
    skipped; :0 is never touched. Returns a metadata dict that callers record.
    """
    display = int(n)
    info = inspect_display(display, ps_snapshot=ps_snapshot,
                           socket_path=socket_path, lock_path=lock_path)
    result: Dict[str, Any] = {**info, "reclaimed": False, "killed": []}
    if display == 0:
        result["reason"] = "display :0 is never touched"
        return result
    if info["socket"] or info["lock"]:
        result["reason"] = "live socket/lock present, not an orphan"
        return result
    if not info["pids"]:
        result["reason"] = "no Xvfb process on this display"
        return result
    _kill = kill or os.kill
    _alive = alive or _pid_alive
    killed: List[int] = []
    for pid in info["pids"]:
        try:
            _kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception as exc:
            result.setdefault("errors", []).append(f"pid {pid}: {exc}")
    deadline = time.time() + max(0.0, wait_s)
    while killed and time.time() < deadline:
        if not any(_alive(pid) for pid in killed):
            break
        time.sleep(0.1)
    for pid in killed:
        if _alive(pid):
            try:
                _kill(pid, signal.SIGKILL)
            except Exception:
                pass
    result["killed"] = killed
    result["reclaimed"] = bool(killed)
    result["reason"] = ("orphan Xvfb reclaimed (no socket/lock)" if killed
                        else "orphan Xvfb found but termination failed")
    return result

def _note(path: str, msg: str) -> None:
    if not path:
        return
    try:
        import datetime
        with open(path, "a") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                    f"{msg}\n")
    except Exception:
        pass

def cdp_http(cfg: Dict[str, Any]) -> str:
    return f"http://127.0.0.1:{cfg['port']}"

def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3):
            return True
    except Exception:
        return False

def launch_cmd(cfg: Dict[str, Any]) -> List[str]:
    """setsid-detached launch: THE slot browser = patchright-launched STEALTH
    Chromium, headless by default, persistent per-slot profile, CDP on the
    slot port. Xvfb/display plumbing is obsolete for this launcher: the
    headless browser needs no display (a --headful opt-in exists inside
    patchright_headless.py for sites that hard-fail headless)."""
    here = Path(__file__).resolve().parent
    script = here / "patchright_headless.py"
    if script.exists():
        target = [str(script)]
    else:
        code = (f"import sys; sys.path.insert(0, {str(here)!r}); "
                "import patchright_headless as m; sys.exit(m.main())")
        target = ["-c", code]
    return [
        "setsid", "nohup", sys.executable or "python3", *target,
        "--port", str(cfg["port"]),
        "--profile", str(cfg["profile"]),
    ]

def ensure(cfg: Dict[str, Any], wait_s: int = 40, note: str = "") -> bool:
    """If this task's browser is down, launch it detached: ONE patchright
    HEADLESS Chromium per slot on its own CDP port/profile. No X display is
    involved: headless needs none. Never touches a browser on another task's
    port/profile. Returns True when up. The detached launch forwards the
    session's own GREYSEARCH_* env vars (the captcha solver knob resolves in
    the launching process too, not only in fetches)."""
    port = int(cfg["port"])
    if _healthy(port):
        return True
    env = {
        "HOME": os.environ.get("HOME") or str(Path.home()),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        **{k: str(v) for k, v in os.environ.items()
           if k.startswith("GREYSEARCH_")},
    }
    try:
        subprocess.Popen(launch_cmd(cfg), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        return False
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _healthy(port):
            if note:
                try:
                    with open(note, "a") as f:
                        import datetime
                        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                                f"auto-launched task browser port={port} "
                                f"profile={cfg['profile']} (headless, no display)\n")
                except Exception:
                    pass
            return True
        time.sleep(1)
    return False

class TaskLock:
    """Intra-task flock: two fetch lanes of the SAME task must never drive
    the same tab at once. Cross-task ports are separate; this only
    serialises lanes within one task. Non-blocking acquire; wait or skip."""

    def __init__(self, cfg: Dict[str, Any]):
        base = os.path.expanduser("~/.cache/greysearch")
        self.path = os.path.join(base, "locks", f"{cfg['key']}.lock")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fh = None

    def acquire(self, wait_s: float = 90.0) -> bool:
        import fcntl
        self.fh = open(self.path, "w")
        end = time.time() + wait_s
        while time.time() < end:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                time.sleep(2)
        self.fh.close()
        self.fh = None
        return False

    def release(self):
        import fcntl
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass
            self.fh = None