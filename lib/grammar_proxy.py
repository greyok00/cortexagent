#!/usr/bin/env python3

import json, os, sys, socket, threading, time, errno
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import urllib.request








_DASHBOARD_STEPS = Path.home() / ".cortexagent" / "big_model_steps.json"


def _emit_dashboard_step(body: bytes, elapsed: float) -> None:

    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return

    steps: list = []
    try:
        choices = parsed.get("choices") or []
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            tcs = msg.get("tool_calls") or []
            for i, tc in enumerate(tcs):
                fn = (tc.get("function") or {}).get("name") or f"tool_{i+1}"
                steps.append({"label": f"call {fn}", "status": "done"})
            if not steps and msg.get("content"):

                steps = [{"label": "respond", "status": "done"}]
    except Exception:
        steps = []
    payload = {
        "steps": steps,
        "current": max(len(steps) - 1, 0) if steps else 0,
        "elapsed_s": round(elapsed, 2),
        "updated_at": time.time(),
    }
    try:
        _DASHBOARD_STEPS.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DASHBOARD_STEPS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(_DASHBOARD_STEPS)
    except Exception:
        pass

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from lib import control







_ROUTING_STATE = Path.home() / ".cortexagent" / "routing_state.json"
_ROUTER = None
_last_routing_key = None


def _get_router():

    global _ROUTER
    if _ROUTER is None:
        try:
            from lib.cortex_routing import CortexRouter
            _ROUTER = CortexRouter()
        except Exception as e:
            print(f"[proxy] router unavailable: {e}", file=sys.stderr)
            _ROUTER = False
    return _ROUTER or None


def _emit_routing() -> None:

    global _last_routing_key
    router = _get_router()
    if router is None:
        return
    try:
        state = {
            "route": "big",
            "model": router.model,
            "base_url": router.base_url,
            "router_mode": router.router_mode,
            "toolproxy_available": router._toolproxy_available,
            "updated_at": time.time(),
        }
        key = (state["route"], state["model"], state["router_mode"])
        if key == _last_routing_key:
            return
        _last_routing_key = key
        _ROUTING_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ROUTING_STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(_ROUTING_STATE)

        try:
            from lib.session_bridge import SessionBridge
            SessionBridge().write("proxy", {
                "id": f"rte-{int(time.time()*1000)}",
                "type": "routing",
                "username": "Router",
                "content": f"route={state['route']} model={state['model']} mode={state['router_mode']}",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "route": state["route"],
                "model": state["model"],
                "router_mode": state["router_mode"],
            })
        except Exception:
            pass
    except Exception as e:
        print(f"[proxy] routing emit failed: {e}", file=sys.stderr)







try:
    from slimtoken.pipeline import minify_request, MinifyConfig
    from slimtoken.tokencount import count_messages, count_system, count_tools
    from slimtoken.token_budget import enforce_budget
    _MINIFY_BACKEND = "slimtoken"
    _MINIFY_OK = True
except Exception as _e:  # pragma: no cover — slimtoken is required
    _MINIFY_OK = False
    print(f"[proxy] slimtoken unavailable (continuing without): {_e}",
          file=sys.stderr)


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


try:
    from lib.config import CFG as _CFG
    _CONTEXT_WINDOW = int(_CFG.big_ctx)
except Exception:
    _CONTEXT_WINDOW = int(os.environ.get("CORTEXAGENT_CONTEXT_WINDOW", "131072") or 131072)
_COMPLETION_RESERVE = int(os.environ.get("CORTEXAGENT_COMPLETION_RESERVE", "16384") or 16384)
_TOKENIZER_MARGIN = int(os.environ.get("CORTEXAGENT_TOKENIZER_MARGIN", "8192") or 8192)
# 2026-09-05: the window is the ONLY hard cap llama-server enforces. Minify's
# target must sit well below it — window - completion reserve (16384) - drift
# margin (8192) ≈ 81% — so autocompact has room and cl100k-vs-Qwen tokenizer
# drift can't tip a "fits" request over. _HARD_CEILING is the forward gate.
_MINIFY_BUDGET = max(1024, _CONTEXT_WINDOW - _COMPLETION_RESERVE - _TOKENIZER_MARGIN)
_HARD_CEILING = max(_MINIFY_BUDGET + 1, _CONTEXT_WINDOW - _TOKENIZER_MARGIN)


def _build_minify_cfg():
    if not _MINIFY_OK or not _bool_env("CORTEXAGENT_MINIFY", True):
        return None
    stages = set()
    if _bool_env("CORTEXAGENT_MINIFY_TOOLS", True):
        stages.add("tools")
    if _bool_env("CORTEXAGENT_MINIFY_SYSTEM", True):
        stages.add("system")
    if _bool_env("CORTEXAGENT_MINIFY_MESSAGES", True):
        stages.add("messages")

        stages.update(("dedup", "distill"))
    skip = {s.strip() for s in os.environ.get(
        "CORTEXAGENT_MINIFY_TOOL_SKIP", "").split(",") if s.strip()}




    _default_budget = _MINIFY_BUDGET if _MINIFY_OK else 0
    try:
        budget = int(os.environ.get("CORTEXAGENT_MINIFY_BUDGET", "") or _default_budget)
    except ValueError:
        budget = _default_budget
    try:
        keep_last = int(os.environ.get("CORTEXAGENT_MINIFY_KEEP_LAST", "8") or 8)
    except ValueError:
        keep_last = 8
    kw = dict(
        token_budget=budget,
        enabled_stages=stages,
        tool_skip=skip,
        keep_last=keep_last,
        dedup_min_chars=int(os.environ.get(
            "CORTEXAGENT_MINIFY_DEDUP_MIN", "200") or 200),
        distill_max_chars=int(os.environ.get(
            "CORTEXAGENT_MINIFY_DISTILL_MAX", "240") or 240),
        tool_compress=_bool_env("CORTEXAGENT_MINIFY_TOOL_COMPRESS", True),
        minify_dom=_bool_env("CORTEXAGENT_MINIFY_DOM", False),
    )
    return MinifyConfig(**kw)


