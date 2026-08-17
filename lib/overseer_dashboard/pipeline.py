"""lib/overseer_dashboard/pipeline.py — the observable request pipeline.

Implements the seven stages COLLECT → COMPOSE → SLIMTOKEN → FINALIZE →
PREFILL → DECODE → DELIVER as typed models, plus a **dry-run** engine that
computes Compose + SlimToken token budget/result *without* sending an
inference request.

The dry-run is the testable core: it builds typed blocks, frames them with a
policy, applies protection rules, and runs SlimToken's dedup/compact logic
while preserving pinned content. It never sends content to a provider and
never mutates the active CLI conversation.

Protection policy (from the spec):
  - Pinned/protected by default: system policy, current user request,
    required tool schemas, output contract.
  - High priority: latest turns, selected retrieval, active task instructions.
  - Compressible: older conversation, verbose tool outputs, oversized
    retrieval, repetitive history.
  - Discardable: duplicates, stale/irrelevant context, empty blocks.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import models as M

# Categories that are pinned by default.
_PINNED_CATEGORIES = {"system", "user", "tool_schema", "output_contract"}
# Categories that are high priority by default.
_HIGH_CATEGORIES = {"memory", "retrieval", "attachment"}
# Categories that are compressible by default.
_COMPRESSIBLE_CATEGORIES = {"history", "tool_output", "reasoning", "other"}


# ── Synthetic context generator (test harness) ──────────────────────────────
def synthetic_blocks(prompt: str, preset: str = "simple") -> List[M.TokenComponent]:
    """Build a realistic typed block set for dry-runs and the test harness.

    Never contains real user content beyond the supplied prompt. Token counts
    are deterministic estimates used only for budget math, not for live
    telemetry.
    """
    n = len(prompt)
    blocks: List[M.TokenComponent] = []
    order = 0

    def add(cat, source, tokens, pinned=False, optimizable=True, priority=None):
        nonlocal order
        order += 1
        if priority is None:
            if pinned or cat in _PINNED_CATEGORIES:
                priority = "pinned"
            elif cat in _HIGH_CATEGORIES:
                priority = "high"
            else:
                priority = "compressible"
        blocks.append(M.TokenComponent(
            id=f"{cat}-{order}", category=cat, source=source, tokens=tokens,
            order=order, pinned=pinned or cat in _PINNED_CATEGORIES,
            optimizable=optimizable, priority=priority))

    add("system", "system policy", 1842, pinned=True, optimizable=False)
    add("user", "current user request", max(n // 4, 1), pinned=True, optimizable=False)
    add("tool_schema", "required tool schemas", 2856, pinned=True, optimizable=False)
    add("output_contract", "output contract", 118, pinned=True, optimizable=False)

    if preset == "long_context":
        add("history", "conversation history", 7103, optimizable=True)
        add("history", "older conversation", 4200, optimizable=True)
        add("retrieval", "retrieved sources", 525, priority="high")
        add("tool_output", "tool outputs", 2635, optimizable=True)
    elif preset == "tool-schema-heavy":
        add("tool_schema", "extra tool schemas", 5000, pinned=True, optimizable=False)
        add("tool_output", "tool outputs", 3000, optimizable=True)
        add("history", "conversation history", 1500, optimizable=True)
    elif preset == "retrieval-heavy":
        add("retrieval", "retrieved sources", 4000, priority="high")
        add("retrieval", "retrieved sources (older)", 3000, optimizable=True)
        add("history", "conversation history", 2000, optimizable=True)
    elif preset == "code_generation":
        add("history", "conversation history", 2500, optimizable=True)
        add("tool_output", "file contents", 3500, optimizable=True)
        add("attachment", "code attachments", 1200, priority="high")
    else:  # simple
        add("history", "conversation history", 1200, optimizable=True)
        add("tool_output", "tool outputs", 800, optimizable=True)

    return blocks


# ── Compose ─────────────────────────────────────────────────────────────────
def compose(blocks: List[M.TokenComponent], context_window: int,
            max_output_tokens: int, policy: str = "coding-agent / strict-tools",
            ) -> M.ComposeResult:
    """Frame blocks with a policy, assign priorities/protection, reserve
    output capacity, and validate a usable request exists."""
    errors: List[str] = []
    if not any(b.category == "user" for b in blocks):
        errors.append("no usable user request found")

    pinned = [b for b in blocks if b.pinned or b.priority == "pinned"]
    compressible = [b for b in blocks
                    if not (b.pinned or b.priority == "pinned")
                    and b.priority in ("compressible", "high")]
    discardable = [b for b in blocks if b.priority == "discardable"]

    total = sum(b.tokens for b in blocks)
    input_budget = max(context_window - max_output_tokens, 0)
    valid = not errors and total <= input_budget

    return M.ComposeResult(
        policy=policy,
        input_budget=input_budget,
        output_reserved=max_output_tokens,
        blocks=blocks,
        pinned=pinned,
        compressible=compressible,
        discardable=discardable,
        total_tokens=total,
        valid=valid,
        errors=errors,
    )


# ── SlimToken (dry-run) ──────────────────────────────────────────────────────
def slimtoken(compose: M.ComposeResult, policy: str = "balanced",
              dedup: bool = True, history_compact_threshold: int = 2000,
              retrieval_budget: int = 2000, dry_run: bool = True,
              ) -> M.SlimTokenResult:
    """Optimize eligible blocks while preserving pinned content.

    This is a deterministic dry-run model of SlimToken's behavior. It never
    rewrites pinned/protected blocks, never touches the current user request,
    and never sends anything to a provider.
    """
    before = compose.total_tokens
    actions: List[M.SlimTokenAction] = []
    after = 0
    seen_hashes: set = set()

    # Dedup pass over eligible blocks (content-hash based on id+category).
    deduped_ids: set = set()
    if dedup:
        for b in compose.blocks:
            if b.pinned or not b.optimizable:
                continue
            h = hashlib.md5(f"{b.category}:{b.source}".encode()).hexdigest()
            if h in seen_hashes:
                deduped_ids.add(b.id)
                actions.append(M.SlimTokenAction(
                    block_id=b.id, category=b.category, action="deduplicated",
                    reason="duplicate block removed", tokens_before=b.tokens,
                    tokens_after=0))
            else:
                seen_hashes.add(h)

    for b in compose.blocks:
        if b.pinned or not b.optimizable:
            # Preserved (pinned/protected) — intentionally untouched.
            actions.append(M.SlimTokenAction(
                block_id=b.id, category=b.category, action="preserved",
                reason="pinned/protected — untouched", tokens_before=b.tokens,
                tokens_after=b.tokens))
            after += b.tokens
            continue
        if b.id in deduped_ids:
            continue  # already removed
        if b.category == "history" and b.tokens > history_compact_threshold:
            compacted = int(b.tokens * 0.4)
            actions.append(M.SlimTokenAction(
                block_id=b.id, category=b.category, action="compacted",
                reason="old history compacted", tokens_before=b.tokens,
                tokens_after=compacted))
            after += compacted
        elif b.category == "retrieval" and b.tokens > retrieval_budget:
            trimmed = retrieval_budget
            actions.append(M.SlimTokenAction(
                block_id=b.id, category=b.category, action="summarized",
                reason="oversized retrieval summarized", tokens_before=b.tokens,
                tokens_after=trimmed))
            after += trimmed
        elif b.category == "tool_output" and b.tokens > 2000:
            trimmed = int(b.tokens * 0.5)
            actions.append(M.SlimTokenAction(
                block_id=b.id, category=b.category, action="compacted",
                reason="verbose tool output reduced", tokens_before=b.tokens,
                tokens_after=trimmed))
            after += trimmed
        else:
            actions.append(M.SlimTokenAction(
                block_id=b.id, category=b.category, action="preserved",
                reason="within budget — preserved", tokens_before=b.tokens,
                tokens_after=b.tokens))
            after += b.tokens

    saved = max(before - after, 0)
    saved_pct = round(saved / before * 100, 1) if before else 0.0
    return M.SlimTokenResult(
        enabled=True, policy=policy, before_tokens=before, after_tokens=after,
        saved_tokens=saved, saved_pct=saved_pct, actions=actions, dry_run=dry_run,
    )


# ── Finalize ────────────────────────────────────────────────────────────────
def finalize(compose: M.ComposeResult, slim: M.SlimTokenResult,
             context_window: int, max_output_tokens: int,
             template_applied: bool = True, schema_valid: bool = True,
             gen_params: Optional[Dict[str, Any]] = None,
             ) -> M.FinalizeResult:
    """Validate the optimized request fits and is provider-ready."""
    final_input = slim.after_tokens
    fits = final_input <= max(context_window - max_output_tokens, 0)
    errors: List[str] = []
    if not fits:
        errors.append(
            f"final input {final_input} exceeds budget "
            f"{context_window - max_output_tokens}")
    return M.FinalizeResult(
        valid=fits and not errors, template_applied=template_applied,
        schema_valid=schema_valid, input_tokens=final_input,
        max_output_tokens=max_output_tokens, context_window=context_window,
        fits=fits, generation_params=gen_params or {}, errors=errors,
    )


# ── Full dry-run ────────────────────────────────────────────────────────────
class DryRunResult:
    """Result of a full Compose + SlimToken + Finalize dry-run."""
    def __init__(self, compose: M.ComposeResult, slim: M.SlimTokenResult,
                 finalize: M.FinalizeResult, elapsed_ms: float):
        self.compose = compose
        self.slim = slim
        self.finalize = finalize
        self.elapsed_ms = elapsed_ms


def dry_run(prompt: str, context_window: int = 156000,
            max_output_tokens: int = 3431, policy: str = "balanced",
            preset: str = "simple", dedup: bool = True,
            history_compact_threshold: int = 2000,
            retrieval_budget: int = 2000,
            ) -> DryRunResult:
    """Run Compose + SlimToken + Finalize without sending an inference request.

    Returns a DryRunResult with the full typed breakdown. Never sends content
    to a provider and never modifies the active CLI conversation.
    """
    t0 = time.time()
    blocks = synthetic_blocks(prompt, preset)
    comp = compose(blocks, context_window, max_output_tokens)
    slim = slimtoken(comp, policy=policy, dedup=dedup,
                     history_compact_threshold=history_compact_threshold,
                     retrieval_budget=retrieval_budget, dry_run=True)
    fin = finalize(comp, slim, context_window, max_output_tokens)
    elapsed = (time.time() - t0) * 1000.0
    return DryRunResult(comp, slim, fin, elapsed)


# ── Build the live pipeline from a snapshot ─────────────────────────────────
def build_pipeline(snap: M.RuntimeSnapshot) -> List[M.PipelineStage]:
    """Assemble the seven stages from real telemetry where available.

    Stages without real data are marked ``skipped`` with a "not instrumented"
    detail rather than fabricated numbers.
    """
    inf = snap.inference
    stages: List[M.PipelineStage] = []

    # COLLECT — from token components if instrumented, else not instrumented.
    stages.append(M.PipelineStage(
        name="COLLECT", state="skipped",
        detail="not instrumented — no typed block telemetry",
        tokens_in=inf.input_tokens))

    # COMPOSE — policy framing.
    stages.append(M.PipelineStage(
        name="COMPOSE", state="skipped",
        detail="not instrumented — no compose telemetry"))

    # SLIMTOKEN — from minify stats.
    minify = snap.minify or {}
    if minify.get("runs"):
        stages.append(M.PipelineStage(
            name="SLIMTOKEN", state="complete",
            detail=f"{minify.get('runs')} runs · {minify.get('ratio_pct', 0)}% saved",
            tokens_in=int(minify.get("tokens_in", 0) or 0),
            tokens_out=int(minify.get("tokens_out", 0) or 0)))
    else:
        stages.append(M.PipelineStage(
            name="SLIMTOKEN", state="skipped", detail="no minify runs yet"))

    # FINALIZE.
    stages.append(M.PipelineStage(
        name="FINALIZE", state="skipped",
        detail="not instrumented — no finalize telemetry",
        tokens_in=inf.input_tokens))

    # PREFILL — from input_tps.
    if inf.input_tps is not None:
        stages.append(M.PipelineStage(
            name="PREFILL", state="complete",
            detail=f"{inf.input_tps:.0f} tok/s",
            tokens_in=inf.input_tokens))
    else:
        stages.append(M.PipelineStage(
            name="PREFILL", state="skipped", detail="no prefill telemetry"))

    # DECODE — from output_tps.
    if inf.output_tps is not None:
        stages.append(M.PipelineStage(
            name="DECODE", state="complete",
            detail=f"{inf.output_tps:.1f} tok/s",
            tokens_out=inf.output_tokens))
    else:
        stages.append(M.PipelineStage(
            name="DECODE", state="skipped", detail="no decode telemetry"))

    # DELIVER — from last request status.
    status = inf.last_request_status
    if status:
        stages.append(M.PipelineStage(
            name="DELIVER", state="complete", detail=f"last: {status}",
            tokens_out=inf.output_tokens))
    else:
        stages.append(M.PipelineStage(
            name="DELIVER", state="skipped", detail="no delivery telemetry"))

    return stages


# ── Pathway strip (broader-scale prompt path for the bottom strip) ──────────
def build_pathway(snap: M.RuntimeSnapshot,
                  stages: Optional[List[M.PipelineStage]] = None
                  ) -> Dict[str, Tuple[str, str, Optional[str], Optional[str]]]:
    """Map the 11 pathway nodes to (state, detail, in_text, out_text).

    Stages with no data render as ``("queued", "—", None, None)``. Derived
    nodes (frame_of_ref / memory_check / tool_routing / cost_ledger) read
    from existing snapshot fields so no new pipeline plumbing is required.
    """
    inf = snap.inference
    minify = snap.minify or {}
    if stages is None:
        stages = build_pipeline(snap)

    by_name = {s.name: s for s in stages}

    def _stage(name: str) -> Tuple[str, str, Optional[str], Optional[str]]:
        s = by_name.get(name)
        if s is None:
            return ("queued", "—", None, None)
        in_text = str(s.tokens_in) if s.tokens_in is not None else None
        out_text = str(s.tokens_out) if s.tokens_out is not None else None
        return (s.state, s.detail or "—", in_text, out_text)

    pathway: Dict[str, Tuple[str, str, Optional[str], Optional[str]]] = {}

    # 1. prompt_intake — COLLECT
    pathway["prompt_intake"] = _stage("COLLECT")

    # 2. frame_assemble — COMPOSE
    pathway["frame_assemble"] = _stage("COMPOSE")

    # 3. frame_of_ref — derived from route (ModelIdentity carries no
    # system_profile field; we just show the route itself).
    route = snap.model.route if snap.model else "—"
    pathway["frame_of_ref"] = (
        "complete" if route and route != "—" else "queued",
        f"{route}", None, None,
    )

    # 4. memory_check — derived from minify runs or overseer write check.
    runs = int(minify.get("runs", 0) or 0)
    if runs:
        pathway["memory_check"] = (
            "complete", f"{runs} minify runs", None, None)
    else:
        pathway["memory_check"] = ("queued", "no memory hits", None, None)

    # 5. slimtoken_minify — SLIMTOKEN
    pathway["slimtoken_minify"] = _stage("SLIMTOKEN")

    # 6. tool_routing — derived from inference.active_request / status.
    if inf.active:
        pathway["tool_routing"] = (
            "active", inf.active_request or "routing", None, None)
    else:
        pathway["tool_routing"] = ("skipped", "idle", None, None)

    # 7. context_fit — FINALIZE
    pathway["context_fit"] = _stage("FINALIZE")

    # 8. prefill — PREFILL
    pathway["prefill"] = _stage("PREFILL")

    # 9. decode — DECODE
    pathway["decode"] = _stage("DECODE")

    # 10. stream_out — DELIVER
    pathway["stream_out"] = _stage("DELIVER")

    # 11. cost_ledger — derived total tokens.
    total_in = inf.input_tokens or 0
    total_out = inf.output_tokens or 0
    if total_in or total_out:
        pathway["cost_ledger"] = (
            "complete",
            f"in {total_in} · out {total_out}",
            str(total_in) if total_in else None,
            str(total_out) if total_out else None,
        )
    else:
        pathway["cost_ledger"] = ("queued", "no telemetry", None, None)

    return pathway


# ── Hot-memory last prompts ─────────────────────────────────────────────────
HOT_MEMORY_CANDIDATES = (
    Path.home() / ".config" / "cortexllm" / "memory" / "hot" / "cortexagent.jsonl",
    Path.home() / ".cortexagent" / "memory" / "hot" / "cortexagent.jsonl",
)


def _read_hot_memory_lines() -> List[Dict[str, Any]]:
    """Best-effort read of the cortexagent hot-memory JSONL file."""
    for path in HOT_MEMORY_CANDIDATES:
        try:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as f:
                lines = [ln for ln in f if ln.strip()]
            entries: List[Dict[str, Any]] = []
            for ln in lines[-200:]:  # only tail to keep this cheap
                try:
                    obj = json.loads(ln)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
            return entries
        except Exception:
            continue
    return []


def load_last_prompts(limit: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent ``user``-role prompts from hot memory.

    Each entry: ``{"ts": str, "role": str, "preview": str, "content": str}``.
    Older entries come first if their timestamp is older; we sort by file
    position (which matches write order under O_APPEND). Falls back to an
    empty list if the file is missing or unreadable.
    """
    entries = _read_hot_memory_lines()
    out: List[Dict[str, Any]] = []
    for obj in entries:
        if obj.get("role") != "user":
            continue
        content = str(obj.get("content", "") or "")
        if not content.strip():
            continue
        ts = str(obj.get("timestamp") or obj.get("ts") or "")
        preview = content[:80].replace("\n", " ")
        out.append({"ts": ts, "role": "user", "preview": preview,
                    "content": content})
    return out[-limit:][::-1]  # most recent first
