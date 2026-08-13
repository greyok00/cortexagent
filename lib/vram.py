#!/usr/bin/env python3
"""lib/vram.py — VRAM budget: locked buffer + free-for-adapters.

The GPU is shared. Required residents (never evicted): the big model, the
overseer, and faster-whisper. Everything else — multimodal adapters (Moondream,
whisper) and the RAG embedding model — may use the remaining free VRAM minus a
locked buffer that is never touched. The buffer is crash protection: the
desktop must never OOM, so a fixed slice of VRAM stays reserved no matter what.

Adapters and the embedder call `can_fit(mb)` before loading on GPU and fall
back to CPU when the budget is too small. `budget_mib()` is the free VRAM
reported by nvidia-smi minus the locked buffer; when the big model is loaded
the budget is near zero and everything runs on CPU, when it is down the budget
is ~14 GB and Moondream can load on GPU.

Usage:
  python3 lib/vram.py --smoke
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from lib.config import CFG


def free_mib() -> Optional[int]:
    """Free VRAM in MiB via nvidia-smi, or None if no GPU / query fails."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
        return int(line) if line else None
    except Exception:
        return None


def budget_mib() -> Optional[int]:
    """VRAM available for adapters/RAG = free VRAM - locked buffer.

    Returns None when the GPU is unavailable (callers treat that as "no GPU,
    stay on CPU"). Never negative: the buffer is clamped to the free VRAM.
    """
    f = free_mib()
    if f is None:
        return None
    return max(f - int(CFG.vram_buffer_mb), 0)


def can_fit(mb: int) -> bool:
    """True if `mb` MiB fits in the adapter/RAG budget (GPU usable)."""
    b = budget_mib()
    return b is not None and mb <= b


def _smoke() -> int:
    fails = 0
    f = free_mib()
    print(f"free_mib() = {f}")
    if f is not None and f <= 0:
        print("❌ free_mib() should be > 0 on a GPU box")
        fails += 1
    b = budget_mib()
    print(f"budget_mib() = {b} (buffer={CFG.vram_buffer_mb})")
    if b is not None:
        if b > f:
            print("❌ budget_mib() > free_mib()")
            fails += 1
        # can_fit must agree with the budget
        if can_fit(b) is not True:
            print("❌ can_fit(budget) should be True")
            fails += 1
        if can_fit(b + 1) is not False:
            print("❌ can_fit(budget+1) should be False")
            fails += 1
    print("vram smoke PASS" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        return _smoke()
    print("Usage: python3 lib/vram.py --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
