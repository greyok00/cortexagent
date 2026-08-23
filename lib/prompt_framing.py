#!/usr/bin/env python3
"""lib/prompt_framing.py — CANONICAL reframing, sourced from slim token.

This file is a thin compatibility shim over the ONE canonical reframing
engine: ``slimtoken.prompt_reframe`` (pure CPU, deterministic, no LLM). It
exists so existing callers (react_loop, and anything importing
``frame_prompt``) keep working while the actual logic lives in slim token.

This file REPLACES the old drifting copy of the engine, which had grown its
own tiny-model fork (semantic rephrase on :8082, agent-persona pick, memory
hint). Per the consolidation decision that fork is removed — the engine here
is 100% pure slim (sentence-rank shrink), identical to what slim's own MCP
server exposes.

Source resolution (in order):
  1. an installed slimtoken that already ships ``prompt_reframe`` (>= 0.3.6)
  2. the canonical local slim repo ``src`` — fallback so we never depend on
     the site-packages copy having caught up to the repo.

Return shape of frame_prompt: (reframed_prompt, system_prompt, domain).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional, Tuple

# ── Resolve the canonical slim reframe engine ──────────────────────────────
# repo sibling layout: /home/grey/cortexagent  +  /home/grey/slimtoken
# this file: <cortex>/lib/prompt_framing.py  → parents[2] = <home>
_LOCAL_REF = Path(__file__).resolve().parents[2] / "slimtoken" / "src" \
    / "slimtoken" / "prompt_reframe.py"


def _resolve_engine():
    """Import slimtoken.prompt_reframe, preferring the canonical local repo.

    Order:
      1. an installed slimtoken that ships prompt_reframe (>= 0.3.6);
      2. the canonical local repo file loaded standalone via importlib —
         prompt_reframe is pure stdlib, so this never collides with a cached
         older ``slimtoken`` already in sys.modules.
    """
    try:
        from slimtoken import prompt_reframe as pr
        pr.frame_prompt  # confirm the attribute actually exists
        return pr
    except (ImportError, AttributeError):
        if not _LOCAL_REF.is_file():
            raise RuntimeError(
                f"no reframing engine: installed slimtoken lacks prompt_reframe "
                f"and {_LOCAL_REF} is missing")
        spec = importlib.util.spec_from_file_location(
            "slimtoken_prompt_reframe_local", _LOCAL_REF)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod


_pr = _resolve_engine()

# ── Canonical public surface (re-exported) ─────────────────────────────────
classify_domain = _pr.classify_domain
reframe_prompt = _pr.reframe_prompt
shrink_prompt = _pr.shrink_prompt
minify_prompt = _pr.minify_prompt
build_system = _pr.build_system


# ── Compat wrapper (react_loop / callers) ──────────────────────────────────
def frame_prompt(
    prompt: str,
    system_prompt: str = "",
    domain: Optional[str] = None,
    profile_name: Optional[str] = None,
    agent_name: Optional[str] = None,
    shrink_mode: Optional[str] = None,
    progress_cb: Optional[Callable] = None,
) -> Tuple[str, str, str]:
    """Run the full slim pipeline: classify → reframe → shrink → minify →
    build_system. Returns (reframed_prompt, system_prompt, domain).

    ``profile_name`` / ``agent_name`` are accepted for backward-compat but
    ignored — the pure slim engine has no agent profiles (the tiny-model
    agent-pick is gone). ``progress_cb(stage, status)`` fires on each stage so
    existing progress bars keep working; the agent_pick / memory_hint stages
    are emitted as instant no-ops for UI compatibility.
    """
    if not prompt:
        return prompt, system_prompt, "general"

    def _stage(name, status):
        if progress_cb:
            try:
                progress_cb(name, status)
            except Exception:
                pass

    dom = domain or classify_domain(prompt)
    mode = shrink_mode or "balanced"

    _stage("reframe", "running")
    reframed = reframe_prompt(prompt)
    _stage("reframe", "done")

    _stage("agent_pick", "running")   # no-op in pure slim; kept for UI
    _stage("agent_pick", "done")

    _stage("shrink", "running")
    shrunk = shrink_prompt(reframed, mode=mode)
    _stage("shrink", "done")

    _stage("memory_hint", "running")  # no-op in pure slim; kept for UI
    _stage("memory_hint", "done")

    _stage("minify", "running")
    minified = minify_prompt(shrunk)
    _stage("minify", "done")

    sys_prompt = build_system(dom, role="generalist", style="terse")
    final_system = (system_prompt + "\n\n" + sys_prompt) if system_prompt \
        else sys_prompt
    return minified, final_system, dom


# ── CLI (smoke) ─────────────────────────────────────────────────────────────
def main() -> int:
    import sys as _sys
    if len(_sys.argv) > 1:
        refr, sysp, dom = frame_prompt(" ".join(_sys.argv[1:]))
        print(f"Domain: {dom}\nReframed:\n  {refr}\nSystem:\n  {sysp}")
        return 0
    tests = [
        "can you basically just tell me what is the answer please really",
        "Investigate the security posture of this server and check for IOCs",
        "Audit the docs. Remove outdated material. Update the diversion section.",
    ]
    for t in tests:
        r, s, d = frame_prompt(t)
        print(f"  IN : {t!r}\n  DOM: {d}\n  OUT: {r!r}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
