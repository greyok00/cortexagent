"""lib/overseer_dashboard/telemetry.py — read live state into typed models.

Reads the same backing data as the old tray popout (overseer state, daemon
control socket, proxy /metrics, minify stats, plan, queue, schedule) but
normalizes it into the typed ``RuntimeSnapshot`` model. This module is the
only place that touches raw JSON; the UI consumes models only.

Model-name resolution follows the spec's priority order:
  1. response.model
  2. response.model_id
  3. response.metadata.model
  4. request.model
  5. active backend runtime model identifier
  6. configured route/profile alias (explicit fallback only)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import models as M

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

STATE_DIR = Path(os.environ.get(
    "CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent")))
PROXY_PORT = os.environ.get("CORTEXAGENT_PROXY_PORT", "8081")
PROXY_METRICS = f"http://127.0.0.1:{PROXY_PORT}/metrics"

# How old a snapshot may be before we call it stale.
STALE_AFTER_S = 5.0


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        with path.open() as f:
            d = json.load(f)
        return d if d else default
    except Exception:
        return default


def _daemon_status() -> Dict[str, Any]:
    try:
        from lib import control
        return control.send_request("status", timeout=2) or {}
    except Exception:
        return {}


def _proxy_metrics() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(PROXY_METRICS, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {}


# ── Model-name resolution ───────────────────────────────────────────────────
def _first(*candidates: Any) -> str:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return ""


def _resolve_model(daemon: Dict[str, Any], proxy: Dict[str, Any],
                   active_model: Dict[str, Any]) -> M.ModelIdentity:
    """Resolve the concrete serving model per the spec's priority order."""
    big = daemon.get("big") if isinstance(daemon.get("big"), dict) else {}
    # 1-3. response.* fields (proxy may carry a last-response model).
    resp = proxy.get("response") if isinstance(proxy.get("response"), dict) else {}
    resp_model = _first(
        resp.get("model"), resp.get("model_id"),
        (resp.get("metadata") or {}).get("model") if isinstance(resp.get("metadata"), dict) else None,
    )
    # 4. request.model
    req_model = _first(proxy.get("request_model"))
    # 5. active backend runtime model identifier (daemon big.model basename).
    backend_model = ""
    path = _first(big.get("model"), big.get("model_path"))
    if path and "/" in path:
        backend_model = path.rsplit("/", 1)[-1]
    elif path:
        backend_model = path
    # 6. route/profile alias (explicit fallback).
    alias = _first(big.get("alias"), big.get("name"))

    model = _first(resp_model, req_model, backend_model, alias)
    source = "response" if resp_model else (
        "request" if req_model else (
            "backend" if backend_model else "alias"))
    if not model:
        model = "unknown"
        source = "none"

    # Backend/provider.
    backend = _first(proxy.get("backend"), big.get("backend"), "unknown")
    route = _first(big.get("alias"), "cortex-big")

    return M.ModelIdentity(model=model, route=route, backend=backend, source=source)


# ── Inference telemetry ─────────────────────────────────────────────────────
def _build_inference(daemon: Dict[str, Any], proxy: Dict[str, Any],
                     big: Dict[str, Any]) -> M.InferenceTelemetry:
    ctx = int(big.get("ctx", 0) or 0) or None
    # Context used: prefer a real value; else None (never fabricate).
    context_used = None
    for key in ("context_used", "ctx_used", "prompt_tokens"):
        v = proxy.get(key)
        if isinstance(v, (int, float)) and v:
            context_used = int(v)
            break

    in_tps = proxy.get("current_in_tps")
    out_tps = proxy.get("current_out_tps")
    if in_tps is None:
        in_tps = proxy.get("current_tok_s")  # legacy single-rate
    in_tps = float(in_tps) if isinstance(in_tps, (int, float)) else None
    out_tps = float(out_tps) if isinstance(out_tps, (int, float)) else None

    vram_used = proxy.get("vram_used_mib")
    vram_total = proxy.get("vram_total_mib")

    # Cache/reuse only when genuinely present.
    cache_pct = proxy.get("cache_pct")
    cache_pct = float(cache_pct) if isinstance(cache_pct, (int, float)) else None
    reused_pct = proxy.get("reused_pct")
    reused_pct = float(reused_pct) if isinstance(reused_pct, (int, float)) else None

    last_req = daemon.get("last_request")
    last_status = None
    if isinstance(last_req, dict):
        last_status = last_req.get("status")

    active = bool(in_tps or out_tps or context_used)

    return M.InferenceTelemetry(
        context_used=context_used,
        context_window=ctx,
        input_tps=in_tps,
        output_tps=out_tps,
        input_tokens=context_used,
        output_tokens=int(proxy.get("completion_tokens", 0) or 0) or None,
        cache_pct=cache_pct,
        reused_pct=reused_pct,
        vram_used_mib=int(vram_used) if isinstance(vram_used, (int, float)) else None,
        vram_total_mib=int(vram_total) if isinstance(vram_total, (int, float)) else None,
        queue_depth=int(daemon.get("queue_depth", 0) or 0) or None,
        active_request=daemon.get("active_request"),
        last_request_status=last_status,
        session_count=int(daemon.get("active_sessions", 0) or 0) or None,
        active=active,
    )


