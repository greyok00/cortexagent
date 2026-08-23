#!/usr/bin/env python3
"""browser_pool — speed via context reuse + parallel workers (§7).

Speed gains come ONLY from concurrency and caching, never from altering
observable page-load behavior. Per spec: do NOT block images, fonts, CSS, or
disable JavaScript — that creates a behavioral anomaly vs real browsing and
undermines stealth. Images/JS/CSS load normally in every pooled context.

  - BrowserPool: opens N reusable browser tabs once (lazily), injects the
    stealth init script on each, and hands them out to workers. Tabs are
    returned to the pool, not closed — reused across tasks (no relaunch).
  - run_parallel(): run independent tasks across workers, scaled to CPU cores.
  - Stealth profile/init script are cached at module level (browser_control)
    so the patched setup is not reinitialized per run.
"""
from __future__ import annotations

import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional


class BrowserPool:
    """A pool of reusable browser tabs (contexts).

    bc is the browser_control module. On first acquire, up to `max_workers`
    tabs are opened (or existing tabs adopted) and stealth-initialized.
    acquire() returns a target_id; release() returns it to the pool.
    """

    def __init__(self, bc: Any, max_workers: Optional[int] = None) -> None:
        self.bc = bc
        self.max_workers = max_workers or max(2, (multiprocessing.cpu_count() or 4) - 1)
        self._idle: List[str] = []          # idle target ids
        self._busy: set = set()
        self._all: List[str] = []           # every tab we manage
        self._init = False

    def _init_pool(self) -> None:
        if self._init:
            return
        # Adopt existing tabs first (reuse, don't relaunch the browser).
        tabs = self.bc.list_tabs()
        for t in tabs[: self.max_workers]:
            self._all.append(t["id"])
            self._idle.append(t["id"])
        # Open extra tabs if we need more workers than tabs exist.
        while len(self._all) < self.max_workers:
            tid = self.bc.new_tab("about:blank")
            self._all.append(tid)
            self._idle.append(tid)
        # Ensure stealth is applied to each (browser_control._ensure_stealth).
        for tid in self._all:
            try:
                self.bc._ensure_stealth(tid)
            except Exception:
                pass
        self._init = True

    def acquire(self, timeout: float = 30.0) -> str:
        """Get an idle target id, waiting if none is currently free."""
        self._init_pool()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._idle:
                tid = self._idle.pop(0)
                self._busy.add(tid)
                return tid
            time.sleep(0.05)
        raise RuntimeError("browser pool exhausted (no idle tab within timeout)")

    def release(self, tid: str) -> None:
        self._busy.discard(tid)
        if tid not in self._all:
            return
        if tid not in self._idle:
            self._idle.append(tid)

    def __enter__(self) -> "BrowserPool":
        self._init_pool()
        return self

    def __exit__(self, *exc) -> None:
        # Leave tabs open for reuse; just clear busy state.
        self._busy.clear()
        self._idle = list(self._all)


def run_parallel(bc: Any, tasks: List[Dict[str, Any]],
                 fn: Callable[[Any, Dict[str, Any]], Any],
                 max_workers: Optional[int] = None) -> List[Any]:
    """Run `fn(bc, task)` for each task across a shared BrowserPool.

    Each task gets its own reusable tab; tasks run concurrently up to
    max_workers (default: CPU-1). Results are returned in input order.
    `fn` receives (bc, task) and may use bc.navigate/click/type via the tab it
    acquires from the pool — it should accept a 'tab' key in the task dict.
    """
    pool = BrowserPool(bc, max_workers=max_workers)

    def _runner(task: Dict[str, Any]) -> Any:
        tid = pool.acquire()
        try:
            task = dict(task)
            task["tab"] = tid
            return fn(bc, task)
        finally:
            pool.release(tid)

    results: List[Any] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=pool.max_workers) as ex:
        future_to_idx = {ex.submit(_runner, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"error": str(e)}
    return results