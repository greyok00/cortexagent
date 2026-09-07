#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from browser_control import (  # noqa: E402
    CDP_URL, close, list_tabs, navigate, fetch, click, type_text,
    evaluate, snapshot, fill_and_send, health,
)

from lib.tool_registry import register_tool  # noqa: E402


def _schema(description: str, properties: Dict[str, Any],
            required: List[str]) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}




_TAB = {"type": ["string", "null"],
        "description": "Target tab: URL prefix, CDP target id, or omit for the first tab."}


# Tool names renamed from brave_* → chrome_* on 2026-08-28 as part of the
# Patchright + Chrome default-browser migration. Same schemas, same handlers,
# just a different prefix to reflect the actual browser underneath.
_TOOL_DEFS = [
    ("chrome_status", "Check Chrome CDP reachability and count open tabs.",
     {}, []),
    ("chrome_tabs", "List open tabs (index, title, url).", {}, []),
    ("chrome_navigate", "Navigate a tab to URL; return title+URL.",
     {"url": {"type": "string"}, "tab": _TAB}, ["url"]),
    ("chrome_fetch", "Fetch page text via Chrome (use for JS-heavy sites).",
     {"url": {"type": "string"},
      "selector": {"type": "string", "description": "CSS selector (default body)."},
      "wait_for_text": {"type": "string"},
      "timeout": {"type": "number", "description": "Seconds (default 30)."},
      "tab": _TAB}, ["url"]),
    ("chrome_click", "Click element by CSS selector or accessible text.",
     {"target": {"type": "string"}, "by_text": {"type": "boolean"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["target"]),
    ("chrome_type", "Type text into an element.",
     {"target": {"type": "string"}, "text": {"type": "string"},
      "by_text": {"type": "boolean"}, "submit": {"type": "boolean"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["target", "text"]),
    ("chrome_evaluate", "Evaluate JS in Chrome and return JSON result.",
     {"expression": {"type": "string"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["expression"]),
    ("chrome_snapshot", "Return accessibility snapshot of a tab.",
     {"depth": {"type": "number"}, "tab": _TAB}, []),
    ("chrome_fill_send", "Fill a shadow-DOM controlled component (React/LWC) and press Enter. Use for embedded chat composers.",
     {"text": {"type": "string"},
      "iframe_marker": {"type": "string", "description": "Substring of the iframe src to target (e.g. 'lwc.mode'). Empty = top document."},
      "tag": {"type": "string", "description": "Element tag (default TEXTAREA)."},
      "class_fragment": {"type": "string", "description": "Substring of the element's class (e.g. 'embeddedMessagingInputFooterTextArea')."},
      "submit": {"type": "boolean", "description": "Press Enter after filling (default true)."},
      "tab": _TAB}, ["text"]),
    ("chrome_health", "Return engine health: CDP reachability, tab count, reconnect count, average call latency, cached sockets. Generic — no site data.",
     {}, []),
]


def _handle_status(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        return {"ok": True, "output": f"Chrome reachable on {CDP_URL} — {len(tabs)} tab(s).", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Chrome not reachable on {CDP_URL}: {e}"}


def _handle_tabs(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        lines = [f"[{t.get('index', i)}] {t.get('title', '')} — {t.get('url', '')}"
                 for i, t in enumerate(tabs)]
        return {"ok": True, "output": "\n".join(lines) if lines else "No tabs open.", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"List tabs failed: {e}"}


def _handle_navigate(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = navigate(tab=args.get("tab"), url=args["url"])
        return {"ok": True, "output": f"Title: {r['title']}\nURL: {r['url']}", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Navigate failed: {e}"}


def _handle_fetch(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        text = fetch(tab=args.get("tab"), url=args["url"],
                     selector=args.get("selector", "body"))
        if not text or not text.get("text"):
            return {"ok": False, "output": "", "error": "Page loaded but extracted text was empty."}
        return {"ok": True, "output": text.get("text", ""), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Fetch failed: {e}"}


def _handle_click(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        click(tab=args.get("tab"), selector=args["target"],
              by_text=bool(args.get("by_text")), timeout=args.get("timeout", 10))
        return {"ok": True, "output": "Clicked.", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Click failed: {e}"}


def _handle_type(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        type_text(tab=args.get("tab"), selector=args["target"], text=args["text"],
                  by_text=bool(args.get("by_text")), submit=bool(args.get("submit")),
                  timeout=args.get("timeout", 10))
        return {"ok": True, "output": "Typed.", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Type failed: {e}"}


def _handle_evaluate(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = evaluate(tab=args.get("tab"), expression=args["expression"],
                          timeout=args.get("timeout", 10))
        return {"ok": True, "output": json.dumps(result, ensure_ascii=False, default=str), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Evaluate failed: {e}"}


def _handle_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        snap = snapshot(tab=args.get("tab"), depth=args.get("depth", 10))
        return {"ok": True, "output": json.dumps(snap, ensure_ascii=False, indent=2), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Snapshot failed: {e}"}


def _handle_fill_send(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ok = fill_and_send(tab=args.get("tab"), text=args["text"],
                           iframe_marker=args.get("iframe_marker", ""),
                           tag=args.get("tag", "TEXTAREA"),
                           class_fragment=args.get("class_fragment", ""),
                           submit=bool(args.get("submit", True)))
        if ok:
            sent = " and sent (Enter)." if args.get("submit", True) else " (not sent)."
            return {"ok": True, "output": "Filled" + sent, "error": ""}
        return {"ok": False, "output": "", "error": "Fill failed — element not found."}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Fill/send failed: {e}"}


def _handle_health(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        h = health()
        if not h.get("cdp_reachable"):
            return {"ok": False, "output": "", "error": h.get("cdp_error", "CDP unreachable")}

        lines = [
            f"CDP: {h.get('browser', '?')}",
            f"  reachable: yes   uptime: {h.get('uptime_sec', 0):.1f}s",
            f"  calls: {h.get('calls', 0)}   reconnects: {h.get('reconnects', 0)}   retries: {h.get('retries', 0)}   failures: {h.get('failures', 0)}",
            f"  /json fetches: {h.get('json_fetches', 0)}   cached_sockets: {h.get('cached_sockets', 0)}",
            f"  last_call: {h.get('last_call_ms', 0):.1f}ms",
        ]
        return {"ok": True, "output": "\n".join(lines), "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Health check failed: {e}"}


_HANDLERS = {
    "chrome_status": _handle_status,
    "chrome_tabs": _handle_tabs,
    "chrome_navigate": _handle_navigate,
    "chrome_fetch": _handle_fetch,
    "chrome_click": _handle_click,
    "chrome_type": _handle_type,
    "chrome_evaluate": _handle_evaluate,
    "chrome_snapshot": _handle_snapshot,
    "chrome_fill_send": _handle_fill_send,
    "chrome_health": _handle_health,
}


def register_browser_tools() -> int:

    from lib.tool_registry import TOOLS
    count = 0
    for name, desc, props, required in _TOOL_DEFS:
        if name in TOOLS:
            continue




        def _make_wrapped(name=name):
            def _wrapped(**kwargs):
                return _HANDLERS[name](kwargs)
            _wrapped.__name__ = f"_wrapped_{name}"
            return _wrapped
        register_tool(name, _schema(desc, props, required), _make_wrapped(),
                      priority=1)
        count += 1
    return count


def _smoke() -> int:
    n = register_browser_tools()
    print(f"registered: {n} chrome_* tools")
    try:
        tabs = list_tabs()
        print(f"CDP reachable — {len(tabs)} tab(s)")
        close()
    except Exception as e:
        print(f"CDP check failed (graceful): {e}")
    print("browser_tools: OK")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())
    print("usage: browser_tools.py smoke", file=sys.stderr)
    sys.exit(2)