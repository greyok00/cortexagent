#!/usr/bin/env python3
"""lib/browser_tools.py — Playwright/Brave browser tools for the harness.

Registers the 9 ``brave_*`` tools directly in the tool registry by wrapping
``lib/browser_control`` functions — no MCP server process, no round-trip.
Same schemas as ``playwright_brave_mcp.py``'s TOOLS so the two surfaces stay
in sync. Drives Brave via CDP on :9222 (see lib/browser_control.py).

Usage:
  python3 lib/browser_tools.py smoke          # self-test (CDP optional)
"""
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
    evaluate, snapshot, fill_and_send,
)

from lib.tool_registry import register_tool  # noqa: E402


def _schema(description: str, properties: Dict[str, Any],
            required: List[str]) -> Dict[str, Any]:
    return {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}


_TAB = {"type": ["integer", "string", "null"],
        "description": "Target tab: index, URL prefix, or omit for the first tab."}

# Same schemas as playwright_brave_mcp.py TOOLS (kept in sync).
_TOOL_DEFS = [
    ("brave_status", "Check Brave CDP reachability and count open tabs.",
     {}, []),
    ("brave_tabs", "List open tabs (index, title, url).", {}, []),
    ("brave_navigate", "Navigate a tab to URL; return title+URL.",
     {"url": {"type": "string"}, "tab": _TAB}, ["url"]),
    ("brave_fetch", "Fetch page text via Brave (use for JS-heavy sites).",
     {"url": {"type": "string"},
      "selector": {"type": "string", "description": "CSS selector (default body)."},
      "wait_for_text": {"type": "string"},
      "timeout": {"type": "number", "description": "Seconds (default 30)."},
      "tab": _TAB}, ["url"]),
    ("brave_click", "Click element by CSS selector or accessible text.",
     {"target": {"type": "string"}, "by_text": {"type": "boolean"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["target"]),
    ("brave_type", "Type text into an element.",
     {"target": {"type": "string"}, "text": {"type": "string"},
      "by_text": {"type": "boolean"}, "submit": {"type": "boolean"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["target", "text"]),
    ("brave_evaluate", "Evaluate JS in Brave and return JSON result.",
     {"expression": {"type": "string"},
      "timeout": {"type": "number", "description": "Seconds (default 10)."},
      "tab": _TAB}, ["expression"]),
    ("brave_snapshot", "Return accessibility snapshot of a tab.",
     {"depth": {"type": "number"}, "tab": _TAB}, []),
    ("brave_fill_send", "Fill a shadow-DOM controlled component (React/LWC) and press Enter. Use for embedded chat composers.",
     {"text": {"type": "string"},
      "iframe_marker": {"type": "string", "description": "Substring of the iframe src to target (e.g. 'lwc.mode'). Empty = top document."},
      "tag": {"type": "string", "description": "Element tag (default TEXTAREA)."},
      "class_fragment": {"type": "string", "description": "Substring of the element's class (e.g. 'embeddedMessagingInputFooterTextArea')."},
      "submit": {"type": "boolean", "description": "Press Enter after filling (default true)."},
      "tab": _TAB}, ["text"]),
]


def _handle_status() -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        return {"ok": True, "output": f"Brave reachable on {CDP_URL} — {len(tabs)} tab(s).", "error": ""}
    except Exception as e:
        return {"ok": False, "output": "", "error": f"Brave not reachable on {CDP_URL}: {e}"}


def _handle_tabs() -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        lines = [f"[{t['index']}] {t['title']} — {t['url']}" for t in tabs]
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
                     selector=args.get("selector", "body"),
                     wait_for_text=args.get("wait_for_text", ""),
                     timeout=args.get("timeout", 30))
        if not text:
            return {"ok": False, "output": "", "error": "Page loaded but extracted text was empty."}
        return {"ok": True, "output": text, "error": ""}
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


_HANDLERS = {
    "brave_status": _handle_status,
    "brave_tabs": _handle_tabs,
    "brave_navigate": _handle_navigate,
    "brave_fetch": _handle_fetch,
    "brave_click": _handle_click,
    "brave_type": _handle_type,
    "brave_evaluate": _handle_evaluate,
    "brave_snapshot": _handle_snapshot,
    "brave_fill_send": _handle_fill_send,
}


def register_browser_tools() -> int:
    """Register the 9 brave_* tools in the tool registry. Idempotent."""
    from lib.tool_registry import TOOLS
    count = 0
    for name, desc, props, required in _TOOL_DEFS:
        if name in TOOLS:
            continue
        register_tool(name, _schema(desc, props, required), _HANDLERS[name],
                      priority=1)
        count += 1
    return count


def _smoke() -> int:
    n = register_browser_tools()
    print(f"registered: {n} brave_* tools")
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
