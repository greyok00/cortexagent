from __future__ import annotations

import copy
import re as _re
import threading
from typing import Any, Callable, Dict, Optional

import json as _json

from core.llm import _query_llm, _query_llm_with_tools
from core.state import classify_mode
from model.prompt import SYSTEM_PROMPT

MAX_STEPS = 8
TOOL_TIMEOUT = 120

_metrics_lock = threading.Lock()
_metrics = {"tokens_in": 0, "tokens_kept": 0, "ratio": 0.0,
            "last_in": 0, "last_kept": 0}

_LT = chr(60)
_GT = chr(62)
_SLASH = chr(47)
_OPEN_MARKER = _LT + "function="
_CLOSE_MARKER = _LT + _SLASH + "function" + _GT
_PARAM_OPEN = _LT + "parameter="
_PARAM_CLOSE = _LT + _SLASH + "parameter" + _GT
_JSON_MARKER_OPEN = _LT + "function_call" + _GT
_JSON_MARKER_CLOSE = _LT + _SLASH + "function_call" + _GT

_PAT_JSON_CALL = _re.escape(_JSON_MARKER_OPEN) + r"\s*(\[.*?\]|\{.*?\})\s*" + \
    _re.escape(_JSON_MARKER_CLOSE)
_PAT_BLOCK = _re.escape(_OPEN_MARKER) + r"\s*([^" + _re.escape(_GT) + r"=]*)\s*" + \
    _re.escape(_GT) + r"(.*?)" + _re.escape(_CLOSE_MARKER)
_PAT_PARAM = _re.escape(_PARAM_OPEN) + r"\s*([^" + _re.escape(_GT) + r"=]*)\s*" + \
    _re.escape(_GT) + r"\s*([\s\S]*?)\s*" + _re.escape(_PARAM_CLOSE)


def compression_stats() -> dict:
    with _metrics_lock:
        return dict(_metrics)


def _record_stats(stats) -> None:
    try:
        tin = int(getattr(stats, "tokens_in", 0) or 0)
        tout = int(getattr(stats, "tokens_out", 0) or 0)
        ratio = round(tout / tin, 3) if tin else 0.0
    except Exception:
        tin, tout, ratio = 0, 0, 0.0
    with _metrics_lock:
        _metrics["tokens_in"] += tin
        _metrics["tokens_kept"] += tout
        _metrics["last_in"] = tin
        _metrics["last_kept"] = tout
        _metrics["ratio"] = ratio


def _compress(body: dict) -> dict:
    import sys as _sys
    from pathlib import Path as _Path
    rootdir = _Path(__file__).resolve().parent.parent
    vendor = str(rootdir / "vendor" / "slimtoken" / "src")
    if vendor not in _sys.path:
        _sys.path.insert(0, vendor)
    try:
        import os as _os
        _os.environ.setdefault("SLIMTOKEN_MODE", "code")
        from slimtoken.pipeline import minify_request
        from slimtoken.profiles import build_config
    except Exception:
        return body
    try:
        cfg = build_config()
        out, stats = minify_request(copy.deepcopy(body), cfg)
    except Exception:
        return body
    try:
        _record_stats(stats)
    except Exception:
        pass
    if isinstance(out, dict) and out.get("messages"):
        return out
    return body


def _beautify(text: str) -> str:
    out = text
    try:
        from tools.display_frame import frame_output
        framed, _ = frame_output(out)
        out = framed
    except Exception:
        pass
    try:
        from tools.display_post import process_output
        out, _ = process_output(out, show_code=True)
    except Exception:
        pass
    try:
        from tools.display_beautify import beautify as _beautify_fn
        out = _beautify_fn(out)
    except Exception:
        pass
    return out


