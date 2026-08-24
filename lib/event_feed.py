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


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_STATE_DIR = Path(os.environ.get("CORTEXAGENT_STATE_DIR",
                                 str(Path.home() / ".cortexagent")))
SOCKET_PATH = _STATE_DIR / "state" / "event_feed.sock"
MINIFY_STATS = _STATE_DIR / "minify_stats.json"
ROUTING_STATE = _STATE_DIR / "routing_state.json"
BRIDGE_FILE = _STATE_DIR / "state" / "webui_session.jsonl"
MEMORY_DIR = Path.home() / ".config" / "cortexllm" / "memory"

RING_SIZE = 200
POLL_INTERVAL = 1.0
BRIDGE_POLL = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default=None):
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return default






def _compression_snapshot() -> dict:
    s = _read_json(MINIFY_STATS, {}) or {}
    return {
        "runs": s.get("runs", 0),
        "tokens_in": s.get("tokens_in", 0),
        "tokens_out": s.get("tokens_out", 0),
        "tokens_saved": s.get("tokens_saved", 0),
        "ratio_pct": s.get("ratio_pct", 0.0),
        "last_run_ts": s.get("last_run_ts"),
        "errors": s.get("errors", 0),
    }


def _routing_snapshot() -> dict:
    s = _read_json(ROUTING_STATE, {}) or {}
    return {
        "route": s.get("route", "unknown"),
        "model": s.get("model", ""),
        "base_url": s.get("base_url", ""),
        "router_mode": s.get("router_mode", ""),
        "toolproxy_available": s.get("toolproxy_available", False),
        "updated_at": s.get("updated_at"),
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

        self._last_minify = None
        self._last_routing = None
        self._last_memory_write = None
        self._bridge_cursor = 0


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

        while not self._shutdown.is_set():
            try:
                if BRIDGE_FILE.exists():
                    with BRIDGE_FILE.open() as f:
                        lines = f.read().splitlines()
                    for line in lines[self._bridge_cursor:]:
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        self._bridge_cursor += 1
                        etype = ev.get("type", "message")
                        content = ev.get("content", "")

                        if etype == "routing":
                            self._emit("routing", content, "info", {"route": ev.get("route")})
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

            m = _read_json(MINIFY_STATS, {}) or {}
            runs = m.get("runs", 0)
            if runs != self._last_minify:
                if self._last_minify is not None and runs > self._last_minify:
                    self._emit("compression",
                               f"compressed {m.get('tokens_in',0)}→{m.get('tokens_out',0)} "
                               f"tok ({m.get('ratio_pct',0)}% saved)",
                               "info", {"runs": runs, "ratio_pct": m.get("ratio_pct")})
                self._last_minify = runs

            r = _read_json(ROUTING_STATE, {}) or {}
            rkey = (r.get("route"), r.get("model"), r.get("router_mode"))
            if rkey != self._last_routing:
                if self._last_routing is not None:
                    self._emit("routing",
                               f"route={r.get('route')} model={r.get('model')} "
                               f"mode={r.get('router_mode')}",
                               "info", {"route": r.get("route"), "model": r.get("model")})
                self._last_routing = rkey

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
