"""pipeline — the minification orchestrator.

This is the PURE EXTRACTION SEAM for the standalone plugin (Phase D).
``minify_request(body, cfg)`` takes a plain ``dict`` (a parsed Anthropic-style
request body) and a ``MinifyConfig``, returns ``(new_body, MinifyStats)``. It
imports NOTHING from ``lib.config`` / ``lib.control`` / socket code — only the
stdlib minify modules + the stdlib context/dom pruners. Build ``MinifyConfig``
from env vars at the call site.

Order (each stage is independent; a failure in one is recorded in stats and
NEVER aborts the others):
  1. tools        — balanced tool-def minify
  2. system       — fence-aware system-prompt minify
  3. messages     — code-aware text-block minify (tool I/O untouched)
  4. dom (opt)    — prune tool_result blocks that look like big HTML
  5. budget       — drop oldest safe messages if over token_budget (last)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Set

from lib.minify.tool_minify import minify_tools
from lib.minify.system_minify import minify_system
from lib.minify.message_minify import minify_message_content
from lib.minify.token_budget import enforce_budget, estimate_tokens_obj

# DOM stage is imported lazily (optional) so the core pipeline stays decoupled
# from the DOM module in the plugin extraction.
_DOM_THRESHOLD = 4096
_HTML_HINT = re.compile(r"<(?:html|!doctype|body|div|script)\b", re.IGNORECASE)


@dataclass
class MinifyConfig:
    token_budget: int = 0          # 0 = no budget enforcement
    enabled_stages: Set[str] = field(default_factory=lambda: {"tools", "system", "messages"})
    tool_skip: Set[str] = field(default_factory=set)
    minify_dom: bool = False       # opt-in: prune big HTML tool_results
    keep_last: int = 8             # budget: always keep most recent N messages


@dataclass
class MinifyStats:
    tokens_in: int = 0
    tokens_out: int = 0
    tools_minified: int = 0
    system_minified: bool = False
    messages_minified: int = 0
    dom_minified: int = 0
    budget_dropped: int = 0
    budget_tokens_before: int = 0
    budget_tokens_after: int = 0
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        d = self.tokens_in - self.tokens_out
        pct = (d / self.tokens_in * 100) if self.tokens_in else 0.0
        s = (f"in={self.tokens_in} out={self.tokens_out} -{d}({pct:.0f}%) "
             f"tools={self.tools_minified} sys={'Y' if self.system_minified else 'N'} "
             f"msgs={self.messages_minified} dom={self.dom_minified} "
             f"dropped={self.budget_dropped}")
        if self.errors:
            s += f" ERRORS={len(self.errors)}"
        return s


def _minify_system_field(system):
    """System can be a string OR a list of text blocks. Returns minified copy."""
    if isinstance(system, str):
        return minify_system(system)
    if isinstance(system, list):
        out = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                nb = dict(block)
                nb["text"] = minify_system(block["text"])
                out.append(nb)
            else:
                out.append(block)
        return out
    return system


def _maybe_prune_dom_in_messages(messages, stats):
    """Opt-in: prune tool_result blocks that look like large HTML payloads."""
    if not isinstance(messages, list):
        return messages
    try:
        from lib.dom_pruner import prune_dom
    except Exception:
        return messages
    changed = False
    new_msgs = []
    for msg in messages:
        if not isinstance(msg, dict):
            new_msgs.append(msg)
            continue
        c = msg.get("content")
        if isinstance(c, list):
            nc = []
            for block in c:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    rc = block.get("content")
                    if isinstance(rc, str) and len(rc) > _DOM_THRESHOLD and _HTML_HINT.search(rc):
                        try:
                            pruned = prune_dom(rc, "proxy")
                            nb = dict(block)
                            nb["content"] = pruned
                            nc.append(nb)
                            stats.dom_minified += 1
                            changed = True
                            continue
                        except Exception as e:
                            stats.errors.append(f"dom:{e}")
                nc.append(block)
            new_msgs.append({**msg, "content": nc})
        else:
            new_msgs.append(msg)
    return new_msgs if changed else messages


def minify_request(body: dict, cfg: MinifyConfig) -> tuple:
    """Minify a parsed request body. Returns (new_body, MinifyStats).

    Never mutates the input. Never raises from a stage — failures are recorded
    in stats so one broken stage can't break inference.
    """
    stats = MinifyStats()
    if not isinstance(body, dict):
        return body, stats
    stats.tokens_in = estimate_tokens_obj(body)
    nb = dict(body)

    # 1. tools
    if "tools" in nb and "tools" in cfg.enabled_stages:
        try:
            before = len(nb.get("tools", []))
            nb["tools"] = minify_tools(nb.get("tools"), cfg.tool_skip)
            stats.tools_minified = before
        except Exception as e:
            stats.errors.append(f"tools:{e}")

    # 2. system
    if "system" in nb and "system" in cfg.enabled_stages:
        try:
            nb["system"] = _minify_system_field(nb["system"])
            stats.system_minified = True
        except Exception as e:
            stats.errors.append(f"system:{e}")

    # 3. messages
    if "messages" in nb and "messages" in cfg.enabled_stages:
        try:
            msgs = nb.get("messages")
            if isinstance(msgs, list):
                nm = []
                count = 0
                for msg in msgs:
                    if isinstance(msg, dict) and "content" in msg:
                        before = json.dumps(msg["content"])
                        after = minify_message_content(msg["content"])
                        if json.dumps(after) != before:
                            count += 1
                        nm.append({**msg, "content": after})
                    else:
                        nm.append(msg)
                nb["messages"] = nm
                stats.messages_minified = count
        except Exception as e:
            stats.errors.append(f"messages:{e}")

    # 4. dom (opt-in)
    if cfg.minify_dom and "messages" in nb:
        try:
            nb["messages"] = _maybe_prune_dom_in_messages(nb.get("messages"), stats)
        except Exception as e:
            stats.errors.append(f"dom:{e}")

    # 5. budget (last)
    if cfg.token_budget > 0 and "messages" in nb:
        try:
            nb = enforce_budget(nb, cfg.token_budget, keep_last=cfg.keep_last, stats=stats.__dict__)
        except Exception as e:
            stats.errors.append(f"budget:{e}")

    stats.tokens_out = estimate_tokens_obj(nb)
    return nb, stats


# ── Chunked path helper ──────────────────────────────────────────────────────
def minify_chunked_first_event(event_bytes: bytes, cfg: MinifyConfig):
    """Minify the first SSE ``data: {...}`` event of a streaming request.

    Returns (new_event_bytes, stats). On ANY parse problem returns the input
    unchanged with empty stats (caller falls back to raw passthrough). Most
    tool/system mass lands in the first event of a streaming /v1/messages POST.
    """
    if not event_bytes:
        return event_bytes, MinifyStats()
    try:
        text = event_bytes.decode("utf-8")
    except Exception:
        return event_bytes, MinifyStats()
    # Find the first complete `data: {json}\n` payload.
    idx = text.find("data: ")
    if idx < 0:
        return event_bytes, MinifyStats()
    nl = text.find("\n", idx)
    if nl < 0:
        return event_bytes, MinifyStats()
    payload = text[idx + 6:nl].strip()
    try:
        obj = json.loads(payload)
    except Exception:
        return event_bytes, MinifyStats()
    if not isinstance(obj, dict):
        return event_bytes, MinifyStats()
    # The streaming body is the full request in the first event (Anthropic sends
    # the complete request as one JSON object before SSE chunks begin in some
    # transports; for a true streaming body the first event is the request).
    new_obj, stats = minify_request(obj, cfg)
    new_payload = json.dumps(new_obj)
    new_event = (text[:idx + 6] + new_payload + text[nl:]).encode("utf-8")
    return new_event, stats