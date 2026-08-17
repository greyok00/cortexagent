"""lib/overseer_dashboard/testharness.py — isolated test-run engine.

Test runs are fully isolated from normal CLI conversations:
  - each run gets an independent test session/request ID
  - a test never replaces, cancels, mutates, or pollutes a normal
    CortexAgent CLI conversation
  - remote/paid backends require explicit confirmation
  - the UI shows clearly whether a test runs active or pending settings

By default a test is a **dry-run** (Compose + SlimToken + Finalize token math,
no inference request). A real inference test is opt-in and, for remote/paid
backends, gated behind confirmation.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from . import models as M
from . import pipeline as P

PRESETS = {
    "simple": "simple response",
    "long_context": "long context",
    "tool-schema-heavy": "tool-schema-heavy",
    "retrieval-heavy": "retrieval-heavy",
    "code_generation": "code generation",
    "custom": "custom",
}


class TestHarness:
    """Owns test runs and history. Keeps at most two selected runs for
    comparison."""

    def __init__(self) -> None:
        self.runs: List[M.TestRun] = []
        self.selected: List[str] = []   # run ids selected for comparison
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"test-{int(time.time())}-{self._counter}-{uuid.uuid4().hex[:6]}"

    def run_dry(self, prompt: str, preset: str = "simple",
                settings_used: str = "active", slimtoken_on: bool = True,
                context_window: int = 156000, max_output_tokens: int = 3431,
                model: str = "unknown", route: str = "cortex-big",
                backend: str = "unknown",
                ) -> M.TestRun:
        """Run an isolated dry-run test. No inference request is sent."""
        run = M.TestRun(
            id=self._new_id(), label=PRESETS.get(preset, preset),
            started_at=time.strftime("%H:%M:%S"),
            model=model, route=route, backend=backend,
            settings_used=settings_used, slimtoken_on=slimtoken_on,
            status="running")
        t0 = time.time()
        try:
            dr = P.dry_run(prompt, context_window=context_window,
                           max_output_tokens=max_output_tokens,
                           preset=preset, dedup=slimtoken_on)
            run.elapsed_s = round(time.time() - t0, 2)
            run.input_tokens = dr.compose.total_tokens
            run.output_tokens = dr.finalize.input_tokens
            run.saved_pct = dr.slim.saved_pct
            run.input_tps = None
            run.output_tps = None
            run.stages = build_pipeline_from_dryrun(dr)
            run.output_preview = f"[dry-run] {prompt[:80]}"
            run.status = "complete"
        except Exception as e:  # pragma: no cover - defensive
            run.status = "failed"
            run.errors.append(str(e))
        self.runs.append(run)
        return run

    def cancel(self, run_id: str) -> None:
        for r in self.runs:
            if r.id == run_id and r.status == "running":
                r.status = "cancelled"
                break

    def clear(self) -> None:
        self.runs.clear()
        self.selected.clear()

    def toggle_select(self, run_id: str) -> None:
        if run_id in self.selected:
            self.selected.remove(run_id)
        else:
            self.selected.append(run_id)
            # Keep at most two selected runs for comparison.
            if len(self.selected) > 2:
                self.selected.pop(0)

    def comparison(self) -> Optional[Dict[str, Any]]:
        """Build a comparison table for the selected runs (max 2)."""
        sel = [r for r in self.runs if r.id in self.selected]
        if len(sel) < 2:
            return None
        a, b = sel[0], sel[1]
        return {
            "a": a, "b": b,
            "rows": [
                ("Input tokens", a.input_tokens, b.input_tokens),
                ("Token reduction", a.saved_pct, b.saved_pct),
                ("Input speed", a.input_tps, b.input_tps),
                ("Output speed", a.output_tps, b.output_tps),
                ("Total elapsed", a.elapsed_s, b.elapsed_s),
            ],
        }


def build_pipeline_from_dryrun(dr: P.DryRunResult) -> List[M.PipelineStage]:
    """Assemble the seven stages from a dry-run result."""
    comp, slim, fin = dr.compose, dr.slim, dr.finalize
    return [
        M.PipelineStage(name="COLLECT", state="complete",
                        detail=f"{comp.total_tokens} input tokens · "
                               f"{len(comp.blocks)} blocks",
                        tokens_in=comp.total_tokens, payload=comp),
        M.PipelineStage(name="COMPOSE", state="complete",
                        detail=f"{comp.total_tokens} tokens · {len(comp.blocks)} blocks · "
                               f"{len(comp.pinned)} pinned · {comp.output_reserved} output reserved",
                        tokens_in=comp.total_tokens, payload=comp),
        M.PipelineStage(name="SLIMTOKEN", state="complete",
                        detail=f"{slim.before_tokens} → {slim.after_tokens} · "
                               f"saved {slim.saved_pct}%",
                        tokens_in=slim.before_tokens, tokens_out=slim.after_tokens,
                        payload=slim),
        M.PipelineStage(name="FINALIZE", state="complete",
                        detail=f"model template applied · schema valid · "
                               f"{fin.input_tokens} input tokens",
                        tokens_in=fin.input_tokens, payload=fin),
        M.PipelineStage(name="PREFILL", state="queued", detail="dry-run — no inference"),
        M.PipelineStage(name="DECODE", state="queued", detail="dry-run — no inference"),
        M.PipelineStage(name="DELIVER", state="queued", detail="dry-run — no inference"),
    ]
