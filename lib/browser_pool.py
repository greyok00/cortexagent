#!/usr/bin/env python3

from __future__ import annotations

import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional


class BrowserPool:


    def __init__(self, bc: Any, max_workers: Optional[int] = None) -> None:
        self.bc = bc
        self.max_workers = max_workers or max(2, (multiprocessing.cpu_count() or 4) - 1)
        self._idle: List[str] = []
        self._busy: set = set()
        self._all: List[str] = []
        self._opened: set = set()
        self._init = False

    def _init_pool(self) -> None:
        if self._init:
            return

        tabs = self.bc.list_tabs()
        for t in tabs[: self.max_workers]:
            self._all.append(t["id"])
            self._idle.append(t["id"])


        while len(self._all) < self.max_workers:
            tid = self.bc.new_tab("about:blank")
            self._all.append(tid)
            self._idle.append(tid)
            self._opened.add(tid)

        for tid in self._all:
            try:
                self.bc._ensure_stealth(tid)
            except Exception:
                pass
        self._init = True

    def acquire(self, timeout: float = 30.0) -> str:

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

    def close(self) -> None:

        for tid in list(self._opened):
            try:
                self.bc.close_tab(tid)
            except Exception:
                pass
        self._opened.clear()
        self._all = [t for t in self._all if t not in self._opened]
        self._idle = [t for t in self._idle if t not in self._opened]
        self._busy.clear()

    def __exit__(self, *exc) -> None:

        self.close()


def run_parallel(bc: Any, tasks: List[Dict[str, Any]],
                 fn: Callable[[Any, Dict[str, Any]], Any],
                 max_workers: Optional[int] = None) -> List[Any]:

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
    with pool, ThreadPoolExecutor(max_workers=pool.max_workers) as ex:
        future_to_idx = {ex.submit(_runner, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"error": str(e)}
    return results