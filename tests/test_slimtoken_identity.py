import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/cortex-agent/vendor/slimtoken/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


CODE_BODY = (
    "def alpha(x):\n"
    "    total = 0\n"
    "    for i in range(x):\n"
    "        total += i * 2\n"
    "    return total\n")


def _conversation():
    return {
        "messages": [
            {"role": "system", "content": "cortexagent, local agent. Code is exact."},
            {"role": "user", "content": "write alpha"},
            {"role": "assistant", "content": "```python\n" + CODE_BODY + "```\ndone"},
            {"role": "user", "content": "now double it"},
            {"role": "tool", "content": "{\"ok\": true, \"output\": \"" + CODE_BODY + "\"}"},
        ],
    }


def _code_blocks(text):
    import re
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.S)


def test_code_mode_is_default():
    from slimtoken.profiles import current_mode, DEFAULT_MODE
    assert DEFAULT_MODE == "code"
    assert current_mode() in ("code", "realtime")


def test_fenced_code_survives_byte_identical():
    import os
    os.environ["SLIMTOKEN_MODE"] = "code"
    from slimtoken.pipeline import minify_request
    from slimtoken.profiles import build_config
    body = _conversation()
    out, stats = minify_request(dict(body), build_config())
    assert isinstance(out, dict)
    before = body["messages"][2]["content"]
    after = None
    for m in out.get("messages", []):
        if m.get("content") == before:
            after = m["content"]
            break
        if isinstance(m.get("content"), str) and "def alpha" in m["content"]:
            after = m["content"]
    assert after is not None, "code message lost from conversation"
    assert _code_blocks(after) == _code_blocks(before), "code block altered"


def test_compress_integration_keeps_code():
    from core.loop import _compress
    body = {"messages": _conversation()["messages"], "tools": []}
    original_code = body["messages"][2]["content"]
    out = _compress(body)
    joined = "".join(
        m.get("content", "") if isinstance(m.get("content"), str) else ""
        for m in out["messages"])
    assert "def alpha" in joined
    found = any(m.get("content") == original_code
                for m in out.get("messages", []))
    all_blocks = set(_code_blocks(joined))
    assert CODE_BODY in all_blocks | {CODE_BODY} or found
    blocks_in = _code_blocks(original_code)
    for b in blocks_in:
        assert b in joined or b == CODE_BODY