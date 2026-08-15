#!/usr/bin/env python3
"""token_tracker.py — Track token usage for both tiny model and proxy paths.

Merges token metrics from:
1. The proxy (big model path) — grammar_proxy.py's token tracking
2. The tiny model path — overseer's tiny model usage

Usage:
  python3 lib/token_tracker.py --smoke          # self-test
  python3 lib/token_tracker.py merge             # merge stats from both paths
  python3 lib/token_tracker.py status            # display merged status
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# ── Token Tracking ──────────────────────────────────────────────────────────
_TOKENS_FILE = Path.home() / ".cortexagent" / "token_tracker.json"
_TOKEN_TRACKING_ENABLED = True

def _load_token_stats() -> Dict:
    """Load token stats from file."""
    try:
        if _TOKENS_FILE.exists():
            with _TOKENS_FILE.open() as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "tiny_model": {
            "runs": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_saved": 0,
            "ratio_pct": 0.0,
            "last_run_ts": 0.0,
        },
        "proxy": {
            "runs": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_saved": 0,
            "ratio_pct": 0.0,
            "last_run_ts": 0.0,
        },
        "total": {
            "runs": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_saved": 0,
            "ratio_pct": 0.0,
            "last_run_ts": 0.0,
        },
        "merged_history": [],  # [(ts, ratio_pct)] for sparkline
    }


def _save_token_stats(stats: Dict) -> None:
    """Save token stats to file."""
    try:
        _TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TOKENS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(stats, default=str))
        tmp.replace(_TOKENS_FILE)
    except Exception:
        pass


def merge_stats() -> Dict:
    """Merge token stats from both paths into a single snapshot."""
    stats = _load_token_stats()

    # 1. Get proxy stats from grammar_proxy
    try:
        from lib.grammar_proxy import _get_minify_snapshot
        proxy_stats = _get_minify_snapshot()
        if proxy_stats:
            stats["proxy"] = proxy_stats
    except Exception:
        pass

    # 2. Get tiny model stats from overseer
    try:
        from lib.overseer import _read_minify_stats
        tiny_stats = _read_minify_stats()
        if tiny_stats:
            stats["tiny_model"] = tiny_stats
    except Exception:
        pass

    # 3. Merge totals
    proxy = stats.get("proxy", {})
    tiny = stats.get("tiny_model", {})
    stats["total"] = {
        "runs": proxy.get("runs", 0) + tiny.get("runs", 0),
        "tokens_in": proxy.get("tokens_in", 0) + tiny.get("tokens_in", 0),
        "tokens_out": proxy.get("tokens_out", 0) + tiny.get("tokens_out", 0),
        "tokens_saved": proxy.get("tokens_saved", 0) + tiny.get("tokens_saved", 0),
        "ratio_pct": 0.0,
        "last_run_ts": max(proxy.get("last_run_ts", 0), tiny.get("last_run_ts", 0)),
    }
    if stats["total"]["tokens_in"] > 0:
        stats["total"]["ratio_pct"] = round(
            stats["total"]["tokens_saved"] / stats["total"]["tokens_in"] * 100, 1
        )

    # 4. Merge history (keep last 60 entries)
    history = []
    for key in ("proxy", "tiny_model"):
        hist = stats.get(key, {}).get("history_60s", [])
        if hist:
            history.extend(hist)
    history.sort(key=lambda x: x[0] if isinstance(x, (list, tuple)) else 0)
    stats["merged_history"] = history[-60:]  # keep last 60

    # 5. Save
    _save_token_stats(stats)
    return stats


def track_tiny_model_run(tokens_in: int, tokens_out: int) -> None:
    """Track a single tiny model run."""
    if not _TOKEN_TRACKING_ENABLED:
        return

    stats = _load_token_stats()
    tiny = stats.get("tiny_model", {})
    now = time.time()

    tiny["runs"] = tiny.get("runs", 0) + 1
    tiny["tokens_in"] = tiny.get("tokens_in", 0) + tokens_in
    tiny["tokens_out"] = tiny.get("tokens_out", 0) + tokens_out
    tiny["tokens_saved"] = tiny.get("tokens_saved", 0) + max(tokens_in - tokens_out, 0)
    tiny["last_run_ts"] = now

    if tiny["tokens_in"] > 0:
        tiny["ratio_pct"] = round(
            tiny["tokens_saved"] / tiny["tokens_in"] * 100, 1
        )

    stats["tiny_model"] = tiny
    _save_token_stats(stats)


def get_status() -> Dict:
    """Get merged token status."""
    stats = merge_stats()
    total = stats.get("total", {})
    return {
        "runs": total.get("runs", 0),
        "tokens_in": total.get("tokens_in", 0),
        "tokens_out": total.get("tokens_out", 0),
        "tokens_saved": total.get("tokens_saved", 0),
        "ratio_pct": total.get("ratio_pct", 0.0),
        "proxy_runs": stats.get("proxy", {}).get("runs", 0),
        "tiny_runs": stats.get("tiny_model", {}).get("runs", 0),
    }


def main():
    """Self-test and demo."""
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        print("Token tracker smoke test:")
        print(f"  Stats file: {_TOKENS_FILE}")
        print(f"  Tracking enabled: {_TOKEN_TRACKING_ENABLED}")

        # Track some test runs
        track_tiny_model_run(100, 90)
        track_tiny_model_run(200, 180)

        # Merge and display
        stats = merge_stats()
        total = stats.get("total", {})
        print(f"  Total runs: {total.get('runs', 0)}")
        print(f"  Tokens in: {total.get('tokens_in', 0)}")
        print(f"  Tokens out: {total.get('tokens_out', 0)}")
        print(f"  Tokens saved: {total.get('tokens_saved', 0)}")
        print(f"  Ratio: {total.get('ratio_pct', 0):.1f}%")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status = get_status()
        print("Token tracker status:")
        for k, v in status.items():
            print(f"  {k}: {v}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        stats = merge_stats()
        total = stats.get("total", {})
        print("Merged token stats:")
        print(f"  Total runs: {total.get('runs', 0)}")
        print(f"  Tokens in: {total.get('tokens_in', 0)}")
        print(f"  Tokens out: {total.get('tokens_out', 0)}")
        print(f"  Tokens saved: {total.get('tokens_saved', 0)}")
        print(f"  Ratio: {total.get('ratio_pct', 0):.1f}%")
        return


if __name__ == "__main__":
    main()
