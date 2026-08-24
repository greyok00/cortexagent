#!/usr/bin/env python3

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


_TOKENS_FILE = Path.home() / ".cortexagent" / "token_tracker.json"
_TOKEN_TRACKING_ENABLED = True

def _load_token_stats() -> Dict:

    try:
        if _TOKENS_FILE.exists():
            with _TOKENS_FILE.open(encoding="utf-8") as f:
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
        "merged_history": [],
    }


def _save_token_stats(stats: Dict) -> None:

    try:
        _TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TOKENS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(stats, default=str), encoding="utf-8")
        tmp.replace(_TOKENS_FILE)
    except Exception:
        pass


def _normalize_token_file(stats: Dict) -> None:

    if "tiny_model" not in stats and "runs" in stats:
        stats["tiny_model"] = {
            "runs": stats.get("runs", 0),
            "tokens_in": stats.get("tokens_in", 0),
            "tokens_out": stats.get("tokens_out", 0),
            "tokens_saved": stats.get("tokens_saved", 0),
            "ratio_pct": stats.get("ratio_pct", 0.0),
            "last_run_ts": stats.get("last_run_ts", 0.0),
        }
        for k in ("runs", "tokens_in", "tokens_out", "tokens_saved",
                  "ratio_pct", "last_run_ts"):
            stats.pop(k, None)


def merge_stats() -> Dict:

    stats = _load_token_stats()


    try:
        from lib.grammar_proxy import _get_minify_snapshot
        proxy_stats = _get_minify_snapshot()
        if proxy_stats:
            stats["proxy"] = proxy_stats
    except Exception:
        pass




    _normalize_token_file(stats)
    tiny = stats.get("tiny_model", {})


    proxy = stats.get("proxy", {})
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


    history = []
    for key in ("proxy", "tiny_model"):
        hist = stats.get(key, {}).get("history_60s", [])
        if hist:
            history.extend(hist)
    history.sort(key=lambda x: x[0] if isinstance(x, (list, tuple)) else 0)
    stats["merged_history"] = history[-60:]


    _save_token_stats(stats)
    return stats


def track_tiny_model_run(tokens_in: int, tokens_out: int) -> None:

    if not _TOKEN_TRACKING_ENABLED:
        return

    stats = _load_token_stats()
    tiny = stats.get("tiny_model", {})
    now = time.time()

    tiny["runs"] = tiny.get("runs", 0) + 1
    tiny["tokens_in"] = tiny.get("tokens_in", 0) + tokens_in
    tiny["tokens_out"] = tiny.get("tokens_out", 0) + tokens_out

    tiny["tokens_saved"] = 0
    tiny["ratio_pct"] = 0.0
    tiny["last_run_ts"] = now


    hist = tiny.setdefault("history_60s", [])
    hist.append((now, tokens_in))
    cutoff = now - 60.0
    if len(hist) > 60:
        hist[:] = [(t, v) for (t, v) in hist if t >= cutoff][-60:]

    stats["tiny_model"] = tiny
    _save_token_stats(stats)


def get_status() -> Dict:

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

    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        print("Token tracker smoke test:")
        print(f"  Stats file: {_TOKENS_FILE}")
        print(f"  Tracking enabled: {_TOKEN_TRACKING_ENABLED}")


        track_tiny_model_run(100, 90)
        track_tiny_model_run(200, 180)


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
