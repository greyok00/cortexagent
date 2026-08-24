#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional, Tuple




_LOCAL_REF = Path(__file__).resolve().parents[2] / "slimtoken" / "src" \
    / "slimtoken" / "prompt_reframe.py"


def _resolve_engine():

    try:
        from slimtoken import prompt_reframe as pr
        pr.frame_prompt
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


classify_domain = _pr.classify_domain
reframe_prompt = _pr.reframe_prompt
shrink_prompt = _pr.shrink_prompt
minify_prompt = _pr.minify_prompt
build_system = _pr.build_system



def frame_prompt(
    prompt: str,
    system_prompt: str = "",
    domain: Optional[str] = None,
    profile_name: Optional[str] = None,
    agent_name: Optional[str] = None,
    shrink_mode: Optional[str] = None,
    progress_cb: Optional[Callable] = None,
) -> Tuple[str, str, str]:

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

    _stage("agent_pick", "running")
    _stage("agent_pick", "done")

    _stage("shrink", "running")
    shrunk = shrink_prompt(reframed, mode=mode)
    _stage("shrink", "done")

    _stage("memory_hint", "running")
    _stage("memory_hint", "done")

    _stage("minify", "running")
    minified = minify_prompt(shrunk)
    _stage("minify", "done")

    sys_prompt = build_system(dom, role="generalist", style="terse")
    final_system = (system_prompt + "\n\n" + sys_prompt) if system_prompt \
        else sys_prompt
    return minified, final_system, dom



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