_MINIFY_CFG = _build_minify_cfg()
_MINIFY_CHUNKED = _bool_env("CORTEXAGENT_MINIFY_CHUNKED", True)
_MINIFY_RESPONSE = _bool_env("CORTEXAGENT_MINIFY_RESPONSE", True)







_TOOL_RESULT_MAX = int(os.environ.get("CORTEXAGENT_TOOL_RESULT_MAX", "50000") or 50000)
# 2026-09-06 root-cause fix: Qwen3.6 reasoning (thinking) burns the whole
# max_completion_tokens budget, so content comes back EMPTY with
# finish_reason="length" -> TUI shows "Response was truncated before
# completion." -> retry loop (+2 msgs/request) -> context balloon -> compaction
# -> "Cannot continue from message role: assistant". Cap thinking so content
# always has at least this many tokens of room.
_MIN_CONTENT_TOKENS = int(os.environ.get("CORTEXAGENT_MIN_CONTENT_TOKENS", "4096") or 4096)


def _trunc_marker(removed: int) -> str:
    return f"\n...[truncated {removed} chars by cortexagent]"


def _cap_text_blocks(blocks: list, max_chars: int) -> None:
    total = sum(len(x.get("text", "")) for x in blocks if isinstance(x, dict))
    if total <= max_chars:
        return
    budget = max_chars
    for blk in blocks:
        if not isinstance(blk, dict) or blk.get("type") != "text":
            continue
        t = blk.get("text", "")
        if len(t) <= budget:
            budget -= len(t)
        else:
            blk["text"] = t[:budget] + _trunc_marker(len(t) - budget)
            budget = 0


