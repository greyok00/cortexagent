"""lib/overseer_dashboard/settings.py — active/pending settings engine.

Maintains ``activeSettings`` and ``pendingSettings`` separately. Changed
fields are marked Pending; Apply is enabled only when pending differs from
active; Revert restores active values; Save-as-default persists only after
confirmation. Disruptive changes (model, backend, context-window, service)
require explicit confirmation and identify the affected active work.

Controls are gated by backend capabilities — unsupported controls are not
shown.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import models as M

STATE_DIR = Path(os.environ.get(
    "CORTEXAGENT_STATE_DIR", str(Path.home() / ".cortexagent")))
DEFAULTS_FILE = STATE_DIR / "overseer_dashboard_defaults.json"

# Disruptive keys: changing these interrupts/resets active work.
_DISRUPTIVE = {"model", "backend", "context_window", "route", "scheduler_enabled"}


def _default_definitions() -> Dict[str, M.SettingValue]:
    return {
        # ── Runtime ────────────────────────────────────────────────────
        "model": M.SettingValue("model", "Model", "", kind="select",
                                group="runtime", disruptive=True,
                                tooltip="Concrete serving model. Changing interrupts active work."),
        "route": M.SettingValue("route", "Route / profile", "cortex-big",
                                kind="select", group="runtime", disruptive=True,
                                tooltip="Route/profile alias."),
        "backend": M.SettingValue("backend", "Backend / provider", "Ollama",
                                 kind="select", group="runtime", disruptive=True,
                                 tooltip="Inference provider."),
        "context_window": M.SettingValue("context_window", "Context window", 156000,
                                         kind="number", group="runtime", disruptive=True,
                                         min=4096, max=262144, step=1024,
                                         tooltip="Max context tokens. Changing resets active work."),
        "temperature": M.SettingValue("temperature", "Temperature", 0.7,
                                      kind="slider", group="runtime",
                                      min=0.0, max=2.0, step=0.05,
                                      tooltip="Sampling temperature."),
        "top_p": M.SettingValue("top_p", "Top-p", 0.9, kind="slider",
                                group="runtime", min=0.0, max=1.0, step=0.01),
        "top_k": M.SettingValue("top_k", "Top-k", 40, kind="number",
                                group="runtime", min=0, max=200, step=1),
        "repeat_penalty": M.SettingValue("repeat_penalty", "Repeat penalty", 1.1,
                                         kind="slider", group="runtime",
                                         min=0.0, max=2.0, step=0.05),
        "seed": M.SettingValue("seed", "Seed", -1, kind="number",
                               group="runtime", min=-1, max=2**31, step=1),
        "max_output_tokens": M.SettingValue("max_output_tokens", "Max output tokens", 3431,
                                            kind="number", group="runtime",
                                            min=64, max=32768, step=64),
        "streaming": M.SettingValue("streaming", "Streaming", True, kind="toggle",
                                    group="runtime"),
        "system_profile": M.SettingValue("system_profile", "System profile", "coding-agent",
                                         kind="select", group="runtime",
                                         options=["coding-agent", "strict-tools", "general"]),
        # ── SlimToken ───────────────────────────────────────────────────
        "slimtoken_enabled": M.SettingValue("slimtoken_enabled", "Enable SlimToken", True,
                                            kind="toggle", group="slimtoken",
                                            tooltip="Optimize eligible context before inference."),
        "slimtoken_policy": M.SettingValue("slimtoken_policy", "Policy", "balanced",
                                           kind="select", group="slimtoken",
                                           options=["conservative", "balanced", "aggressive", "custom"]),
        "target_context_budget": M.SettingValue("target_context_budget", "Target context budget", 120000,
                                                kind="number", group="slimtoken",
                                                min=4096, max=262144, step=1024),
        "dedup": M.SettingValue("dedup", "Deduplication", True, kind="toggle",
                                group="slimtoken"),
        "history_compact_threshold": M.SettingValue("history_compact_threshold", "History compaction threshold", 2000,
                                                    kind="number", group="slimtoken",
                                                    min=256, max=32768, step=256),
        "retrieval_budget": M.SettingValue("retrieval_budget", "Retrieval token budget", 2000,
                                           kind="number", group="slimtoken",
                                           min=256, max=32768, step=256),
        "cache_reuse": M.SettingValue("cache_reuse", "Cache reuse", False, kind="toggle",
                                      group="slimtoken", supported=False,
                                      tooltip="Only when the backend supports it."),
        # ── Service / scheduler ─────────────────────────────────────────
        "scheduler_enabled": M.SettingValue("scheduler_enabled", "Scheduler enabled", True,
                                            kind="toggle", group="service", disruptive=True),
        "scheduler_timezone": M.SettingValue("scheduler_timezone", "Scheduler timezone", "local",
                                             kind="select", group="service",
                                             options=["local", "UTC"]),
        "retry_limit": M.SettingValue("retry_limit", "Retry limit", 3, kind="number",
                                      group="service", min=0, max=10, step=1),
        "retry_backoff": M.SettingValue("retry_backoff", "Retry backoff (s)", 2.0,
                                        kind="slider", group="service", min=0.0, max=60.0, step=0.5),
        "refresh_interval": M.SettingValue("refresh_interval", "Refresh interval (s)", 1.0,
                                           kind="slider", group="service", min=0.5, max=30.0, step=0.5),
        "log_level": M.SettingValue("log_level", "Logging level", "info",
                                    kind="select", group="service",
                                    options=["debug", "info", "warn", "error"]),
        "warmup": M.SettingValue("warmup", "Model warm-up / preload", False, kind="toggle",
                                 group="service", supported=False,
                                 tooltip="Only when the backend supports it."),
    }


def _load_defaults() -> Dict[str, Any]:
    try:
        with DEFAULTS_FILE.open() as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_defaults(defaults: Dict[str, Any]) -> None:
    try:
        DEFAULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DEFAULTS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(defaults, indent=2))
        tmp.replace(DEFAULTS_FILE)
    except Exception:
        pass


def build_settings(capabilities: M.BackendCapabilities,
                   model: Optional[M.ModelIdentity] = None,
                   ) -> M.SettingsState:
    """Build a SettingsState from definitions, defaults, and capabilities."""
    defs = _default_definitions()
    defaults = _load_defaults()
    active: Dict[str, Any] = {}
    for key, d in defs.items():
        # Capability gating: unsupported controls are hidden.
        if not d.supported:
            continue
        if key == "cache_reuse" and not capabilities.supports_cache_reuse:
            continue
        if key == "warmup" and not capabilities.supports_warmup:
            continue
        if key == "model" and model is not None:
            active[key] = model.display_model()
        elif key == "route" and model is not None:
            active[key] = model.route
        elif key == "backend" and model is not None:
            active[key] = model.backend
        else:
            active[key] = defaults.get(key, d.value)
    return M.SettingsState(
        active=active, pending=dict(active), defaults=defaults,
        definitions=defs)


def set_pending(state: M.SettingsState, key: str, value: Any) -> None:
    """Set a pending value. No-op if the key is unsupported."""
    d = state.definitions.get(key)
    if d is None or not d.supported:
        return
    state.pending[key] = value


def apply_pending(state: M.SettingsState) -> List[str]:
    """Apply pending → active. Returns the list of keys that changed."""
    changed = state.changed_keys
    for k in changed:
        state.active[k] = state.pending[k]
    return changed


def revert_pending(state: M.SettingsState) -> None:
    """Restore pending to active values."""
    state.pending = dict(state.active)


def save_as_default(state: M.SettingsState) -> None:
    """Persist active values as defaults (after confirmation)."""
    defaults = {k: v for k, v in state.active.items()
                if k not in ("model", "route", "backend")}
    _save_defaults(defaults)
    state.defaults = defaults


def disruptive_keys(state: M.SettingsState) -> List[str]:
    """Keys among the pending changes that are disruptive (interrupt work)."""
    return [k for k in state.changed_keys
            if state.definitions.get(k) and state.definitions[k].disruptive]