# ── Scheduler ────────────────────────────────────────────────────────────────
def _build_scheduler(schedule: List[Dict[str, Any]]) -> M.SchedulerState:
    from .scheduler import normalize_cron, humanize_cron
    tasks: List[M.SchedulerTask] = []
    seen: set = set()
    active = paused = 0
    for raw in schedule:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or raw.get("name") or "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        status = str(raw.get("status") or "active")
        if status == "paused":
            paused += 1
        else:
            active += 1
        cron = normalize_cron(str(raw.get("cron") or ""))
        tasks.append(M.SchedulerTask(
            id=tid,
            name=str(raw.get("name") or tid),
            cron=cron,
            humanized=humanize_cron(cron) if cron else "",
            status=status,
            next_run=str(raw.get("next_run") or ""),
            task_type=str(raw.get("task_type") or ""),
        ))
    return M.SchedulerState(
        enabled=True, healthy=True,
        active_count=active, paused_count=paused, tasks=tasks,
    )


# ── Top-level snapshot ───────────────────────────────────────────────────────
def read_snapshot() -> M.RuntimeSnapshot:
    """Read every source once and build a typed RuntimeSnapshot."""
    daemon = _daemon_status()
    proxy = _proxy_metrics()
    ov = _read_json(STATE_DIR / "overseer_state.json", {}) or {}
    steps = _read_json(STATE_DIR / "big_model_steps.json", {}) or {}
    minify = _read_json(STATE_DIR / "minify_stats.json", {}) or {}
    queue = _read_json(STATE_DIR / "overseer_queue.json", []) or []
    schedule = _read_json(STATE_DIR / "overseer_schedule.json", []) or []
    plan = _read_json(STATE_DIR / "overseer_plan.json", {}) or {}
    active_model = _read_json(STATE_DIR / "state" / "active_model.json", {}) or {}

    big = daemon.get("big") if isinstance(daemon.get("big"), dict) else {}
    tiny = daemon.get("tiny") if isinstance(daemon.get("tiny"), dict) else {}
    proxy_up = bool(proxy.get("proxy_up", False)) or bool(daemon.get("proxy", {}).get("running"))
    big_healthy = bool(big.get("healthy", False))
    tiny_healthy = bool(tiny.get("healthy", False))
    backend_healthy = big_healthy or tiny_healthy

    connected = bool(daemon.get("ok")) or bool(proxy)
    data_age = 0.0
    stale = False
    stale_detail = ""
    # Data age from the proxy's last_request_ts or the overseer state mtime.
    last_ts = proxy.get("last_request_ts")
    if isinstance(last_ts, (int, float)) and last_ts:
        data_age = time.time() - last_ts
    if data_age > STALE_AFTER_S:
        stale = True
        stale_detail = f"data current {data_age:.1f}s"

    model = _resolve_model(daemon, proxy, active_model)
    inference = _build_inference(daemon, proxy, big)
    scheduler = _build_scheduler(schedule)

    # Alerts from overseer health events (last few).
    alerts: List[str] = []
    for ev in (ov.get("health_events") or [])[-5:]:
        if isinstance(ev, dict) and ev.get("level") in ("warn", "error", "critical"):
            alerts.append(str(ev.get("message") or ev.get("label") or ""))

    sessions = daemon.get("sessions") or []
    queue_pending = sum(1 for t in queue if t.get("status") == "queued")

    return M.RuntimeSnapshot(
        connected=connected,
        data_age_s=data_age,
        stale=stale,
        stale_detail=stale_detail,
        model=model,
        big_healthy=big_healthy,
        tiny_healthy=tiny_healthy,
        proxy_up=proxy_up,
        backend_healthy=backend_healthy,
        inference=inference,
        capabilities=M.BackendCapabilities(local=True, paid=False),
        scheduler=scheduler,
        minify=minify,
        queue_pending=queue_pending,
        queue_total=len(queue),
        sessions=sessions,
        alerts=alerts,
        last_successful=None,
    )
