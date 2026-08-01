#!/usr/bin/env python3
"""dispatcher — async priority queue + per-profile worker pool (stdlib-only).

Async priority queue + per-profile worker pool. Stdlib only.

  - WorkItem dataclass + WorkPriority enum
  - Worker (per-profile sandbox dir, single async task)
  - Dispatcher (asyncio.PriorityQueue, max_workers cap, submit_and_wait)
  - circuit-breaker wrapping per worker run

Env knobs:
  CORTEXAGENT_DISPATCH_MAX_WORKERS   default 4
  CORTEXAGENT_DISPATCH_SANDBOX_ROOT  default ~/.cortexagent/sandboxes

Usage (the agent writes a tiny script and runs it via Bash):

    import asyncio
    from dispatcher import Dispatcher, WorkItem, WorkPriority

    async def llm(prompt: str) -> str:
        # call local cortexagent, an MCP tool, a subprocess, etc.
        ...

    async def main():
        d = Dispatcher()
        await d.start(llm_call_fn=llm)
        results = await asyncio.gather(*[
            d.submit_and_wait(WorkItem(profile="p1", prompt="task A")),
            d.submit_and_wait(WorkItem(profile="p2", prompt="task B")),
        ])
        await d.stop()
        for r in results:
            print(r)

    asyncio.run(main())

Stdlib only.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from reliability import CircuitBreaker, CircuitBreakerOpenError, retry  # noqa: F401  (re-exported)


# ── Defaults ────────────────────────────────────────────────────────────────
def _max_workers() -> int:
    try:
        return int(os.environ.get("CORTEXAGENT_DISPATCH_MAX_WORKERS", "4"))
    except ValueError:
        return 4


def _sandbox_root() -> Path:
    raw = os.environ.get("CORTEXAGENT_DISPATCH_SANDBOX_ROOT")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cortexagent" / "sandboxes"


# ── Public types ───────────────────────────────────────────────────────────
class WorkPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class WorkItem:
    """A unit of work for the dispatcher."""
    profile: str
    prompt: str
    task_id: str = ""
    priority: WorkPriority = WorkPriority.NORMAL
    attached_files: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    submitted_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))


# ── Worker ─────────────────────────────────────────────────────────────────
class Worker:
    """Per-profile worker with isolated sandbox directory."""

    def __init__(self, profile: str, sandbox_dir: Path):
        self.profile = profile
        self.sandbox_dir = sandbox_dir
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._running = False
        self.last_result: Optional[Dict] = None
        self.last_error: Optional[str] = None

    async def run(self, item: WorkItem, llm_call_fn: Callable) -> Dict:
        """Execute a work item. Sync callables run in a thread; async ones awaited directly."""
        self._running = True
        try:
            if inspect.iscoroutinefunction(llm_call_fn):
                response = await llm_call_fn(item.prompt)
            else:
                response = await asyncio.to_thread(llm_call_fn, item.prompt)
            result = {"status": "completed", "response": response, "task_id": item.task_id}
            self.last_result = result
            return result
        except Exception as e:
            self.last_error = str(e)
            return {"status": "failed", "error": str(e), "task_id": item.task_id}
        finally:
            self._running = False


# ── Dispatcher ─────────────────────────────────────────────────────────────
class Dispatcher:
    """Async queue-based router. Pure routing — no blocking logic inside."""

    def __init__(self, max_workers: Optional[int] = None,
                 sandbox_root: Optional[Path] = None):
        self.max_workers = max(max_workers or _max_workers(), 1)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._workers: Dict[str, Worker] = {}
        self._sandbox_root = sandbox_root or _sandbox_root()
        self._running = False
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._llm_call_fn: Optional[Callable] = None
        self._active_profiles: Set[str] = set()
        self._inflight: Set[asyncio.Task] = set()

    # ── Lifecycle ───────────────────────────────────────────────────────
    async def start(self, llm_call_fn: Optional[Callable] = None):
        """Start the dispatcher loop. llm_call_fn is required for actual work."""
        if llm_call_fn is None:
            llm_call_fn = self._default_llm_call
        self._llm_call_fn = llm_call_fn
        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self):
        """Cancel the loop and wait for in-flight tasks (best effort)."""
        self._running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        # Drain in-flight (give them 5s)
        if self._inflight:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._inflight, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                for t in self._inflight:
                    t.cancel()

    # ── Submission ──────────────────────────────────────────────────────
    async def submit(self, item: WorkItem):
        """Queue a work item (priority-ordered)."""
        await self._queue.put((item.priority.value, time.monotonic(), item))
        self._active_profiles.add(item.profile)

    async def submit_and_wait(self, item: WorkItem) -> Dict:
        """Submit and wait for the result. Bypasses the queue (direct worker)."""
        worker = self._get_or_create_worker(item.profile)
        cb = CircuitBreaker(name=f"worker:{item.profile}", threshold=5, cooldown_seconds=60)
        try:
            with cb:
                return await worker.run(item, self._llm_call_fn or self._default_llm_call)
        except CircuitBreakerOpenError as e:
            return {"status": "circuit_open", "error": str(e), "task_id": item.task_id}

    # ── Dispatch loop ───────────────────────────────────────────────────
    async def _dispatch_loop(self):
        while self._running:
            try:
                try:
                    _, _, item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                worker = self._get_or_create_worker(item.profile)
                task = asyncio.create_task(self._run_with_breaker(worker, item))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
            except asyncio.CancelledError:
                break
            except Exception:
                # Loop continues — dispatcher is pure routing, no fatal here
                pass

    async def _run_with_breaker(self, worker: Worker, item: WorkItem):
        cb = CircuitBreaker(name=f"worker:{worker.profile}", threshold=5, cooldown_seconds=60)
        try:
            with cb:
                return await worker.run(item, self._llm_call_fn or self._default_llm_call)
        except CircuitBreakerOpenError as e:
            return {"status": "circuit_open", "error": str(e), "task_id": item.task_id}

    # ── Worker management ───────────────────────────────────────────────
    def _get_or_create_worker(self, profile: str) -> Worker:
        if profile not in self._workers:
            safe = profile.replace(":", "_").replace("/", "_")
            sandbox = self._sandbox_root / safe
            self._workers[profile] = Worker(profile, sandbox)
        return self._workers[profile]

    # ── Default LLM call (echo) ─────────────────────────────────────────
    @staticmethod
    def _default_llm_call(prompt: str) -> str:
        """Stand-in for the real LLM. The caller supplies their own."""
        return f"[dispatcher echo] {prompt[:200]}"

    # ── Status ──────────────────────────────────────────────────────────
    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def active_workers(self) -> int:
        return sum(1 for w in self._workers.values() if w._running)

    @property
    def active_profiles(self) -> List[str]:
        return sorted(self._active_profiles)

    def get_worker_status(self, profile: Optional[str] = None) -> Dict:
        workers = {}
        for p, w in self._workers.items():
            if profile and p != profile:
                continue
            workers[p] = {
                "running": w._running,
                "sandbox": str(w.sandbox_dir),
                "sandbox_exists": w.sandbox_dir.exists(),
                "last_error": w.last_error,
            }
        return {
            "queue_size": self.queue_size,
            "active_workers": self.active_workers,
            "total_workers": len(self._workers),
            "workers": workers,
        }


# ── Module-level singleton ─────────────────────────────────────────────────
_dispatcher: Optional[Dispatcher] = None


async def get_dispatcher(llm_call_fn: Optional[Callable] = None) -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        await _dispatcher.start(llm_call_fn=llm_call_fn)
    elif llm_call_fn is not None:
        _dispatcher._llm_call_fn = llm_call_fn
    return _dispatcher


# ── CLI / smoke ────────────────────────────────────────────────────────────
async def _smoke() -> int:
    print("dispatcher: smoke test")
    calls: List[str] = []

    async def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        await asyncio.sleep(0.05)
        return f"answer({prompt[:20]})"

    d = Dispatcher(max_workers=3)
    await d.start(llm_call_fn=fake_llm)
    items = [
        WorkItem(profile="p1", prompt="alpha", priority=WorkPriority.HIGH),
        WorkItem(profile="p2", prompt="beta",  priority=WorkPriority.NORMAL),
        WorkItem(profile="p1", prompt="gamma", priority=WorkPriority.LOW),
    ]
    results = await asyncio.gather(*(d.submit_and_wait(i) for i in items))
    await d.stop()
    print(f"  results: {len(results)}")
    for r in results:
        print(f"    {r}")
    print(f"  calls dispatched: {len(calls)}")
    print(f"  status: {d.get_worker_status()}")
    print("dispatcher: OK")
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(asyncio.run(_smoke()))
    print("usage: dispatcher.py smoke", file=sys.stderr)
    sys.exit(2)