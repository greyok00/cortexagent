#!/usr/bin/env python3
"""
CortexLLM Model Router (2026-07-29)
Multi-tier routing with local fallback.
Primary: deepseek-v4-flash:cloud (cloud, best quality)
Fallback 1: gemma4:fixed (local 8B, 4.5GB VRAM, tool-call capable)
Fallback 2: qwen3.6:fixed (local 36B MoE, 12GB VRAM, best quality)
All :fixed models have proper chat templates for system messages and tool calls.
"""

import json
import urllib.request
from pathlib import Path
from typing import Tuple, Optional, Dict, List

# ─── Model Tiers ──────────────────────────────────────────────────────────────
# Ordered by preference — first available is used
MODEL_TIERS = [
    {
        "id": "cloud",
        "model": "ollama/deepseek-v4-flash:cloud",
        "label": "deepseek cloud",
        "check": lambda: _check_ollama_model("deepseek-v4-flash:cloud"),
    },
    {
        "id": "local_light",
        "model": "gemma4:fixed",
        "label": "gemma4 local (8B)",
        "check": lambda: _check_ollama_model("gemma4:fixed"),
    },
    {
        "id": "local_moe",
        "model": "qwen3.6:fixed",
        "label": "qwen3.6 local MoE (36B)",
        "check": lambda: _check_ollama_model("qwen3.6:fixed"),
    },
]

# Cache for availability checks (avoids hammering Ollama on every call)
_availability_cache: Dict[str, bool] = {}


def _check_ollama_model(model_name: str) -> bool:
    """Check if a model is available in Ollama (cached for 30s)."""
    if model_name in _availability_cache:
        return _availability_cache[model_name]
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            available = any(m["name"] == model_name for m in data.get("models", []))
            _availability_cache[model_name] = available
            return available
    except Exception:
        _availability_cache[model_name] = False
        return False


def get_best_available_model() -> Tuple[str, str]:
    """
    Return (model_id, label) of the best available model tier.
    Falls through tiers until one is available.
    """
    for tier in MODEL_TIERS:
        try:
            if tier["check"]():
                return tier["model"], tier["label"]
        except Exception:
            continue
    # Last resort — return local MoE even if check failed (it might still load)
    return MODEL_TIERS[1]["model"], MODEL_TIERS[1]["label"]


# Resolve models at import time
PRIMARY_MODEL, PRIMARY_LABEL = get_best_available_model()
SUBAGENT_MODEL = PRIMARY_MODEL  # Sub-agents use same model as primary


def should_delegate(task: str) -> bool:
    """
    Determine if a task should run in a sub-agent.
    Uses the same model — splits compute, not model type.

    Delegates when task is long-running or independent.
    """
    delegate_keywords = [
        "search", "fetch", "monitor", "watch", "scrape",
        "background", "batch", "bulk", "long", "heavy",
        "file_operation", "data_processing"
    ]
    task_lower = task.lower()
    for kw in delegate_keywords:
        if kw in task_lower:
            return True
    return False


def create_worker_task(task: str, label: str = "worker") -> Dict:
    """Create sub-agent task config — uses best available model."""
    model, model_label = get_best_available_model()
    return {
        "task": task,
        "model": model,
        "label": label,
        "runtime": "subagent"
    }


def classify_and_delegate(task: str) -> Tuple[bool, Optional[Dict]]:
    """
    Decide: run in main session or spawn sub-agent.
    Uses best available model from the tier chain.

    Returns:
        (False, None) — run in main session
        (True, task_config) — spawn sub-agent
    """
    if should_delegate(task):
        return True, create_worker_task(task)
    return False, None


# Test
if __name__ == "__main__":
    model, label = get_best_available_model()
    print(f"Model Router v0.4.0 (2026-07-29)")
    print(f"Active model: {model} ({label})")
    print(f"Fallback chain: {' → '.join(t['label'] for t in MODEL_TIERS)}")
    print()
    for task in [
        "Find my calendar events for this week",
        "Search for job postings",
        "Fix the broken memory integration",
        "Monitor the uptime of my server",
        "Explain to the user what happened",
    ]:
        delegate, cfg = classify_and_delegate(task)
        if delegate:
            print(f"  ⤵ {task} → sub-agent ({cfg['model']})")
        else:
            print(f"  →  {task} → main session")
