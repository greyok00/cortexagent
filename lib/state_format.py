#!/usr/bin/env python3
"""lib/state_format.py — shared state formatter for CortexAgent UI surfaces.

Three UI surfaces all read the same backing data (overseer state, daemon
status, big-model steps, minify stats, queue, schedule, plan, workflow):

  - lib/tray_dashboard.py — Tkinter tray popout (1Hz polling, compact view)
  - lib/webui.py          — :8090 webui dashboard (5s polling, full schema)
  - lib/statusline.py     — CLI bottom bar (per-call, minify-only slice)

Each previously wrote its own _read_json + key names, which meant adding a
new state field required three coordinated edits. This module is the single
source of truth:

  - `read_state()`   — load + validate every state file once, returns a
                       canonical dict; missing files yield sensible defaults.
  - `format_dashboard()` — full bundle (tray popout + webui cards schema).
  - `format_statusline()` — compact bundle (minify + model name only).

Callers that need a single field should still use the canonical bundle's
key rather than rolling their own reader.
"""
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
        with path.open() as f:
            d = json.load(f)
        return d if d else default
    except Exception:
        return default


# ── Active-model fallback (mtime-aware) ────────────────────────────────────
# state/active_model.json is written by the daemon only when the model
# changes, not on every tick — so a stale file can show a retired model
# (e.g. lfm2.5-8b-a1b) long after the live big model swapped. The live
# daemon control socket is the source of truth; the disk file is a hint.
_ACTIVE_MODEL_FRESH_SEC = 60.0


def _resolve_active_model(active_model: Dict[str, Any],
                          big_alias: str,
                          fresh_sec: float = _ACTIVE_MODEL_FRESH_SEC) -> str:
    """Return the active model name with disk-file fallback semantics.

    Order of preference:
      1. Live daemon `big.alias` if non-empty (always wins).
      2. Disk `state/active_model.json` `model` field if its `ts` is < fresh_sec.
      3. Live `big.alias` even if empty (rarely — only when disk is missing too).
    """
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
        # File existed with a model but ts is stale or missing — keep the
        # last known model rather than going blank. The freshness strip in
        # the tray popout will flag the file as stale.
        return file_model
    return ""


def _daemon_status() -> Dict[str, Any]:
    """Read daemon status via the AF_UNIX control socket. Optional; empty on
    failure (the daemon may be stopped — that's fine for UI surfaces)."""
    try:
        from lib import control
        return control.send_request("status", timeout=2) or {}
    except Exception:
        return {}


def _proxy_metrics() -> Dict[str, Any]:
    """Read proxy metrics. Currently the webui is the only place that hits
    the proxy directly; surfaces that don't need it get an empty dict."""
    try:
        from lib import control
        return control.send_request("proxy-metrics", timeout=2) or {}
    except Exception:
        return {}


def read_state() -> Dict[str, Any]:
    """Read every backing state file once and return a canonical dict.

    Keys (all present, defaults if missing):
        daemon:        full daemon status (or {})
        proxy:         proxy metrics (or {})
        overseer:      overseer_state.json (label, since, last_llm_summary,
                       health_events, total_ticks, last_compact, last_distill,
                       task_steps, hot_overflow_ticks)
        steps:         big_model_steps.json (or {})
        minify:        minify_stats.json (or {})
        queue:         overseer_queue.json (list)
        schedule:      overseer_schedule.json (list)
        plan:          overseer_plan.json (or {})
        workflow:      workflow_state.json (or {})
        prompt_queue:  prompt_queue.json (or {})
        active_model:  state/active_model.json (or {})
    """
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
    """Compact bundle for lib/statusline.py — model name + minify ratio.

    Returned keys:
        model:        big model alias (or "")
        minify_runs:  total minify invocations (int)
        tokens_saved: cumulative tokens saved (int)
        ratio_pct:    savings as a percentage of input (int, 0-100)
        proxy_up:     whether the grammar proxy is reachable (bool)
    """
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
    """Full bundle for tray_dashboard + webui. Includes every field those
    surfaces render, with normalized key names. Callers should consume this
    rather than poking at the raw state files.

    Tray popout reads a subset: overseer.label, overseer.task_steps,
    steps.steps, plan.current_step.
    Webui reads the whole bundle + compose it into makeCards(j) cards.
    """
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
        # ── Identity ──────────────────────────────────────────────────
        "model_alias": big.get("alias", ""),
        "tiny_alias": tiny.get("alias", ""),
        "active_model": _resolve_active_model(
            s.get("active_model") or {}, big.get("alias", "") or ""),
        # ── Overseer state ────────────────────────────────────────────
        "overseer_label": ov.get("overseer_state", {}).get("label", "idle"),
        "overseer_since": ov.get("overseer_state", {}).get("since", ""),
        "total_ticks": int(ov.get("total_ticks", 0)),
        "last_compact": ov.get("last_compact"),
        "last_distill": ov.get("last_distill"),
        "last_llm_summary": ov.get("last_llm_summary", ""),
        "hot_overflow_ticks": int(ov.get("hot_overflow_ticks", 0)),
        "task_steps": ov.get("task_steps", []) or [],
        "health_events": ov.get("health_events", []) or [],
        # ── Big-model steps (tray popout reads this) ──────────────────
        "big_steps": steps.get("steps", []) or [],
        "big_step_count": int(steps.get("step_count", 0)),
        "big_tool_calls": int(steps.get("tool_calls", 0)),
        # ── Minify ────────────────────────────────────────────────────
        "minify_runs": int(minify.get("runs", 0)),
        "tokens_saved": int(minify.get("tokens_saved", 0)),
        "ratio_pct": int(minify.get("ratio_pct", 0) or 0),
        # ── Queue / Schedule / Plan / Workflow ────────────────────────
        "queue_pending": sum(1 for t in queue if (t.get("status") == "queued")),
        "queue_total": len(queue),
        "schedule_count": len(schedule),
        # v0.5.3: expose raw arrays so tray + webui can paint per-item
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
        # ── VRAM / proxy ──────────────────────────────────────────────
        "vram_big_mb": int(vbp.get("big_mib", 0)),
        "vram_tiny_mb": int(vbp.get("tiny_mib", 0)),
        "vram_other_mb": int(vbp.get("other_mib", 0)),
        "proxy_up": bool(proxy.get("proxy_up", False)),
        "current_in_tps": float(proxy.get("current_in_tps", 0) or 0),
        "current_out_tps": float(proxy.get("current_out_tps", 0) or 0),
        # ── Raw daemon (v0.5.3) ────────────────────────────────────────
        # Consumers (tray popout, webui) need the full daemon dict for
        # sessions list, profile, idle_sec, model_alias, etc. Earlier
        # versions stripped it, which made the OVERSEER panel claim
        # "all models down" even when big + tiny were live.
        "daemon": daemon,
    }
