#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                                 str(Path.home() / ".cortexagent")))
SOCKET_PATH = _STATE_DIR / "state" / "event_feed.sock"
MINIFY_STATS = _STATE_DIR / "minify_stats.json"
TOKEN_TRACKER = _STATE_DIR / "token_tracker.json"
ROUTING_STATE = _STATE_DIR / "routing_state.json"
SLIMTOKEN_STATS = Path.home() / ".local" / "state" / "slimtoken" / "stats.json"
BRIDGE_FILE = _STATE_DIR / "state" / "session_bridge.jsonl"
MEMORY_DIR = Path.home() / ".config" / "cortexllm" / "memory"

RING_SIZE = 200
POLL_INTERVAL = 1.0
BRIDGE_POLL = 0.5






COMPRESSION_SOURCES = (
    ("token_tracker", TOKEN_TRACKER),
    ("slimtoken-local", MINIFY_STATS),
    ("slimtoken", SLIMTOKEN_STATS),
)


COMPRESSION_LIVE_WINDOW_S = 600






LEGACY_ROUTE_WORDS = {
    "big": "local", "large": "local", "model": "local", "local": "local",
    "onprem": "local", "on-prem": "local",
    "small": "cloud", "little": "cloud", "tiny": "cloud", "cloud": "cloud",
    "remote": "cloud",
}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _read_json(path: Path, default=None):
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return default

def _cfg():

    try:
        from lib.config import CFG
        return CFG
    except Exception:
        return None

def _active_model_name() -> str:

    for var in ("CORTEXAGENT_ACTIVE_MODEL", "CLAUDE_MODEL_NAME",
                "CORTEXAGENT_MODEL_NAME"):
        val = os.environ.get(var)
        if val:
            return val
    cfg = _cfg()
    if cfg is not None:
        return str(getattr(cfg, "model_alias", "") or "")
    return ""

def route_for_model(model: str, base_url: str = "") -> str:

    text = f"{model or ''} {base_url or ''}".strip().lower()
    if ":cloud" in text or "11600" in text:
        return "cloud"
    return "local" if text else "unknown"

def normalize_route(word, model: str = "", base_url: str = "") -> str:

    w = str(word or "").strip().lower()
    if w in LEGACY_ROUTE_WORDS:
        return LEGACY_ROUTE_WORDS[w]
    return route_for_model(model or w, base_url)

def _newest_source(sources):

    best = None
    for name, path in sources:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best[2]:
            best = (name, path, mtime)
    return best

def _ledger_age_s(stats: dict, mtime: float) -> float:

    raw = stats.get("last_run_ts")
    ts = None
    if isinstance(raw, (int, float)) and raw > 0:
        ts = float(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip()).timestamp()
        except ValueError:
            ts = None
    if ts is None:
        return max(0.0, time.time() - mtime)
    return max(0.0, time.time() - ts)

_ALL_STAGES = ("dedup", "distill", "tools", "system", "messages")




_MODE_STAGES_FALLBACK = {
    "code": {"dedup", "distill"},
    "realtime": {"tools", "system", "messages", "dedup", "distill"},
}
DEFAULT_MODE = "code"


def _mode_stages() -> dict:

    try:
        from slimtoken.profiles import MODES
        table = {name: set(m.get("stages") or ()) for name, m in MODES.items()}
        if table:
            return table
    except Exception:
        pass
    return {k: set(v) for k, v in _MODE_STAGES_FALLBACK.items()}


def _compressor_profile(pid: str) -> dict:

    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
    except OSError:
        return {"mode": "", "stages": []}
    env = {}
    for item in raw.split("\x00"):
        if "=" in item:
            k, v = item.split("=", 1)
            env[k.strip()] = v.strip()

    table = _mode_stages()
    mode = env.get("SLIMTOKEN_MODE", DEFAULT_MODE).strip().lower() or DEFAULT_MODE
    if mode not in table:
        mode = DEFAULT_MODE
    in_mode = table.get(mode, set())

    def on(name: str, default: str) -> bool:
        return env.get(name, default).strip().lower() in ("1", "true", "yes", "on")

    if not on("SLIMTOKEN_MINIFY", "1"):
        return {"mode": mode, "stages": []}
    return {"mode": mode,
            "stages": [s for s in _ALL_STAGES
                       if on(f"SLIMTOKEN_MINIFY_{s.upper()}",
                             "1" if s in in_mode else "0")]}