def _cap_tool_results(parsed, max_chars: int):
    # 2026-09-05 root-cause fix: the old body only matched Anthropic
    # type:"tool_result" content blocks, but cortexagent speaks
    # openai-completions — tool results are role:"tool" messages with plain
    # string content. The cap never fired there, so multi-MB tool dumps rode
    # through, keep_last=8 protected them from slimtoken's prune, and
    # llama-server 400'd (observed: minify in=639976 → out=482233 tok).
    if not isinstance(parsed, dict):
        return parsed
    for msg in parsed.get("messages", []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if msg.get("role") == "tool":
            if isinstance(content, str) and len(content) > max_chars:
                msg["content"] = content[:max_chars] + _trunc_marker(len(content) - max_chars)
            elif isinstance(content, list):
                _cap_text_blocks(content, max_chars)
            continue
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            c = item.get("content")
            if isinstance(c, str):
                if len(c) > max_chars:
                    item["content"] = c[:max_chars] + _trunc_marker(len(c) - max_chars)
            elif isinstance(c, list):
                _cap_text_blocks(c, max_chars)
    return parsed


def _cap_thinking(parsed):
    """Guarantee content always has room when thinking is enabled.

    llama-server accepts a per-request ``reasoning_budget_tokens`` cap (the
    server flag --reasoning-budget, settable per request). When the TUI sends
    enable_thinking + max_completion_tokens, cap thinking so the completion
    budget can never be exhausted by reasoning_content alone — otherwise
    content returns empty (finish_reason="length") and the TUI retries forever.
    """
    if not isinstance(parsed, dict):
        return parsed
    if not parsed.get("enable_thinking"):
        return parsed
    mct = parsed.get("max_completion_tokens")
    if mct is None:
        return parsed  # no budget to exhaust -> no empty-content risk
    budget = max(0, int(mct) - _MIN_CONTENT_TOKENS)
    parsed["reasoning_budget_tokens"] = budget
    return parsed


def _hard_cap_prompt(parsed: dict) -> tuple[dict, str | None]:
    """Aggressively truncate the user message so the body always fits.

    Runs BEFORE `_context_gate()` — it is the first line of defence.  It:

    1. Reserves room for system prompt, tool definitions, and the minimal
       message envelope (role, content key).  Budget is computed with the
       real cl100k tokenizer.
    2. Finds the LATEST user message (the one being added now) and truncates
       its content to whatever character budget remains.
    3. Prepends a CLEAR NOTICE so the assistant knows the prompt was cut:
         "[TRUNCATED: your prompt was too large for this context window."
         "Only the end fit. Rework into smaller chunks.]\n\n"
    4. Returns ``(modified_parsed, notice)``.  ``notice`` is the human-
       readable string prepended (or None if nothing was truncated).

    If even a bare 10-char user prompt can't fit after system+tools, the
    function returns the original parsed dict with a NOTICE that tells the
    user to split their request.  The caller should then send a friendly
    error instead of a 400 that triggers auto-compaction.

    Parameters
    ----------
    parsed : dict
        The request body (same shape as what reaches _context_gate).

    Returns
    -------
    (parsed, notice)
        Modified parsed dict + human-readable notice string (or None).
    """
    if not isinstance(parsed, dict):
        return parsed, None

    # ── 1. Measure what system + tools + envelope already consume ─────
    system_tok = count_system(parsed.get("system"))
    tools_tok  = count_tools(parsed.get("tools"))
    # Envelope overhead: role + content wrapper (JSON structure, keys, etc.)
    # Measured empirically: ~80 chars for a 10-char user msg = 8 tok
    ENVELOPE_TOK = 80

    reserved_tok = system_tok + tools_tok + ENVELOPE_TOK
    # How many tokens of user text can we fit?
    # Reserve 1 token for output, plus a 1% safety margin so the total
    # (system + tools + user_envelope + user_text + output) stays strictly
    # under _HARD_CEILING even with cl100k-vs-Qwen drift.
    # 3 chars/token is conservative but safe; 4 chars/tok overestimates
    # for dense unique text and caused the overflow above.
    user_budget_tok = max(1, int((_HARD_CEILING - reserved_tok - 1) * 0.99))
    user_budget_chars = user_budget_tok * 3  # 3 chars/tok — conservative

    # ── 2. Find latest user message and check size ────────────────────
    msgs = parsed.get("messages")
    if not isinstance(msgs, list):
        return parsed, None

    # Walk backwards to find the latest user message
    target_idx = -1
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if isinstance(m, dict) and m.get("role") == "user":
            target_idx = i
            break

    if target_idx < 0:
        return parsed, None

    user_msg = msgs[target_idx]
    content = user_msg.get("content", "")
    if not isinstance(content, str):
        return parsed, None

    char_len = len(content)
    if char_len <= user_budget_chars:
        return parsed, None  # already fits

    # ── 3. Truncate ───────────────────────────────────────────────────
    notice = (
        "[TRUNCATED: your prompt was too large for this context window. "
        "Only the tail (last ~4000 chars) fit — the head was dropped. "
        "Rework your request into smaller chunks for complete processing.\n\n"
    )
    # Keep the tail; budget = notice + tail
    tail_budget = max(200, user_budget_chars - len(notice))
    truncated = content[-tail_budget:]
    new_content = notice + truncated
    msgs[target_idx] = {**user_msg, "content": new_content}

    return parsed, None  # notice is already in the content


def _context_gate(parsed):
    """Post-minify hard gate — never forward a prompt llama-server must 400.

    Counts the final body with slimtoken's cl100k tokenizer (real count, not
    chars) plus a surcharge for OpenAI ``tool_calls`` arguments, which
    count_message() does not inspect. Over _HARD_CEILING: one emergency
    enforce_budget pass with keep_last=1 (drop oldest history, protect only
    the newest message); still over → return ok=False and the caller sends a
    llama-server-shaped overflow 400 so the client's isContextOverflow()
    recovery compacts and retries instead of stalling.

    Returns
    -------
    (body, ok, total_tokens, is_overcapacity)
        ``is_overcapacity`` is True when system+tools alone exceed the
        ceiling (hard cap cannot help).  The caller should use
        ``_respond_overcapacity`` instead of ``_respond_overflow``.
    """
    if not _MINIFY_OK or not isinstance(parsed, dict):
        return parsed, True, 0, False
    msgs = parsed.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return parsed, True, 0, False

    def _total(body):
        n = (count_system(body.get("system")) + count_tools(body.get("tools"))
             + count_messages(body.get("messages", []))[0])
        for m in body.get("messages", []):
            tcs = m.get("tool_calls") if isinstance(m, dict) else None
            if tcs:
                try:
                    n += max(1, len(json.dumps(tcs)) // 4)
                except Exception:
                    n += 1
        return n

    total = _total(parsed)
    if total <= _HARD_CEILING:
        return parsed, True, total, False
    try:
        trimmed = enforce_budget(parsed, _HARD_CEILING, keep_last=1)
        t2 = _total(trimmed)
        if t2 <= _HARD_CEILING:
            print(f"[proxy] gate: emergency trim {total}→{t2} tok "
                  f"(keep_last=1, was over {_HARD_CEILING})", file=sys.stderr)
            return trimmed, True, t2, False
        # ── Hard cap fallback: truncate user message to fit ─────────────
        print(
            f"[proxy] gate: OVER {_HARD_CEILING} tok — applying hard cap "
            f"(trim user msg)",
            file=sys.stderr,
        )
        capped, _ = _hard_cap_prompt(parsed)
        t3 = _total(capped)
        if t3 <= _HARD_CEILING:
            print(
                f"[proxy] gate: hard cap trimmed to {t3} tok (fits)",
                file=sys.stderr,
            )
            return capped, True, t3, False
        # Even the truncated prompt won't fit — system+tools alone are
        # too large.  Return a CLEAR rejection that does NOT look like a
        # server-overflow (so isContextOverflow stays False and no
        # auto-compaction loop fires).
        print(
            f"[proxy] gate: HARD OVER {t3} tok > {_HARD_CEILING} — "
            f"clear rejection (system+tools too large)",
            file=sys.stderr,
        )
        return parsed, False, t3, True  # is_overcapacity = True
    except Exception as e:
        # counting/enforce failed — forward as before rather than block traffic
        print(f"[proxy] gate bypassed: {e}", file=sys.stderr)
        return parsed, True, total, False









_REFRAISE = _bool_env("CORTEXAGENT_REFRAISE", True)
_REFRAISE_SYSTEM = _bool_env("CORTEXAGENT_REFRAISE_SYSTEM", False)


def _frame_fn():

    try:
        from lib import prompt_framing
        return prompt_framing.frame_prompt
    except ImportError:
        import prompt_framing
        return prompt_framing.frame_prompt


def _append_system(msgs: list, add_sys: str) -> None:

    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "system":
            cur = m.get("content")
            m["content"] = (cur + "\n\n" + add_sys) if isinstance(cur, str) \
                else add_sys
            return
    msgs.insert(0, {"role": "system", "content": add_sys})


def _reframe_user_prompt(parsed: dict) -> tuple[dict, int]:

    if not _REFRAISE:
        return parsed, 0
    msgs = parsed.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return parsed, 0
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user" or not isinstance(m.get("content"), str):
            continue
        content = m["content"].strip()
        if not content:
            continue
        try:
            reframed, framed_sys, _dom = _frame_fn()(content)
        except Exception as e:
            print(f"[proxy] reframe skipped: {e}", file=sys.stderr)
            return parsed, 0
        if not reframed or reframed == content:
            return parsed, 0
        msgs[i] = {**m, "content": reframed}
        if _REFRAISE_SYSTEM and framed_sys:
            _append_system(msgs, framed_sys)
        saved = len(content) - len(reframed)
        print(f"[proxy] reframed user prompt {len(content)}→{len(reframed)} chars "
              f"(-{saved})", file=sys.stderr)
        return parsed, saved
    return parsed, 0







_FILLER_PATTERNS = (
    "Sure!\n", "Sure!\n\n", "Sure, ", "Sure.\n",
    "Here is the code:\n", "Here is the code:\n\n",
    "Here is your code:\n", "Here is your code:\n\n",
    "Let me know if you need anything else.\n",
    "Let me know if you have any questions.\n",
    "I hope this helps!\n", "I hope this helps.\n",
    "Feel free to ask if you have any questions.\n",
)


def minify_response(body: bytes) -> bytes:

    if not _MINIFY_RESPONSE or not body:
        return body
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return body

    out_lines = []
    changed = False
    for line in text.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith("data: ") and stripped != "data: [DONE]"):
            out_lines.append(line)
            continue
        payload = stripped[6:]
        try:
            obj = json.loads(payload)
        except Exception:
            out_lines.append(line)
            continue

        modified = False
        try:
            choices = obj.get("choices") or []
            for ch in choices:
                delta = ch.get("delta") or {}
                msg = ch.get("message") or {}
                c = delta.get("content")
                if not c:
                    c = msg.get("content")
                if isinstance(c, str):
                    new = c


                    while True:
                        hit = False
                        for pat in _FILLER_PATTERNS:
                            if new.startswith(pat):
                                new = new[len(pat):]
                                hit = True
                                changed = True
                                break
                        if not hit:
                            break
                    if new != c:
                        modified = True
                        if "delta" in ch:
                            ch["delta"]["content"] = new
                        else:
                            ch["message"]["content"] = new
        except Exception:
            pass
        if modified:
            out_lines.append("data: " + json.dumps(obj, ensure_ascii=False))
        else:
            out_lines.append(line)
    if not changed:
        return body
    return ("\n".join(out_lines)).encode("utf-8")


_token_lock = threading.Lock()
_token_metrics = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "requests": 0,
    "total_time_s": 0.0,
    "started_at": datetime.now().isoformat(),
    "current_tok_s": 0.0,
    "current_in_tps": 0.0,
    "current_out_tps": 0.0,
    "avg_tok_s": 0.0,
    "avg_in_tps": 0.0,
    "avg_out_tps": 0.0,
    "last_request_ts": 0.0,
}