def _parse_text_calls(content: str) -> list:
    calls = []
    for m in _re.finditer(_PAT_JSON_CALL, content, _re.S):
        try:
            data = _json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for d in items:
            try:
                fn = d.get("function", d)
                name = fn.get("name", "")
                args = fn.get("arguments", fn.get("input", {}))
                if isinstance(args, str):
                    args = _json.loads(args) if args.strip() else {}
                if name:
                    calls.append({"name": name, "args": args})
            except Exception:
                continue
    for fname, body in _re.findall(_PAT_BLOCK, content, _re.S):
        args = {}
        for m in _re.finditer(_PAT_PARAM, body, _re.S):
            args[m.group(1)] = m.group(2)
        if fname:
            calls.append({"name": fname, "args": args})
    seen = set()
    uniq = []
    for c in calls:
        key = (c["name"], _json.dumps(c["args"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def run(task: Dict, on_event: Optional[Callable] = None) -> Dict[str, Any]:
    prompt = task.get("prompt", "")
    system = task.get("system", "")
    max_steps = int(task.get("max_steps", MAX_STEPS))
    if not prompt or not prompt.strip():
        return {"ok": False, "output": "", "error": "empty prompt"}
    mode = classify_mode(prompt)
    if mode == "direct":
        result = _query_llm(prompt, system=system or SYSTEM_PROMPT,
                            max_tokens=1024)
        if result is None:
            return {"ok": False, "output": "", "error": "model unavailable"}
        return {"ok": True, "output": _beautify(result), "error": ""}

    try:
        from core.wiring import register_all
        register_all()
        from core.registry import list_tools, _executor_tool
    except Exception as e:
        return {"ok": False, "output": "", "error": "registry: %s" % e}

    # GA-12/GA-30 (2026-11-03): check_trust() existed as a decorative control —
    # NOTHING consumed its verdict. Rule now: a tool result flagged "suspicious"
    # places this run() under a trust HOLD; while the hold is on, the write/exec
    # suppress-set below is refused (the model is told to ask the operator).
    # Scoped per run() call — starts clean each task by definition.
    _MUTATING_TOOLS = frozenset((
        "shell", "bash", "files_write", "files_edit", "files_delete", "web_post",
    ))
    trust_hold = False

    sys_prompt = system or (SYSTEM_PROMPT + (
        " Tool list gives name and short description only; parameter names "
        "resolve on execution. Call tools with the arguments you think they "
        "need; a wrong or missing argument returns an error naming the "
        "correct parameter names — retry once with them."))
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]
    steps = []
    for step in range(1, max_steps + 1):
        steps.append({"id": step, "status": "in_progress"})
        comp = _compress({"messages": copy.deepcopy(messages)})
        response = _query_llm_with_tools(
            comp["messages"], list_tools(stub=False), max_tokens=1024,
            timeout=TOOL_TIMEOUT)
        if response is None:
            return {"ok": False, "output": "", "error": "model unavailable"}
        if response["kind"] == "text":
            calls = _parse_text_calls(response["content"])
            if calls:
                response = {"kind": "tool_calls", "calls": calls}
            else:
                return {"ok": True, "output": _beautify(response["content"]),
                        "error": "", "steps": steps}
        calls = response["calls"][:3]
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [
                             {"id": "call%d" % i, "type": "function",
                              "function": {"name": c["name"],
                                           "arguments": (c["args"] if isinstance(c["args"], str) else _json.dumps(c["args"]))}}
                             for i, c in enumerate(calls)]})
        outputs = ""
        for c in calls:
            cname = c["name"]
            if trust_hold and cname in _MUTATING_TOOLS:
                result = {"ok": False, "output": "", "error": (
                    "trust HOLD active: a previous tool result was flagged "
                    "'suspicious' (prompt-injection marker), so %s is refused "
                    "for the rest of this task — report to the operator instead "
                    "of retrying" % cname)}
            else:
                result = _executor_tool(cname, c.get("args") or {}, TOOL_TIMEOUT)
                if result.get("trust") == "suspicious":
                    trust_hold = True
            outputs += "\n<tool_result tool=%s>\n%s\n</tool_result>" % (
                cname, str(result.get("output") or result.get("error", ""))[:8000])
            steps[-1]["tool"] = cname
            if on_event:
                try:
                    on_event({"type": "tool", "name": cname, "result": result})
                except Exception:
                    pass
        messages.append({"role": "tool", "content": outputs.strip()})
    return {"ok": True, "output": "max steps reached", "error": "", "steps": steps}