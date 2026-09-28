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

# Three writers have produced compression numbers. Only the newest one is worth
# reporting, and its age has to travel with the numbers: slimtoken was stopped
# on purpose 2026-09-27 00:11, so whichever file it left behind is frozen at the
# moment it stopped. Reporting that figure without its age is what made the
# panel read as "putting in hard numbers" (owner report 2026-09-27).
COMPRESSION_SOURCES = (
    ("token_tracker", TOKEN_TRACKER),
    ("slimtoken-local", MINIFY_STATS),
    ("slimtoken", SLIMTOKEN_STATS),
)

# Older than this and the compression numbers describe a run that has ended.
COMPRESSION_LIVE_WINDOW_S = 600

# The only route vocabulary cortexagent speaks is local/cloud. The retired
# entry names in this table come from the old two-model size scheme; each is
# mapped to the lane it stood for and translated on read, so an old record or a
# replayed bridge line cannot put those words back into the feed (owner request
# 2026-09-27: route words are local/cloud only).
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
    """The live configuration object, or None when it cannot be imported."""
    try:
        from lib.config import CFG
        return CFG
    except Exception:
        return None

def _active_model_name() -> str:
    """The model the agent is actually running, as the launcher names it."""
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
    """Map a model or endpoint onto the two route names: local or cloud.

    A name carrying ``:cloud`` (or pointing at the ollama cloud port 11600) is
    the cloud lane; anything else served from this machine is the local lane.
    """
    text = f"{model or ''} {base_url or ''}".strip().lower()
    if ":cloud" in text or "11600" in text:
        return "cloud"
    return "local" if text else "unknown"

def normalize_route(word, model: str = "", base_url: str = "") -> str:
    """Translate a recorded route word into local/cloud.

    A recorded word is honoured first (the retired vocabulary is translated by
    LEGACY_ROUTE_WORDS), and only then is the live model consulted, so a route
    that was genuinely chosen still reads as chosen.
    """
    w = str(word or "").strip().lower()
    if w in LEGACY_ROUTE_WORDS:
        return LEGACY_ROUTE_WORDS[w]
    return route_for_model(model or w, base_url)

def _newest_source(sources):
    """The most recently written of `sources` as (name, path, mtime)."""
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
    """How long ago the numbers were written — the ledger's own word first.

    `last_run_ts` is when the writer last ran. A file's mtime is not: these
    ledgers get rewritten without a new compression (token_tracker.json's total
    is republished on every restart), so a fresh mtime next to a five-day-old
    total is exactly the shape that makes a frozen figure look live — it made
    this snapshot report 37 minutes for a writer that stopped 2026-09-22.
    Epoch seconds are what token_tracker writes, ISO strings what slimtoken
    writes, so both are accepted. mtime remains the fallback when the ledger
    carries no timestamp at all.
    """
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

def _compressor_stages(pid: str) -> list:
    """Which rewriting stages this slimtoken process is actually running with.

    Read from the process's own environment, not from a unit file: the unit is
    one of several places a stage can be switched and the process is what is
    serving. `SLIMTOKEN_MINIFY=0` — or every MINIFY_* flag off — means the proxy
    forwards request bodies untouched (proxy._is_fast_path), so a lane can be
    fronted by slimtoken and still have nothing compressed on it.
    """
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
    except OSError:
        return []
    env = {}
    for item in raw.split("\x00"):
        if "=" in item:
            k, v = item.split("=", 1)
            env[k.strip()] = v.strip()

    def on(name: str, default: str = "1") -> bool:
        return env.get(name, default).strip().lower() in ("1", "true", "yes", "on")

    if not on("SLIMTOKEN_MINIFY"):
        return []
    return [s for s in ("dedup", "distill", "tools", "system", "messages")
            if on(f"SLIMTOKEN_MINIFY_{s.upper()}")]


def _compressor_state(lane: str) -> dict:
    """Is a compressor actually in the path the agent's traffic takes?

    The panels used to answer "is compression working?" from a runs counter, and
    a counter only moves when a request passes through a compressor. That is not
    the same question: the counter is frozen if the compressor is gone, idle, or
    — the live case on 2026-09-27 — if the agent talks to a lane nothing fronts
    (traffic goes to llama-server :11599 while slimtoken fronts ollama :11600).
    So probe the compressor itself, live, and report which of those it is.

    A lane is fronted when a running slimtoken listens ON the lane's port, or
    when it forwards TO the lane's port — the second case is the lane proxy
    added 2026-09-27 (slimtoken-lane.service :11598 -> llama-server :11599),
    where the agent's own base_url is the proxy and the lane port is only ever
    an upstream. Reading the listen ports alone called that "bypasses
    slimtoken" while the proxy was serving the agent's traffic.
    """
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
        inst["stages"] = _compressor_stages(entry)
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
        # Only the instance that fronts the lane answers for the lane: the two
        # ollama fronts run with stages on and would otherwise report rewriting
        # that never touches the agent's traffic.
        "stages": fronting["stages"] if fronting else [],
        "lane": lane or None,
        "lane_port": lane_port or None,
        "in_path": fronting is not None,
    }

def _compression_snapshot() -> dict:
    """Compression numbers plus the age, origin, and live state of the numbers.

    `age_s` is how long ago the compressor last ran (see `_ledger_age_s`). When
    it is large the numbers are a record of a compressor that is no longer
    running, not live traffic — consumers must say so rather than render them as
    current. `compressor` says whether one is running at all and whether it is
    even in the agent's request path, so a frozen counter can be explained
    instead of just dated.
    """
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
    # token_tracker.json has a "total" key wrapping the stats
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
    """The live route, in local/cloud terms.

    Nothing in this tree writes routing_state.json — its writer, the grammar
    proxy, was deleted 2026-09-22 — so the route is derived from the model the
    agent is running instead of being replayed from a frozen file. The recorded
    state is consulted only for what it still truthfully describes (which mode
    was selected, and when it was recorded).
    """
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

        # Compression changes on a runs increase OR on the compressor's own state
        # (started, stopped, in/out of the agent's path) — a counter frozen five
        # days ago with a compressor that just died is a change consumers need.
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

        # Start at the END of the bridge. The bridge is an append-only log of
        # every session message since 2026-08-19, so replaying it from line 0
        # delivered weeks of stale events to each new client as if they were
        # current — 815 of those lines carry the retired size-scheme route name,
        # why the feed kept announcing it (owner report 2026-09-27: "cortexagent
        # is calling routing=big"). Only lines appended after this process starts
        # are events.
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
                        # Advance past every line examined, parsed or not, so a
                        # malformed line cannot make the cursor drift and replay
                        # its neighbours.
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
                            # Rebuild from fields, translated to local/cloud —
                            # the recorded `content` still carries the old word.
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

            # Watch the same source the snapshot reports, so a change in which
            # file is newest cannot leave the two disagreeing.
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

            # Also watch scheduling (tasks)
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
