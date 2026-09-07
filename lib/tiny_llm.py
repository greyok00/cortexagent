#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.config import CFG  # noqa: E402

_PORT = int(CFG.tiny_model_port)
_BASE = f"http://127.0.0.1:{_PORT}"
CHAT_URL = f"{_BASE}/v1/chat/completions"
HEALTH_URL = f"{_BASE}/health"


def is_available(timeout: float = 3.0) -> bool:

    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _record_usage(data: dict) -> None:

    try:
        usage = data.get("usage") or {}
        tin = int(usage.get("prompt_tokens", 0))
        tout = int(usage.get("completion_tokens", 0))
        if tin or tout:
            from lib.token_tracker import track_tiny_model_run
            track_tiny_model_run(tin, tout)
    except Exception:
        pass






_TINY_SYSTEM = (
    "You are the CortexAgent overseer's reasoning engine. Plain language, "
    "short answers (one or two lines), no markdown, no emojis, no narration. "
    "State the action taken and the artifact path. If uncertain, say so."
)

def query(prompt: str, system: str = "", max_tokens: int = 256,
          temperature: float = 0.1, timeout: int = 30) -> Optional[str]:

    messages = []
    messages.append({"role": "system", "content": system or _TINY_SYSTEM})
    messages.append({"role": "user", "content": prompt})
    payload = {


        "model": "tiny",
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        req = urllib.request.Request(
            CHAT_URL, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        _record_usage(data)
        choices = data.get("choices") or [{}]
        content = choices[0].get("message", {}).get("content", "") or ""
        return content.strip()
    except Exception:
        return None


def _parse_tool_calls(message: dict) -> list:

    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append({
            "id": tc.get("id", f"call_{len(calls)}"),
            "name": name,
            "arguments": args,
        })
    return calls


def _parse_text_tool_calls(content: str) -> list:

    if not content:
        return []
    text = content.strip()



    m = re.search(
        r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:\n\s*Action Input:\s*(\{.*\}))?",
        text, re.S)
    if m:
        name = m.group(1)
        args = {}
        if m.group(2):
            try:
                args = json.loads(m.group(2))
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        return [{"id": "call_text_0", "name": name, "arguments": args}]




    m = re.search(r"<function_call>(.*?)</function_call>", text, re.S)
    if m:
        inner = m.group(1).strip()
        try:
            obj = json.loads(inner)
        except Exception:
            obj = None
        items = obj if isinstance(obj, list) else ([obj] if isinstance(obj, dict) else [])
        calls = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            if isinstance(name, str) and name:
                calls.append({"id": f"call_tag_{len(calls)}",
                              "name": name, "arguments": args})
        if calls:
            return calls

    start = text.find("{")
    if start == -1:
        return []
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return []
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []

    if "tool_call" in obj and isinstance(obj["tool_call"], dict):
        obj = obj["tool_call"]
    name = obj.get("tool") or obj.get("name") or obj.get("function")
    if isinstance(name, dict):
        name = name.get("name")
    if not isinstance(name, str) or not name:
        return []
    args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return [{"id": "call_text_0", "name": name, "arguments": args}]


def query_with_tools(messages: list, tools: list, max_tokens: int = 512,
                     timeout: int = 60) -> Optional[dict]:

    payload = {
        "model": "tiny",
        "messages": messages,
        "tools": tools,
        "max_tokens": int(max_tokens),
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        req = urllib.request.Request(
            CHAT_URL, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        _record_usage(data)
        choices = data.get("choices") or [{}]
        message = choices[0].get("message", {}) or {}
        calls = _parse_tool_calls(message)
        if calls:
            return {"kind": "tool_calls", "calls": calls}
        content = (message.get("content") or "").strip()
        if content:



            text_calls = _parse_text_tool_calls(content)
            if text_calls:
                return {"kind": "tool_calls", "calls": text_calls}
            return {"kind": "text", "content": content}
        return None
    except Exception:
        return None


def _test() -> int:

    fails = 0

    msg = {"content": "hello", "tool_calls": None}
    calls = _parse_tool_calls(msg)
    if calls != []:
        print(f"❌ text msg parsed as calls: {calls}")
        fails += 1

    msg = {"content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "run_command", "arguments": '{"command": "echo hi"}'}}]}
    calls = _parse_tool_calls(msg)
    if len(calls) != 1 or calls[0]["name"] != "run_command" \
            or calls[0]["arguments"] != {"command": "echo hi"}:
        print(f"❌ tool_calls parse: {calls}")
        fails += 1

    msg = {"content": None, "tool_calls": [
        {"id": "call_2", "type": "function",
         "function": {"name": "run_command", "arguments": "{bad json"}}]}
    calls = _parse_tool_calls(msg)
    if len(calls) != 1 or calls[0]["arguments"] != {}:
        print(f"❌ malformed args parse: {calls}")
        fails += 1


    calls = _parse_text_tool_calls(
        'I will check the time. {"tool": "run_command", '
        '"arguments": {"command": "date"}}')
    if len(calls) != 1 or calls[0]["name"] != "run_command" \
            or calls[0]["arguments"] != {"command": "date"}:
        print(f"❌ text JSON tool call: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        '{"name": "rag_query", "arguments": {"domain": "osint", "query": "IP"}}')
    if len(calls) != 1 or calls[0]["name"] != "rag_query":
        print(f"❌ text name/arguments: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        'Action: run_command\nAction Input: {"command": "echo hi"}')
    if len(calls) != 1 or calls[0]["name"] != "run_command" \
            or calls[0]["arguments"] != {"command": "echo hi"}:
        print(f"❌ ReAct Action parse: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        'I need the date. <function_call>[{"function": {"name": "get_current_date", '
        '"arguments": {}}}]</function_call>')
    if len(calls) != 1 or calls[0]["name"] != "get_current_date" \
            or calls[0]["arguments"] != {}:
        print(f"❌ function_call tag parse: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        '<function_call>[{"function": {"name": "run_command", '
        '"arguments": "{\\"command\\": \\"echo hi\\"}"}}, '
        '{"function": {"name": "rag_query", "arguments": {"domain": "osint", '
        '"query": "IP"}}}]</function_call>')
    if len(calls) != 2 or calls[0]["name"] != "run_command" \
            or calls[0]["arguments"] != {"command": "echo hi"} \
            or calls[1]["name"] != "rag_query":
        print(f"❌ function_call multi parse: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        '<function_call>{"function": {"name": "do_math", '
        '"arguments": {"a": 2, "op": "+", "b": 3}}}</function_call>')
    if len(calls) != 1 or calls[0]["name"] != "do_math" \
            or calls[0]["arguments"] != {"a": 2, "op": "+", "b": 3}:
        print(f"❌ function_call single-object parse: {calls}")
        fails += 1

    calls = _parse_text_tool_calls(
        '<function_call>[{"function": {"name": "x", "arguments": {bad}}]</function_call>')
    if calls != []:
        print(f"❌ malformed function_call parsed: {calls}")
        fails += 1

    calls = _parse_text_tool_calls("The answer is 4. No tools needed.")
    if calls != []:
        print(f"❌ plain answer parsed as call: {calls}")
        fails += 1

    calls = _parse_text_tool_calls('{"answer": 4}')
    if calls != []:
        print(f"❌ JSON answer parsed as call: {calls}")
        fails += 1
    print("tiny_llm parser: OK" if fails == 0 else f"❌ {fails} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_test())

    ok = is_available()
    print(f"tiny server health: {'OK' if ok else 'DOWN'}")
    if ok and len(sys.argv) > 1:
        print("response:", query(" ".join(sys.argv[1:]), max_tokens=64))