def _compressor_state(lane: str) -> dict:

    instances = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = Path(f"/proc/{entry}/cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        parts = [p for p in raw.split("\x00") if p]
        if not parts or "slimtoken" not in " ".join(parts):
            continue
        inst = {"ports": [], "upstreams": []}
        for i, part in enumerate(parts):
            if part == "--port" and i + 1 < len(parts):
                inst["ports"].append(parts[i + 1])
            elif part == "--upstream" and i + 1 < len(parts):
                inst["upstreams"].append(parts[i + 1])
        inst.update(_compressor_profile(entry))
        instances.append(inst)

    ports = sorted({p for i in instances for p in i["ports"]})
    upstreams = sorted({u for i in instances for u in i["upstreams"]})

    def _port(url: str) -> str:
        try:
            return str(urlparse(url).port or "")
        except ValueError:
            return ""

    upstream_ports = sorted({p for p in (_port(u) for u in upstreams) if p})
    lane_port = _port(lane) if lane else ""

    fronting = None
    for inst in instances:
        if lane_port and (lane_port in inst["ports"]
                          or lane_port in {_port(u) for u in inst["upstreams"]}):
            fronting = inst
            break
    return {
        "running": bool(ports or upstreams),
        "ports": ports,
        "upstreams": upstreams,
        "upstream_ports": upstream_ports,



        "stages": fronting["stages"] if fronting else [],



        "mode": fronting.get("mode", "") if fronting else "",
        "lane": lane or None,
        "lane_port": lane_port or None,
        "in_path": fronting is not None,
    }

def _compression_snapshot() -> dict:

    compressor = _compressor_state(_routing_snapshot().get("base_url") or "")
    empty = {
        "runs": 0, "tokens_in": 0, "tokens_out": 0, "tokens_saved": 0,
        "ratio_pct": 0.0, "last_run_ts": None, "errors": 0,
        "source": None, "age_s": None, "live": False,
        "compressor": compressor,
    }
    picked = _newest_source(COMPRESSION_SOURCES)
    if picked is None:
        return empty
    name, path, mtime = picked
    s = _read_json(path, {}) or {}

    if "total" in s:
        s = s["total"]
    elif "proxy" in s:
        s = s["proxy"]
    age = _ledger_age_s(s, mtime)
    return {
        "runs": s.get("runs", 0),
        "tokens_in": s.get("tokens_in", 0),
        "tokens_out": s.get("tokens_out", 0),
        "tokens_saved": s.get("tokens_saved", 0),
        "ratio_pct": s.get("ratio_pct", 0.0),
        "last_run_ts": s.get("last_run_ts"),
        "errors": s.get("errors", 0),
        "source": name,
        "age_s": round(age, 1),
        "live": age < COMPRESSION_LIVE_WINDOW_S,
        "compressor": compressor,
    }

def _routing_snapshot() -> dict:

    recorded = _read_json(ROUTING_STATE, {}) or {}
    model = (_active_model_name() or str(recorded.get("model") or "")).strip()
    route = normalize_route(recorded.get("route"), model, "")
    cfg = _cfg()
    if route == "cloud":
        base_url = "http://127.0.0.1:11600"
    else:
        port = int(getattr(cfg, "local_port", 11599) or 11599) if cfg else 11599
        base_url = f"http://127.0.0.1:{port}"
    router_mode = str((getattr(cfg, "cortex_router_mode", "") if cfg else "")
                      or recorded.get("router_mode") or "auto")
    if cfg is not None:
        toolproxy = bool(getattr(cfg, "cortex_toolproxy", False))
    else:
        toolproxy = False
    return {
        "route": route,
        "model": model,
        "base_url": base_url,
        "router_mode": router_mode,
        "toolproxy_available": toolproxy,
        "recorded_at": recorded.get("updated_at"),
        "derived_from": "active-model",
    }

def _scheduling_snapshot() -> dict:
    try:
        from lib.scheduler.store import Store
        tasks = Store().list(visible_only=False)
    except Exception:
        tasks = []
    by_state = {}
    for t in tasks:
        st = t.get("state", "unknown")
        by_state[st] = by_state.get(st, 0) + 1
    return {
        "task_count": len(tasks),
        "by_state": by_state,
        "tasks": [
            {
                "id": t.get("id", "")[:8],
                "title": t.get("title", ""),
                "state": t.get("state", ""),
                "trigger": t.get("trigger", ""),
                "next_run_at": t.get("next_run_at"),
            }
            for t in tasks
        ],
    }

def _memory_snapshot() -> dict:
    counts = {}
    last_write = None
    for tier in ("hot", "warm", "cold"):
        d = MEMORY_DIR / tier
        try:
            files = [p for p in d.glob("*.jsonl") if p.is_file()]
            counts[tier] = len(files)
            for p in files:
                m = p.stat().st_mtime
                if last_write is None or m > last_write:
                    last_write = m
        except Exception:
            counts[tier] = 0
    return {
        "tiers": counts,
        "last_write_ts": last_write,
        "last_write_age_s": round(time.time() - last_write, 1) if last_write else None,
    }

def snapshot() -> dict:

    return {
        "compression": _compression_snapshot(),
        "routing": _routing_snapshot(),
        "scheduling": _scheduling_snapshot(),
        "memory": _memory_snapshot(),
        "timestamp": _now_iso(),
    }

class EventFeed:

    def __init__(self, socket_path: Path = SOCKET_PATH):
        self.socket_path = socket_path
        self._ring: list[dict] = []
        self._clients: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._shutdown = threading.Event()




        self._last_compression = None
        self._last_routing = None
        self._last_memory_write = None
        self._bridge_cursor = 0
        self._last_scheduling = None

    def _push(self, ev: dict) -> None:
        with self._lock:
            self._ring.append(ev)
            if len(self._ring) > RING_SIZE:
                self._ring = self._ring[-RING_SIZE:]
            for c in list(self._clients):
                try:
                    c.sendall((json.dumps(ev) + "\n").encode())
                except Exception:
                    self._clients.discard(c)

    def _emit(self, event_type: str, message: str, severity: str = "info",
              data: dict | None = None) -> None:
        self._push({
            "type": "event",
            "event_type": event_type,
            "message": message,
            "severity": severity,
            "timestamp": _now_iso(),
            "data": data or {},
        })

    def _serve(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.socket_path))
        srv.listen(8)
        srv.settimeout(0.5)
        while not self._shutdown.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(5)

            try:
                conn.sendall((json.dumps({"type": "snapshot", "data": snapshot()}) + "\n").encode())
                with self._lock:
                    for ev in self._ring:
                        conn.sendall((json.dumps(ev) + "\n").encode())
                    self._clients.add(conn)
            except Exception:
                conn.close()
        srv.close()
        try:
            self.socket_path.unlink()
        except Exception:
            pass

    def _watch_bridge(self) -> None:








        try:
            if BRIDGE_FILE.exists():
                with BRIDGE_FILE.open() as f:
                    self._bridge_cursor = sum(1 for _ in f)
        except OSError:
            self._bridge_cursor = 0

        while not self._shutdown.is_set():
            try:
                if BRIDGE_FILE.exists():
                    with BRIDGE_FILE.open() as f:
                        lines = f.read().splitlines()
                    for idx, line in enumerate(lines[self._bridge_cursor:],
                                               start=self._bridge_cursor):



                        self._bridge_cursor = idx + 1
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        etype = ev.get("type", "message")
                        content = ev.get("content", "")

                        if etype == "routing":


                            route = normalize_route(ev.get("route"), str(ev.get("model") or ""))
                            model = ev.get("model") or ""
                            mode = ev.get("router_mode") or ""
                            self._emit("routing",
                                       f"route={route} model={model} mode={mode}",
                                       "info", {"route": route, "model": model})
                        elif etype == "schedule_fired":
                            self._emit("scheduled_task", content, "info",
                                       {"name": ev.get("schedule_name")})
                        elif etype in ("task_done", "task_fail", "task_crash"):
                            sev = "high" if etype in ("task_fail", "task_crash") else "info"
                            self._emit("scheduled_task", content, sev)
                        elif etype == "message" and content.startswith("📅"):
                            self._emit("scheduled_task", content, "info")
                        elif etype == "message" and content.startswith("✅"):
                            self._emit("scheduled_task", content, "info")
                        elif etype == "message" and content.startswith("❌"):
                            self._emit("scheduled_task", content, "high")
            except Exception:
                pass
            self._shutdown.wait(BRIDGE_POLL)

    def _watch_state(self) -> None:

        while not self._shutdown.is_set():



            m = _compression_snapshot()
            runs = m.get("runs", 0)
            comp = m.get("compressor") or {}
            ckey = (runs, comp.get("running"), comp.get("in_path"),
                    tuple(comp.get("ports") or ()))
            if ckey != self._last_compression:
                if self._last_compression is not None:
                    prev_runs = self._last_compression[0]
                    if runs > prev_runs:
                        msg = (f"compressed {m.get('tokens_in',0)}→"
                               f"{m.get('tokens_out',0)} tok ({m.get('ratio_pct',0)}% saved)")
                    elif not comp.get("in_path"):
                        msg = ("no compression: the agent's lane "
                               f"({comp.get('lane')}) is not fronted by the compressor")
                    elif comp.get("running"):
                        msg = "no compression traffic: compressor up, nothing routed through it"
                    else:
                        msg = "no compression: compressor not running"
                    self._emit("compression", msg, "info", m)
                self._last_compression = ckey

            r = _routing_snapshot()
            rkey = (r.get("route"), r.get("model"), r.get("router_mode"))
            if rkey != self._last_routing:
                if self._last_routing is not None:
                    self._emit("routing",
                               f"route={r.get('route')} model={r.get('model')} "
                               f"mode={r.get('router_mode')}",
                               "info", {"route": r.get("route"), "model": r.get("model")})
                self._last_routing = rkey


            ss = _scheduling_snapshot()
            if ss is not None:
                sskey = (ss.get("task_count", 0), tuple(sorted(ss.get("by_state", {}).items())))
                if sskey != self._last_scheduling:
                    if self._last_scheduling is not None:
                        self._emit("scheduling",
                                   f"tasks: {ss.get('task_count', 0)} total, "
                                   f"{ss.get('by_state', {})}",
                                   "info", ss)
                    self._last_scheduling = sskey

            mem = _memory_snapshot()
            mw = mem.get("last_write_ts")
            if mw != self._last_memory_write:
                if self._last_memory_write is not None:
                    self._emit("memory", "memory updated", "info", mem)
                self._last_memory_write = mw
            self._shutdown.wait(POLL_INTERVAL)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self._serve, daemon=True),
            threading.Thread(target=self._watch_bridge, daemon=True),
            threading.Thread(target=self._watch_state, daemon=True),
        ]
        for t in threads:
            t.start()
        try:
            while not self._shutdown.is_set():
                self._shutdown.wait(1)
        except KeyboardInterrupt:
            pass
        self._shutdown.set()
        for t in threads:
            t.join(timeout=2)

def _smoke() -> int:
    fails = 0

    def check(label, cond):
        nonlocal fails
        if not cond:
            print(f"❌ {label}")
            fails += 1
        else:
            print(f"✅ {label}")

    s = snapshot()
    check("snapshot has compression", "compression" in s)
    check("snapshot has routing", "routing" in s)
    check("snapshot has scheduling", "scheduling" in s)
    check("snapshot has memory", "memory" in s)
    check("compression.runs is int", isinstance(s["compression"]["runs"], int))
    check("scheduling.task_count >= 0", s["scheduling"]["task_count"] >= 0)
    print("✅ event_feed smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0

def main() -> int:
    if "--smoke" in sys.argv:
        return _smoke()
    if "--once" in sys.argv:
        print(json.dumps(snapshot(), indent=2))
        return 0
    feed = EventFeed()
    print(f"🐺 event_feed listening on {SOCKET_PATH}", file=sys.stderr)
    feed.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())
