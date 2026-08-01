#!/usr/bin/env python3
"""playwright_brave_mcp — MCP server controlling Brave via CDP on port 9222."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


CDP_URL = "http://127.0.0.1:9222"


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


TOOLS = [
    _tool("brave_status", "Check Brave CDP reachability.", {}, []),
    _tool("brave_navigate", "Navigate to URL; return title+URL.", {"url": {"type": "string"}}, ["url"]),
    _tool("brave_fetch", "Fetch page text via Brave (use for JS-heavy sites).", {
        "url": {"type": "string"},
        "selector": {"type": "string", "description": "CSS selector (default body)."},
        "wait_for_text": {"type": "string"},
        "timeout": {"type": "number", "description": "Seconds (default 30)."},
    }, ["url"]),
    _tool("brave_click", "Click element by CSS selector or accessible text.", {
        "target": {"type": "string"},
        "by_text": {"type": "boolean"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
    }, ["target"]),
    _tool("brave_type", "Type text into an element.", {
        "target": {"type": "string"},
        "text": {"type": "string"},
        "by_text": {"type": "boolean"},
        "submit": {"type": "boolean"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
    }, ["target", "text"]),
    _tool("brave_evaluate", "Evaluate JS in Brave and return JSON result.", {
        "expression": {"type": "string"},
        "timeout": {"type": "number", "description": "Seconds (default 10)."},
    }, ["expression"]),
    _tool("brave_snapshot", "Return accessibility snapshot of current page.", {"depth": {"type": "number"}}, []),
]


def _connect() -> Tuple[Any, Any]:
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    return browser, page


def _close(browser: Any) -> None:
    try:
        browser.close()
    except Exception:
        pass


def _as_text_content(element: Any) -> str:
    text = element.inner_text()
    return text.strip() if text else ""


def _ok_result(content: Any) -> Dict[str, Any]:
    if isinstance(content, list):
        return {"content": content}
    return {"content": [{"type": "text", "text": str(content)}]}


def _err_result(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _handle_status() -> Dict[str, Any]:
    try:
        browser, page = _connect()
        version = browser.version if hasattr(browser, "version") else "unknown"
        _close(browser)
        return _ok_result(f"Brave reachable on {CDP_URL} (browser: {version}).")
    except Exception as e:
        return _err_result(f"Brave not reachable on {CDP_URL}: {e}")


def _handle_navigate(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        browser, page = _connect()
        page.goto(args["url"], wait_until="domcontentloaded", timeout=30000)
        title, url = page.title(), page.url
        _close(browser)
        return _ok_result(f"Title: {title}\nURL: {url}")
    except Exception as e:
        return _err_result(f"Navigate failed: {e}")


def _handle_fetch(args: Dict[str, Any]) -> Dict[str, Any]:
    selector = args.get("selector", "body")
    wait_text = args.get("wait_for_text")
    timeout = args.get("timeout", 30) * 1000
    try:
        browser, page = _connect()
        page.goto(args["url"], wait_until="networkidle", timeout=timeout)
        if wait_text:
            page.wait_for_selector(f"text={wait_text}", timeout=timeout)
        text = _as_text_content(page.locator(selector).first)
        _close(browser)
        if not text:
            return _err_result("Page loaded but extracted text was empty.")
        return _ok_result(text)
    except PlaywrightTimeout:
        return _err_result(f"Timed out waiting for {args['url']} or selector '{selector}'.")
    except Exception as e:
        return _err_result(f"Fetch failed: {e}")


def _locate(page: Any, target: str, by_text: bool, timeout: float) -> Any:
    return page.get_by_text(target) if by_text else page.locator(target)


def _handle_click(args: Dict[str, Any]) -> Dict[str, Any]:
    target = args["target"]
    by_text = bool(args.get("by_text"))
    timeout = args.get("timeout", 10) * 1000
    try:
        browser, page = _connect()
        _locate(page, target, by_text, timeout).click(timeout=timeout)
        _close(browser)
        return _ok_result("Clicked.")
    except Exception as e:
        return _err_result(f"Click failed: {e}")


def _handle_type(args: Dict[str, Any]) -> Dict[str, Any]:
    target = args["target"]
    text = args["text"]
    by_text = bool(args.get("by_text"))
    submit = bool(args.get("submit"))
    timeout = args.get("timeout", 10) * 1000
    try:
        browser, page = _connect()
        _locate(page, target, by_text, timeout).fill(text, timeout=timeout)
        if submit:
            page.keyboard.press("Enter")
        _close(browser)
        return _ok_result("Typed.")
    except Exception as e:
        return _err_result(f"Type failed: {e}")


def _handle_evaluate(args: Dict[str, Any]) -> Dict[str, Any]:
    expression = args["expression"]
    timeout = args.get("timeout", 10) * 1000
    try:
        browser, page = _connect()
        result = page.evaluate(expression, timeout=timeout)
        _close(browser)
        return _ok_result(json.dumps(result, ensure_ascii=False, default=str))
    except Exception as e:
        return _err_result(f"Evaluate failed: {e}")


def _handle_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    depth = args.get("depth", 10)
    try:
        browser, page = _connect()
        snapshot = page.accessibility.snapshot(depth=depth)
        _close(browser)
        return _ok_result(json.dumps(snapshot, ensure_ascii=False, indent=2))
    except Exception as e:
        return _err_result(f"Snapshot failed: {e}")


def _dispatch_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "brave_status":
        return _handle_status()
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
    return _err_result(f"Unknown tool: {name}")


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    _id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": _id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "playwright-brave-mcp", "version": "1.0"}}}

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
