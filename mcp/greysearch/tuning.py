"""tuning.py: pacing values the Greysearch engine actually obeys.

Defaults are the human-pace floors the engine obeys. doctor.py writes
research/tuning.json after its checks; anything present there overrides a
default. Every value is a floor-or-slower: tuning can never make the engine
faster than the defaults, only more patient.
"""

import json
import os
import threading

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_TUNING_PATH = os.path.join(_REPO_ROOT, "research", "tuning.json")

_LOCK = threading.Lock()
_CACHE: dict = {}
_CACHE_MTIME: float = 0.0

DEFAULTS = {
    "politeness_s": 3.0,
    "page_gap_min_s": 3.5,
    "page_gap_max_s": 7.0,
    "human_gap_s": 15.0,
    "human_gap_jitter_s": 5.0,
    "warmup_jitter_s": 15.0,
    "probe_gap_min_s": 3.0,
    "probe_gap_max_s": 6.0,
    "pace_floor_s": 8.0,
    "slow_factor": 1.0,
}

HARD_FLOORS = {
    "politeness_s": 3.0,
    "page_gap_min_s": 3.5,
    "page_gap_max_s": 3.6,
    "human_gap_s": 15.0,
    "probe_gap_min_s": 3.0,
    "pace_floor_s": 8.0,
    "slow_factor": 1.0,
}

def _load_file() -> dict:
    try:
        with open(_TUNING_PATH) as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def values() -> dict:
    """Effective tuning: defaults <- tuning.json, floors enforced."""
    global _CACHE, _CACHE_MTIME
    try:
        mtime = os.path.getmtime(_TUNING_PATH)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if _CACHE and mtime == _CACHE_MTIME:
            return dict(_CACHE)
        eff = dict(DEFAULTS)
        for k, v in _load_file().items():
            if k in eff and isinstance(v, (int, float)) and v > 0:
                eff[k] = float(v)
        for k, floor in HARD_FLOORS.items():
            if eff[k] < floor:
                eff[k] = float(floor)
        _CACHE, _CACHE_MTIME = eff, mtime
        return dict(_CACHE)

def get(key: str, default: float | None = None) -> float:
    v = values().get(key)
    if v is None:
        return float(default if default is not None else 0.0)
    return float(v)

def scaled(key: str) -> float:
    """Value with the doctor's slow_factor applied.

    slow_factor only ever multiplies upward (>=1.0): tuning slows gaps, it
    never speeds them past the floor."""
    sf = max(1.0, get("slow_factor", 1.0))
    return get(key) * sf

def write(updates: dict) -> dict:
    """doctor.py writes findings-driven adjustments; floors stay enforced."""
    cur = values()
    for k, v in updates.items():
        if k == "slow_factor":
            cur["slow_factor"] = max(1.0, min(3.0, float(v)))
        elif k in cur and isinstance(v, (int, float)) and v > 0:
            cur[k] = max(float(v), HARD_FLOORS.get(k, 0.0))
    os.makedirs(os.path.dirname(_TUNING_PATH), exist_ok=True)
    with open(_TUNING_PATH, "w") as f:
        json.dump(cur, f, indent=1)
    global _CACHE, _CACHE_MTIME
    with _LOCK:
        _CACHE, _CACHE_MTIME = {}, 0.0
    return values()