def _record_tokens(prompt_tokens: int, completion_tokens: int, elapsed: float):
    with _token_lock:
        _token_metrics["prompt_tokens"] += prompt_tokens
        _token_metrics["completion_tokens"] += completion_tokens
        _token_metrics["total_tokens"] += prompt_tokens + completion_tokens
        _token_metrics["requests"] += 1
        _token_metrics["total_time_s"] += elapsed
        _token_metrics["last_request_ts"] = time.time()
        if elapsed > 0 and completion_tokens > 0:
            out_tps = completion_tokens / elapsed
            _token_metrics["current_tok_s"] = round(out_tps, 1)
            _token_metrics["current_out_tps"] = round(out_tps, 1)
            in_tps = prompt_tokens / elapsed if elapsed > 0 else 0.0
            _token_metrics["current_in_tps"] = round(in_tps, 1)
        if _token_metrics["total_time_s"] > 0 and _token_metrics["completion_tokens"] > 0:
            avg_out = _token_metrics["completion_tokens"] / _token_metrics["total_time_s"]
            _token_metrics["avg_tok_s"] = round(avg_out, 1)
            _token_metrics["avg_out_tps"] = round(avg_out, 1)
            avg_in = _token_metrics["prompt_tokens"] / _token_metrics["total_time_s"]
            _token_metrics["avg_in_tps"] = round(avg_in, 1)








_session_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}
_SESSION_TTL = 3600.0


def _register_session(hdr: Dict[str, str], kind: str = "unknown") -> str:

    sid = (hdr.get("X-CortexAgent-Session")
           or hdr.get("x-cortexagent-session")
           or "").strip()
    if not sid:
        return ""
    origin = (hdr.get("X-CortexAgent-Origin")
              or hdr.get("x-cortexagent-origin")
              or "").strip().lower() or kind
    now = time.time()
    with _session_lock:
        _sessions[sid] = {"origin": origin, "kind": kind, "ts": now}


        if len(_sessions) > 64:
            cutoff = now - _SESSION_TTL
            for k in list(_sessions.keys()):
                if _sessions[k].get("ts", 0) < cutoff:
                    _sessions.pop(k, None)
    return sid


def _snapshot_sessions() -> Dict[str, Dict[str, Any]]:

    with _session_lock:
        return {k: dict(v) for k, v in _sessions.items()}














_minify_lock = threading.Lock()
_minify_stats = {
    "runs": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "tokens_saved": 0,
    "ratio_pct": 0.0,
    "last_run_ts": 0.0,
    "last_saved_pct": 0.0,
    "history_60s": [],
    "errors": 0,
}
_MINIFY_STATS_FILE = Path.home() / ".cortexagent" / "minify_stats.json"
_MINIFY_HIST_CAP = 60


