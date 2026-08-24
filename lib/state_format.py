#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

STATE_DIR = Path(os.environ.get(
    "CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent")))


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        with path.open(encoding="utf-8") as f:
            d = json.load(f)
        return d if d else default
    except Exception:
        return default







_ACTIVE_MODEL_FRESH_SEC = 60.0


def _resolve_active_model(active_model: Dict[str, Any],
                          big_alias: str,
                          fresh_sec: float = _ACTIVE_MODEL_FRESH_SEC) -> str:

    file_model = ""
    file_ts = None
    if isinstance(active_model, dict):
        m = active_model.get("model")
        if isinstance(m, str) and m.strip():
            file_model = m.strip()
        ts = active_model.get("ts")
        if isinstance(ts, (int, float)):
            file_ts = float(ts)
    live = (big_alias or "").strip() if isinstance(big_alias, str) else ""
    if live:
        return live
    if file_model and file_ts is not None:
        if (time.time() - file_ts) <= fresh_sec:
            return file_model
    if file_model:



        return file_model
    return ""


def _daemon_status() -> Dict[str, Any]:

    try:
        from lib import control
        return control.send_request("status", timeout=2) or {}
    except Exception:
        return {}


def _proxy_metrics() -> Dict[str, Any]:

    try:
        from lib import control
        return control.send_request("proxy-metrics", timeout=2) or {}
    except Exception:
        return {}


def read_state() -> Dict[str, Any]:

    return {
        "daemon": _daemon_status(),
        "proxy": _proxy_metrics(),
        "overseer": _read_json(STATE_DIR / "overseer_state.json", default={}) or {},
        "steps": _read_json(STATE_DIR / "big_model_steps.json", default={}) or {},
        "minify": _read_json(STATE_DIR / "minify_stats.json", default={}) or {},
        "queue": _read_json(STATE_DIR / "overseer_queue.json", default=[]) or [],
        "schedule": _read_json(STATE_DIR / "overseer_schedule.json", default=[]) or [],
        "plan": _read_json(STATE_DIR / "overseer_plan.json", default={}) or {},
        "workflow": _read_json(STATE_DIR / "workflow_state.json", default={}) or {},
        "prompt_queue": _read_json(STATE_DIR / "prompt_queue.json", default={}) or {},
        "active_model": _read_json(STATE_DIR / "state" / "active_model.json", default={}) or {},
    }


def format_statusline(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

    s = state if state is not None else read_state()
    daemon = s.get("daemon") or {}
    big = daemon.get("big") if isinstance(daemon.get("big"), dict) else {}
    minify = s.get("minify") or {}
    proxy = s.get("proxy") or {}
    return {
        "model": _resolve_active_model(
            s.get("active_model") or {}, big.get("alias", "") or ""),
        "minify_runs": int(minify.get("runs", 0)),
        "tokens_saved": int(minify.get("tokens_saved", 0)),
        "ratio_pct": int(minify.get("ratio_pct", 0) or 0),
        "proxy_up": bool(proxy.get("proxy_up", False)),
    }


def format_dashboard(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

    s = state if state is not None else read_state()
    daemon = s.get("daemon") or {}
    big = daemon.get("big") if isinstance(daemon.get("big"), dict) else {}
    tiny = daemon.get("tiny") if isinstance(daemon.get("tiny"), dict) else {}
    vbp = daemon.get("vram_by_proc") if isinstance(daemon.get("vram_by_proc"), dict) else {}
    proxy = s.get("proxy") or {}
    ov = s.get("overseer") or {}
    steps = s.get("steps") or {}
    minify = s.get("minify") or {}
    queue = s.get("queue") or []
    schedule = s.get("schedule") or []
    plan = s.get("plan") or {}
    workflow = s.get("workflow") or {}

    return {

        "model_alias": big.get("alias", ""),
        "tiny_alias": tiny.get("alias", ""),
        "active_model": _resolve_active_model(
            s.get("active_model") or {}, big.get("alias", "") or ""),

        "overseer_label": ov.get("overseer_state", {}).get("label", "idle"),
        "overseer_since": ov.get("overseer_state", {}).get("since", ""),
        "total_ticks": int(ov.get("total_ticks", 0)),
        "last_compact": ov.get("last_compact"),
        "last_distill": ov.get("last_distill"),
        "last_llm_summary": ov.get("last_llm_summary", ""),
        "hot_overflow_ticks": int(ov.get("hot_overflow_ticks", 0)),
        "task_steps": ov.get("task_steps", []) or [],
        "health_events": ov.get("health_events", []) or [],

        "big_steps": steps.get("steps", []) or [],
        "big_step_count": int(steps.get("step_count", 0)),
        "big_tool_calls": int(steps.get("tool_calls", 0)),

        "minify_runs": int(minify.get("runs", 0)),
        "tokens_saved": int(minify.get("tokens_saved", 0)),
        "ratio_pct": int(minify.get("ratio_pct", 0) or 0),

        "queue_pending": sum(1 for t in queue if (t.get("status") == "queued")),
        "queue_total": len(queue),
        "schedule_count": len(schedule),

        "queue": queue,
        "schedule": schedule,
        "plan_name": plan.get("name", ""),
        "plan_total_steps": int(plan.get("total_steps", 0)),
        "plan_current": int(plan.get("current_step", 0) or 0),
        "workflow_total": len(workflow.get("tasks", []) or []),
        "workflow_pending": sum(1 for t in (workflow.get("tasks") or [])
                                if t.get("status") == "PENDING"),
        "workflow_running": sum(1 for t in (workflow.get("tasks") or [])
                                if t.get("status") == "RUNNING"),
        "workflow_completed": sum(1 for t in (workflow.get("tasks") or [])
                                  if t.get("status") == "COMPLETED"),
        "workflow_failed": sum(1 for t in (workflow.get("tasks") or [])
                               if t.get("status") == "FAILED"),

        "vram_big_mb": int(vbp.get("big_mib", 0)),
        "vram_tiny_mb": int(vbp.get("tiny_mib", 0)),
        "vram_other_mb": int(vbp.get("other_mib", 0)),
        "proxy_up": bool(proxy.get("proxy_up", False)),
        "current_in_tps": float(proxy.get("current_in_tps", 0) or 0),
        "current_out_tps": float(proxy.get("current_out_tps", 0) or 0),





        "daemon": daemon,
    }
