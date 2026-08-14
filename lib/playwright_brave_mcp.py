#!/usr/bin/env python3
"""playwright_brave_mcp — MCP server controlling Brave via CDP on port 9222.

Thin MCP transport over lib/browser_control (the general browser engine).
Holds ONE persistent Playwright CDP connection per process — no per-call
connect/close churn (which wedges the browser-level endpoint).

Run as:  python3 lib/playwright_brave_mcp.py   (stdio MCP server)
         python3 lib/playwright_brave_mcp.py smoke
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from browser_control import (
    CDP_URL, close, list_tabs, navigate, fetch, click, type_text,
    evaluate, snapshot, read_text, fill_and_send,
)


def _send_json(obj: Dict[str, Any]) -> None:
    raw = json.dumps(obj, ensure_ascii=False) + "\n"
    sys.stdout.write(raw)
    sys.stdout.flush()


def _read_json() -> Optional[Dict[str, Any]]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _tool(name: str, description: str, params: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": params, "required": required}}


_TAB = {"type": ["integer", "string", "null"], "description": "Target tab: index, URL prefix, or omit for the first tab."}

TOOLS = [
    _tool("brave_status", "Check Brave CDP reachability and count open tabs.", {}, []),
    _tool("brave_tabs", "List open tabs (index, title, url).", {}, []),
    _tool("brave_navigate", "Navigate a tab to URL; return title+URL.", {
        "url": {"type": "string"},
        "tab": _TAB,
    }, ["url"]),
    _tool("brave_fetch", "Fetch page text via Brave (use for JS-heavy sites).", {
        "url": {"type": "string"},
        "selector": {"type": "string", "description": "CSS selector (default body)."},
        "wait_for_text": {"type": "string"},
        "timeout": {"type": "number", "description": "Seconds (default 30)."},
        "tab": _TAB,
    }, ["url"]),
    _tool("brave_click", "Click element by CSS selector or accessible text.", {
        "target": {"type": "string"},
        "by_text": {"type": "boolean"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
        "tab": _TAB,
    }, ["target"]),
    _tool("brave_type", "Type text into an element.", {
        "target": {"type": "string"},
        "text": {"type": "string"},
        "by_text": {"type": "boolean"},
        "submit": {"type": "boolean"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
        "tab": _TAB,
    }, ["target", "text"]),
    _tool("brave_evaluate", "Evaluate JS in Brave and return JSON result.", {
        "expression": {"type": "string"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
        "tab": _TAB,
    }, ["expression"]),
    _tool("brave_snapshot", "Return accessibility snapshot of a tab.", {
        "depth": {"type": "number"},
        "tab": _TAB,
    }, []),
    _tool("brave_fill_send", "Fill a shadow-DOM controlled component (React/LWC) and press Enter. Use for embedded chat composers.", {
        "text": {"type": "string"},
        "iframe_marker": {"type": "string", "description": "Substring of the iframe src to target (e.g. 'lwc.mode'). Empty = top document."},
        "tag": {"type": "string", "description": "Element tag (default TEXTAREA)."},
        "class_fragment": {"type": "string", "description": "Substring of the element's class (e.g. 'embeddedMessagingInputFooterTextArea')."},
        "submit": {"type": "boolean", "description": "Press Enter after filling (default true)."},
        "tab": _TAB,
    }, ["text"]),
]


def _ok_result(content: Any) -> Dict[str, Any]:
    if isinstance(content, list):
        return {"content": content}
    return {"content": [{"type": "text", "text": str(content)}]}


def _err_result(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _handle_status() -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        return _ok_result(f"Brave reachable on {CDP_URL} — {len(tabs)} tab(s).")
    except Exception as e:
        return _err_result(f"Brave not reachable on {CDP_URL}: {e}")


def _handle_tabs() -> Dict[str, Any]:
    try:
        tabs = list_tabs()
        lines = [f"[{t['index']}] {t['title']} — {t['url']}" for t in tabs]
        return _ok_result("\n".join(lines) if lines else "No tabs open.")
    except Exception as e:
        return _err_result(f"List tabs failed: {e}")


def _handle_navigate(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = navigate(tab=args.get("tab"), url=args["url"])
        return _ok_result(f"Title: {r['title']}\nURL: {r['url']}")
    except Exception as e:
        return _err_result(f"Navigate failed: {e}")


def _handle_fetch(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        text = fetch(tab=args.get("tab"), url=args["url"],
                     selector=args.get("selector", "body"),
                     wait_for_text=args.get("wait_for_text", ""),
                     timeout=args.get("timeout", 30))
        if not text:
            return _err_result("Page loaded but extracted text was empty.")
        return _ok_result(text)
    except Exception as e:
        return _err_result(f"Fetch failed: {e}")


def _handle_click(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        click(tab=args.get("tab"), selector=args["target"],
              by_text=bool(args.get("by_text")), timeout=args.get("timeout", 10))
        return _ok_result("Clicked.")
    except Exception as e:
        return _err_result(f"Click failed: {e}")


def _handle_type(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        type_text(tab=args.get("tab"), selector=args["target"], text=args["text"],
                  by_text=bool(args.get("by_text")), submit=bool(args.get("submit")),
                  timeout=args.get("timeout", 10))
        return _ok_result("Typed.")
    except Exception as e:
        return _err_result(f"Type failed: {e}")


def _handle_evaluate(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = evaluate(tab=args.get("tab"), expression=args["expression"],
                          timeout=args.get("timeout", 10))
        return _ok_result(json.dumps(result, ensure_ascii=False, default=str))
    except Exception as e:
        return _err_result(f"Evaluate failed: {e}")


def _handle_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        snap = snapshot(tab=args.get("tab"), depth=args.get("depth", 10))
        return _ok_result(json.dumps(snap, ensure_ascii=False, indent=2))
    except Exception as e:
        return _err_result(f"Snapshot failed: {e}")


def _handle_fill_send(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ok = fill_and_send(tab=args.get("tab"), text=args["text"],
                           iframe_marker=args.get("iframe_marker", ""),
                           tag=args.get("tag", "TEXTAREA"),
                           class_fragment=args.get("class_fragment", ""),
                           submit=bool(args.get("submit", True)))
        if ok:
            sent = " and sent (Enter)." if args.get("submit", True) else " (not sent)."
            return _ok_result("Filled" + sent)
        return _err_result("Fill failed — element not found.")
    except Exception as e:
        return _err_result(f"Fill/send failed: {e}")


def _dispatch_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "brave_status":
        return _handle_status()
    if name == "brave_tabs":
        return _handle_tabs()
    if name == "brave_navigate":
        return _handle_navigate(args)
    if name == "brave_fetch":
        return _handle_fetch(args)
    if name == "brave_click":
        return _handle_click(args)
    if name == "brave_type":
        return _handle_type(args)
    if name == "brave_evaluate":
        return _handle_evaluate(args)
    if name == "brave_snapshot":
        return _handle_snapshot(args)
    if name == "brave_fill_send":
        return _handle_fill_send(args)
    return _err_result(f"Unknown tool: {name}")


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": _id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "playwright-brave-mcp", "version": "1.1"}}}

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": _id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        return {"jsonrpc": "2.0", "id": _id, "result": _dispatch_call(name, args)}

    return {"jsonrpc": "2.0", "id": _id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def _smoke() -> int:
    print(f"tools exposed: {[t['name'] for t in TOOLS]}")
    try:
        tabs = list_tabs()
        print(f"CDP reachable — {len(tabs)} tab(s)")
        close()
    except Exception as e:
        print(f"CDP check failed: {e}")
    print("playwright_brave_mcp: OK")
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        sys.exit(_smoke())

    while True:
        req = _read_json()
        if req is None:
            break
        resp = _handle_request(req)
        if resp is not None:
            _send_json(resp)


if __name__ == "__main__":
    main()