def _load_minify_stats() -> None:

    try:
        with _MINIFY_STATS_FILE.open(encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            with _minify_lock:
                for k in _minify_stats:
                    if k in d:
                        _minify_stats[k] = d[k]
    except Exception:
        pass


def _record_minify(mstats, reframe_saved_chars: int = 0) -> None:

    try:
        tin = int(getattr(mstats, "tokens_in", 0) or 0)
        tout = int(getattr(mstats, "tokens_out", 0) or 0)
        reframe_tok = max(int(reframe_saved_chars) // 4, 0)
        orig_in = tin + reframe_tok
        if orig_in <= 0:
            return
        saved = max(orig_in - tout, 0)
        saved_pct = round(saved / orig_in * 100, 1) if orig_in else 0.0
        now = time.time()
        with _minify_lock:
            _minify_stats["runs"] += 1
            _minify_stats["tokens_in"] += orig_in
            _minify_stats["tokens_out"] += tout
            _minify_stats["tokens_saved"] += saved
            if _minify_stats["tokens_in"] > 0:
                _minify_stats["ratio_pct"] = round(
                    _minify_stats["tokens_saved"] / _minify_stats["tokens_in"] * 100, 1
                )
            _minify_stats["last_run_ts"] = now
            _minify_stats["last_saved_pct"] = saved_pct
            hist = _minify_stats["history_60s"]
            hist.append((now, saved_pct))

            cutoff = now - 60.0
            if len(hist) > _MINIFY_HIST_CAP:
                hist[:] = [(t, v) for (t, v) in hist if t >= cutoff][-_MINIFY_HIST_CAP:]
            errs = getattr(mstats, "errors", None) or []
            _minify_stats["errors"] += len(errs) if isinstance(errs, (list, tuple)) else 0

        try:
            _MINIFY_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _MINIFY_STATS_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(dict(_minify_stats), default=str))
            tmp.replace(_MINIFY_STATS_FILE)
        except Exception:
            pass
    except Exception:
        pass


def _get_minify_snapshot() -> Dict[str, Any]:

    try:
        with _MINIFY_STATS_FILE.open(encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass

    with _minify_lock:
        return dict(_minify_stats)






_VRAM_TTL = 3.0
_vram_cache = {"ts": 0.0, "used": None, "total": None}


def _vram_mib():

    now = time.time()
    if now - _vram_cache["ts"] < _VRAM_TTL:
        return _vram_cache["used"], _vram_cache["total"]
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().split(", ")
        used, total = int(out[0]), int(out[1])
        _vram_cache.update(ts=now, used=used, total=total)
        return used, total
    except Exception:
        _vram_cache["ts"] = now
        return _vram_cache["used"], _vram_cache["total"]


def _get_metrics() -> str:
    with _token_lock:
        m = dict(_token_metrics)
    used, total = _vram_mib()
    if used is not None:
        m["vram_used_mib"] = used
        m["vram_total_mib"] = total
    with _minify_lock:
        m["minify"] = dict(_minify_stats)
    m["sessions"] = _snapshot_sessions()
    return json.dumps(m, indent=2)



_DUMP = os.environ.get("CORTEXAGENT_PROXY_DUMP", "")


def _has_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def _diag(method, path, cl, chunked, body_len, parsed, parse_err):
    keys = list(parsed.keys()) if isinstance(parsed, dict) else None
    ntools = len(parsed.get("tools", [])) if isinstance(parsed, dict) else None
    has_grammar = _has_key(parsed, "grammar") if parsed is not None else None
    has_rf = ("response_format" in parsed) if isinstance(parsed, dict) else None
    nmsgs = len(parsed.get("messages", [])) if isinstance(parsed, dict) else None
    print(f"[proxy] DIAG method={method} path={path} cl={cl} chunked={chunked} "
          f"body={body_len} keys={keys} ntools={ntools} nmsgs={nmsgs} "
          f"grammar_present={has_grammar} response_format={has_rf} parse_err={parse_err}",
          file=sys.stderr)
    if parsed is not None and _DUMP:
        try:
            with open(_DUMP, "w") as f:
                f.write(json.dumps(parsed)[:400000])
        except Exception as e:
            print(f"[proxy] DIAG dump failed: {e}", file=sys.stderr)


def pipe(src, dst, stop, resp_buf=None):
    src.settimeout(0.3)
    while not stop.is_set():
        try:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            if resp_buf is not None:
                resp_buf.append(data)
        except socket.timeout:
            continue
        except OSError:
            break


def _dechunk(data: bytes):

    out = []
    i = 0
    n = len(data)
    while True:
        crlf = data.find(b"\r\n", i)
        if crlf < 0:
            return None
        size_field = data[i:crlf].split(b";")[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError:
            return None
        i = crlf + 2
        if size == 0:
            break
        if i + size + 2 > n:
            return None
        out.append(data[i:i + size])
        i += size + 2
    return b"".join(out)


class ProxyHandler:
    def __init__(self, conn, addr, target):
        self.conn = conn
        self.addr = addr
        self.target = target


    def _target_healthy(self, timeout=2):
        try:
            h, p = self.target
            req = urllib.request.Request(f"http://{h}:{p}/health", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _touch_activity(self):


        try:
            control.send_request("activity", timeout=2)
        except Exception:
            pass

    def _ensure_target(self):


        if self._target_healthy(timeout=2):
            return True
        print(f"[proxy] target {self.target} down — requesting reload...", file=sys.stderr)
        try:
            control.send_request("load", which="big", timeout=300)
        except Exception as e:
            print(f"[proxy] reload request failed (daemon absent?): {e}", file=sys.stderr)
        deadline = time.time() + 300
        while time.time() < deadline:
            if self._target_healthy(timeout=2):
                print("[proxy] target back up — forwarding", file=sys.stderr)
                return True
            time.sleep(1)
        print("[proxy] target still down after reload — returning 503", file=sys.stderr)
        return False

    def _connect_with_reload(self, timeout: float = 90):

        for attempt in (1, 2):
            dst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            dst.settimeout(timeout)
            try:
                dst.connect(self.target)
                return dst
            except Exception as e:
                dst.close()
                if attempt == 1:
                    print(f"[proxy] connect error: {e} — reloading target...", file=sys.stderr)
                    if not self._ensure_target():
                        return None
                else:
                    print(f"[proxy] connect error after reload: {e}", file=sys.stderr)
                    return None
        return None

    def _respond_502(self):
        body = b'{"error":"bad gateway - backend connection failed"}'
        resp = ("HTTP/1.1 502 Bad Gateway\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

    def _respond_503(self):
        body = b'{"error":"model unavailable"}'
        resp = ("HTTP/1.1 503 Service Unavailable\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

    def _respond_overflow(self, n_tokens: int):
        # llama-server-shaped overflow 400 — the body text matches the
        # client's OVERFLOW_PATTERNS (/exceeds the available context size/i)
        # so its existing recovery path compacts and retries.
        # Used ONLY when the body itself is over the ceiling (not when
        # _hard_cap_prompt already fixed it).
        body = json.dumps({"error": {
            "message": f"request ({n_tokens} tokens) exceeds the available "
                       f"context size ({_CONTEXT_WINDOW} tokens) [cortexagent gate]",
            "type": "server_error",
            "code": 400,
        }}).encode()
        resp = ("HTTP/1.1 400 Bad Request\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

    def _respond_overcapacity(self, n_tokens: int, truncated_chars: int):
        """Clear over-capacity rejection.

        This response does NOT match the client's OVERFLOW_PATTERNS, so
        isContextOverflow() stays False and NO auto-compaction loop fires.
        Instead the assistant sees the error text directly.
        """
        notice = (
            f"Over capacity: the full prompt ({n_tokens} estimated tokens) "
            f"cannot fit in the {_CONTEXT_WINDOW}-token window even after "
            f"aggressive truncation. Only the last ~{truncated_chars:,} chars "
            f"of your message can be processed. Rework your request into "
            f"smaller chunks for complete processing."
        )
        body = json.dumps({"error": {
            "message": notice,
            "type": "over_capacity",
            "code": 429,
            "hint": "split your request into smaller pieces",
        }}).encode()
        resp = ("HTTP/1.1 429 Too Many Requests\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        try:
            self.conn.sendall(resp)
        except Exception:
            pass

    def handle(self):
        try:
            head_bytes, body = self._read_request()
            if not head_bytes:
                return
            self._forward(head_bytes, body)

            _emit_routing()
        except Exception as e:
            print(f"[proxy] handle error: {e}", file=sys.stderr)
        finally:
            try:
                self.conn.close()
            except Exception:
                pass

    def _read_request(self):

        self.conn.settimeout(5)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                chunk = self.conn.recv(65536)
                if not chunk:
                    return None, b""
                buf += chunk
                if len(buf) > (1 << 20):
                    return None, b""
        except socket.timeout:
            return None, b""
        head_bytes, body = buf.split(b"\r\n\r\n", 1)
        return head_bytes, body

    def _forward(self, head_bytes, body):
        headers_text = head_bytes.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        parts = lines[0].split(" ", 2)
        if len(parts) < 2:
            return
        method = parts[0].upper()
        path = parts[1] if len(parts) > 1 else "/"


        if method == "GET" and len(parts) > 1 and parts[1] == "/metrics":
            resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(_get_metrics())}\r\n\r\n{_get_metrics()}"
            try:
                self.conn.sendall(resp.encode())
            except Exception:
                pass
            return







        if method == "GET":
            if not self._target_healthy(timeout=2):
                if path == "/health":
                    self._respond_502()
                else:
                    self._respond_503()
                return


        order, hdr, orig = [], {}, {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            raw = k.strip()
            k = raw.lower()
            order.append(k)
            hdr[k] = v.strip()
            orig[k] = raw

        if method == "POST":






            try:
                _register_session(hdr, kind="http")
            except Exception:
                pass
            if not self._ensure_target():
                self._respond_503()
                return
            self._touch_activity()

            if "100-continue" in hdr.get("expect", "").lower():
                try:
                    self.conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                except Exception:
                    pass

            te = hdr.get("transfer-encoding", "").lower()
            cl = hdr.get("content-length")
            is_chunked = "chunked" in te
            if is_chunked and _MINIFY_CFG is not None and _MINIFY_CHUNKED:
                _diag(method, parts[1] if len(parts) > 1 else "?",
                      cl, True, len(body), None,
                      "chunked → buffer+minify (raw fallback on parse fail)")
                self._forward_chunked(head_bytes, body)
                return
            if is_chunked:




                _diag(method, parts[1] if len(parts) > 1 else "?",
                      cl, True, len(body), None,
                      "chunked → dechunk+grammar-strip only")
                self._forward_chunked_strip_only(head_bytes, body)
                return
            if cl is None:
                _diag(method, parts[1] if len(parts) > 1 else "?",
                      cl, True, len(body), None,
                      "raw/no-strip (no content-length)")
                self._forward_raw(head_bytes, body)
                return

            cl = int(cl)
            while len(body) < cl:
                chunk = self.conn.recv(min(65536, cl - len(body)))
                if not chunk:
                    break
                body += chunk

            parse_err = None
            parsed = None
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    if "grammar" in parsed:
                        del parsed["grammar"]
                    parsed = _cap_tool_results(parsed, _TOOL_RESULT_MAX)
                    parsed, reframe_saved = _reframe_user_prompt(parsed)
                    if _MINIFY_CFG is not None:
                        parsed, mstats = minify_request(parsed, _MINIFY_CFG)
                        print(f"[proxy] minify: {mstats.summary()}", file=sys.stderr)
                        _record_minify(mstats, reframe_saved)
                    parsed = _cap_thinking(parsed)
                    # Hard cap: aggressively truncate user message so it
                    # always fits.  Runs BEFORE _context_gate so the gate
                    # usually sees a body that already fits.
                    parsed, _ = _hard_cap_prompt(parsed)
                    parsed, gate_ok, gate_total, is_overcapacity = _context_gate(parsed)
                    if not gate_ok:
                        if is_overcapacity:
                            self._respond_overcapacity(gate_total, len(parsed.get("messages", [{}])[-1].get("content", "") or "") // 4)
                            _diag(method, parts[1] if len(parts) > 1 else "?",
                                  cl, False, 0, parsed, "gate-overcapacity")
                        else:
                            self._respond_overflow(gate_total)
                            _diag(method, parts[1] if len(parts) > 1 else "?",
                                  cl, False, 0, parsed, "gate-overflow-400")
                        return
                body = json.dumps(parsed).encode()
            except Exception as e:
                parse_err = str(e)
                print(f"[proxy] strip skipped: {e}", file=sys.stderr)
            _diag(method, parts[1] if len(parts) > 1 else "?",
                  cl, "chunked" in te, len(body), parsed, parse_err)


            new_lines = [lines[0]]
            for k in order:
                if k in ("host", "content-length", "expect", "transfer-encoding"):
                    continue
                if k == "user-agent":
                    new_lines.append("User-Agent: cortexagent/1.0")
                else:
                    new_lines.append(f"{orig[k]}: {hdr[k]}")
            new_lines.append(f"Content-Length: {len(body)}")
            new_lines.append("Host: 127.0.0.1")
            head_bytes = ("\r\n".join(new_lines)).encode()

        data = head_bytes + b"\r\n\r\n" + body
        _t0 = time.time()
        self._send_and_pipe(data)
        _elapsed = time.time() - _t0
        if _elapsed > 0.1:
            print(f"[proxy] completed in {_elapsed:.2f}s", file=sys.stderr)




        if os.isatty(sys.stderr.fileno()) if hasattr(sys.stderr, "fileno") else False:
            print("\n_\n▎ thinking: completion in {:.2f}s\n".format(_elapsed), file=sys.stderr)






        try:
            _emit_dashboard_step(body, _elapsed)
        except Exception:
            pass

    def _forward_chunked(self, head_bytes, body):

        cap = int(os.environ.get("CORTEXAGENT_MINIFY_CHUNKED_MAX", str(16 * 1024 * 1024)))
        buf = body
        terminator = b"\r\n0\r\n\r\n"
        while terminator not in buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap:

                self._forward_raw(head_bytes, buf)
                return
        dechunked = _dechunk(buf)
        if dechunked is None:
            self._forward_raw(head_bytes, buf)
            return
        try:
            parsed = json.loads(dechunked)
            if isinstance(parsed, dict):
                if "grammar" in parsed:
                    del parsed["grammar"]
                parsed = _cap_tool_results(parsed, _TOOL_RESULT_MAX)
                parsed, mstats = minify_request(parsed, _MINIFY_CFG)
                print(f"[proxy] minify(chunked): {mstats.summary()}", file=sys.stderr)
                _record_minify(mstats)
                # Hard cap: aggressively truncate user message so it
                # always fits before the gate check.
                parsed, _ = _hard_cap_prompt(parsed)
                parsed, gate_ok, gate_total, is_overcapacity = _context_gate(parsed)
                if not gate_ok:
                    if is_overcapacity:
                        self._respond_overcapacity(gate_total, 100)
                    else:
                        self._respond_overflow(gate_total)
                    return
                dechunked = json.dumps(parsed).encode()
        except Exception as e:
            print(f"[proxy] chunked minify skipped: {e}", file=sys.stderr)
            self._forward_raw(head_bytes, buf)
            return

        headers_text = head_bytes.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        new_lines = [lines[0]]
        for line in lines[1:]:
            if not line:
                continue
            k = line.split(":", 1)[0].strip().lower()
            if k in ("transfer-encoding", "content-length", "expect", "host"):
                continue
            if k == "user-agent":
                new_lines.append("User-Agent: cortexagent/1.0")
            else:
                new_lines.append(line)
        new_lines.append(f"Content-Length: {len(dechunked)}")
        new_lines.append("Host: 127.0.0.1")
        head = ("\r\n".join(new_lines)).encode()
        self._send_and_pipe(head + b"\r\n\r\n" + dechunked)

    def _forward_chunked_strip_only(self, head_bytes, body):

        cap = int(os.environ.get("CORTEXAGENT_MINIFY_CHUNKED_MAX", str(16 * 1024 * 1024)))
        buf = body
        terminator = b"\r\n0\r\n\r\n"
        while terminator not in buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap:
                self._forward_raw(head_bytes, buf)
                return
        dechunked = _dechunk(buf)
        if dechunked is None:
            self._forward_raw(head_bytes, buf)
            return
        try:
            parsed = json.loads(dechunked)
            if isinstance(parsed, dict) and "grammar" in parsed:
                del parsed["grammar"]
                dechunked = json.dumps(parsed).encode()
        except Exception as e:
            print(f"[proxy] chunked strip skipped: {e}", file=sys.stderr)
            self._forward_raw(head_bytes, buf)
            return

        headers_text = head_bytes.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        new_lines = [lines[0]]
        for line in lines[1:]:
            if not line:
                continue
            k = line.split(":", 1)[0].strip().lower()
            if k in ("transfer-encoding", "content-length", "expect", "host"):
                continue
            if k == "user-agent":
                new_lines.append("User-Agent: cortexagent/1.0")
            else:
                new_lines.append(line)
        new_lines.append(f"Content-Length: {len(dechunked)}")
        new_lines.append("Host: 127.0.0.1")
        head = ("\r\n".join(new_lines)).encode()
        self._send_and_pipe(head + b"\r\n\r\n" + dechunked)

    def _forward_raw(self, head_bytes, body):

        data = head_bytes + b"\r\n\r\n" + body



        dst = self._connect_with_reload(timeout=90)
        if dst is None:
            self._respond_502()
            return
        try:
            dst.sendall(data)
        except Exception as e:
            print(f"[proxy] send error: {e}", file=sys.stderr)
            dst.close()
            self._respond_502()
            return
        stop = threading.Event()
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop), daemon=True)
        t1.start()
        self.conn.settimeout(0.5)
        _idle_since = time.monotonic()
        try:
            while True:
                try:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    _idle_since = time.monotonic()
                    dst.sendall(chunk)
                except socket.timeout:






                    if not t1.is_alive() and time.monotonic() - _idle_since > 30:
                        break
                    continue
        except Exception:
            pass
        finally:
            stop.set()
            t1.join(timeout=3)
            try:
                dst.close()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass

    def _send_and_pipe(self, data):

        dst = self._connect_with_reload(timeout=5)
        _t0 = time.time()
        if dst is None:
            self._respond_502()
            return
        try:
            dst.sendall(data)
        except Exception as e:
            print(f"[proxy] send error: {e}", file=sys.stderr)
            dst.close()
            self._respond_502()
            return
        stop = threading.Event()
        resp_buf: list[bytes] = []
        t1 = threading.Thread(target=pipe, args=(dst, self.conn, stop, resp_buf), daemon=True)
        t1.start()
        self.conn.settimeout(0.5)
        _idle_since = time.monotonic()
        try:
            while True:
                try:
                    chunk = self.conn.recv(65536)
                    if not chunk:
                        break
                    _idle_since = time.monotonic()
                    dst.sendall(chunk)
                except socket.timeout:


                    if not t1.is_alive() and time.monotonic() - _idle_since > 2:
                        # 2026-08-30: upstream pipe thread is dead -> the response
                        # is over. Old code idled 30s here, so the client SDK's own
                        # timeout fired first and every late/long turn surfaced as
                        # "Connection error." (123 of them in one live session).
                        # 2s grace to drain in-flight client bytes, then EOF.
                        break
                    continue
        except Exception:
            pass
        finally:
            stop.set()







            try:
                pt, ct, _elapsed = 0, 0, time.time() - _t0
                if resp_buf:
                    full = b"".join(resp_buf)



                    minified = minify_response(full)
                    if minified is not full:
                        resp_buf.clear()
                        resp_buf.append(minified)
                    body_bytes = minified if minified is not full else full
                    full_text = body_bytes.decode("utf-8", errors="replace")




                    if "\r\n\r\n" in full_text:
                        full_text = full_text.split("\r\n\r\n", 1)[1]

                    if not full_text and "\n\n" in (body_bytes.decode("utf-8", errors="replace")):
                        full_text = body_bytes.decode("utf-8", errors="replace").split("\n\n", 1)[1]
                    stripped_text = full_text.strip()






                    payloads: list[str] = []
                    try:
                        json.loads(stripped_text)
                        payloads.append(stripped_text)
                    except Exception:
                        for line in full_text.split("\n"):
                            ln = line.strip()
                            if not ln or not ln.startswith("data:"):
                                continue
                            payload = ln[5:].strip()
                            if not payload or payload == "[DONE]":
                                continue
                            payloads.append(payload)


                    for payload in payloads:
                        try:
                            obj = json.loads(payload)
                        except Exception:
                            continue
                        if not isinstance(obj, dict):
                            continue




                        usage = obj.get("usage")


                        if not isinstance(usage, dict):
                            msg = obj.get("message")
                            if isinstance(msg, dict):
                                usage = msg.get("usage")
                        if isinstance(usage, dict):
                            u_pt = int(usage.get("prompt_tokens", 0) or 0)
                            u_ct = int(usage.get("completion_tokens", 0) or 0)

                            if not u_pt:
                                u_pt = int(usage.get("input_tokens", 0) or 0)
                            if not u_ct:
                                u_ct = int(usage.get("output_tokens", 0) or 0)
                            if u_pt:
                                pt = u_pt
                            if u_ct:
                                ct = u_ct






                        if not pt and not ct:
                            timings = obj.get("timings")
                            if isinstance(timings, dict):
                                pn = int(timings.get("prompt_n", 0) or 0)
                                prn = int(timings.get("predicted_n", 0) or 0)
                                if pn:
                                    pt = pn
                                if prn:
                                    ct = prn
            except Exception:



                pt, ct, _elapsed = 0, 0, 0.0


            if ct:
                try:
                    _record_tokens(pt, ct, _elapsed)
                    tok_s = round(ct / _elapsed, 1) if _elapsed > 0 else 0
                    print(f"[proxy] tokens: {pt} in → {ct} out ({tok_s} tok/s, {_elapsed:.1f}s)", file=sys.stderr)
                except Exception:
                    pass


            t1.join(timeout=3)
            try:
                dst.close()
            except Exception:
                pass
            try:
                self.conn.close()
            except Exception:
                pass


def main():
    _load_minify_stats()
    port = int(os.environ.get("CORTEXAGENT_PROXY_PORT", sys.argv[1] if len(sys.argv) > 1 else "8081"))
    target_url = os.environ.get("CORTEXAGENT_PROXY_TARGET", sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8080")
    host = target_url.split("://")[-1].split(":")[0]
    port_target = int(target_url.split(":")[-1])
    target = (host, port_target)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


    bound = False
    for attempt in range(20):
        try:
            server.bind(("127.0.0.1", port))
            bound = True
            break
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            print(f"[proxy] :{port} busy (attempt {attempt+1}/20), retrying…", file=sys.stderr)
            time.sleep(0.5)
    if not bound:
        raise OSError(errno.EADDRINUSE, f"port {port} still in use after 10s of retries")
    server.listen(10)
    print(f"[proxy] listening on {port} -> {target_url}", file=sys.stderr)

    while True:
        conn, addr = server.accept()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

        if hasattr(socket, "TCP_KEEPIDLE"):
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            except Exception:
                pass
        handler = ProxyHandler(conn, addr, target)
        threading.Thread(target=handler.handle, daemon=True).start()


if __name__ == "__main__":
    main()
