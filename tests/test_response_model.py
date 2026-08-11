#!/usr/bin/env python3
"""Unit tests for lib/response_model.py — pure parsing/rendering, no Textual.

Run:  python3 -m pytest tests/test_response_model.py -q
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.response_model import (
    ArtifactBlock,
    CodeArtifact,
    DisclosureBlock,
    TextBlock,
    ToolBlock,
    collapse,
    detect_language,
    format_visual,
    infer_filename,
    parse_response,
    render_plain,
    sanitize_terminal,
    stream_turn,
    summarize,
    wrap_text,
)


# ── sanitization ─────────────────────────────────────────────────────────────
def test_sanitize_sgr_codes():
    assert sanitize_terminal("\x1b[31mred\x1b[0m") == "red"


def test_sanitize_osc_hyperlink():
    assert sanitize_terminal("link \x1b]8;;https://x\x07text\x1b]8;;\x07 end") == "link text end"


def test_sanitize_cursor_and_bracket_paste():
    text = "a\x1b[2Jb\x1b[?2004hc\x1b[?2004l"
    assert sanitize_terminal(text) == "abc"


def test_sanitize_two_byte_esc_and_ctrl():
    # \x1bM (2-byte ESC), BEL \x07, BS \x08, SI \x0f all stripped; \n kept
    assert sanitize_terminal("a\x1bMb\x1bMc\x07\x08d\x0fe") == "abcde"
    assert sanitize_terminal("a\nb\x0ct") == "a\nbt"


def test_sanitize_empty():
    assert sanitize_terminal("") == ""


# ── block parsing ───────────────────────────────────────────────────────────
def test_fenced_code_extraction():
    blocks = parse_response("Intro\n```python\nprint(1)\nprint(2)\n```\nOutro")
    kinds = [type(b) for b in blocks]
    assert TextBlock in kinds and ArtifactBlock in kinds
    art = next(b for b in blocks if isinstance(b, ArtifactBlock))
    assert art.artifact.language == "python"
    assert art.artifact.n_lines == 2
    assert art.artifact.source == "print(1)\nprint(2)"


def test_fence_without_language():
    blocks = parse_response("```\ndef foo():\n    return 1\n```")
    art = next(b for b in blocks if isinstance(b, ArtifactBlock))
    assert art.artifact.language == "python"
    assert art.artifact.filename.endswith(".py")


def test_fence_after_text_keeps_text():
    blocks = parse_response("before\n\n```bash\nls\n```")
    text = next(b for b in blocks if isinstance(b, TextBlock))
    assert text.text == "before"


def test_diff_block_extraction():
    src = ("diff --git a/x.py b/x.py\n"
           "index abc..def\n"
           "--- a/x.py\n"
           "+++ b/x.py\n"
           "@@ -1 +1 @@\n"
           "-print(1)\n"
           "+print(2)\n")
    blocks = parse_response(src)
    art = next(b for b in blocks if isinstance(b, ArtifactBlock))
    assert art.artifact.language == "diff"


def test_json_block_extraction():
    blocks = parse_response('{"a": 1}\n{"b": 2}')
    art = next(b for b in blocks if isinstance(b, ArtifactBlock))
    assert art.artifact.language == "json"


def test_indented_code_extraction():
    src = "Here is the code:\n\n    def add(a, b):\n        return a + b\n\nDone."
    blocks = parse_response(src)
    assert any(isinstance(b, ArtifactBlock) for b in blocks)


def test_plain_markdown_stays_text():
    blocks = parse_response("# Heading\n\nSome *prose* with `code`.")
    assert all(isinstance(b, TextBlock) for b in blocks)
    assert blocks[0].text.startswith("# Heading")


def test_parse_sanitizes_input():
    blocks = parse_response("hello \x1b[31mworld\x1b[0m")
    assert blocks and "world" in blocks[0].text
    assert "\x1b" not in blocks[0].text


# ── compaction ──────────────────────────────────────────────────────────────
def test_collapse_long_text_to_disclosure():
    blocks = [TextBlock("x" * 5000)]
    out = collapse(blocks)
    assert any(isinstance(b, DisclosureBlock) for b in out)
    visible = sum(len(b.text) for b in out if isinstance(b, TextBlock))
    assert visible <= 1501  # 1500 chars + the "…" truncation marker


def test_collapse_many_artifacts():
    arts = [ArtifactBlock(CodeArtifact(i, "python", f"f{i}.py", [f"line{i}"]))
            for i in range(6)]
    out = collapse(arts, max_visible_artifacts=4)
    visible = [b for b in out if isinstance(b, ArtifactBlock)]
    disc = [b for b in out if isinstance(b, DisclosureBlock)]
    assert len(visible) == 4
    assert any("Code artifacts (2)" in d.title for d in disc)


def test_collapse_tool_overflow():
    tools = [ToolBlock(summary=f"tool {i}", status="ok") for i in range(12)]
    out = collapse(tools)
    vis = [b for b in out if isinstance(b, ToolBlock)]
    disc = [b for b in out if isinstance(b, DisclosureBlock)]
    assert len(vis) == 8
    assert any(d.title.startswith("Tool activity") for d in disc)


def test_collapse_empty():
    assert collapse([]) == []


# ── language / filename inference ───────────────────────────────────────────
def test_detect_language_aliases():
    assert detect_language("js", ["x"]) == "javascript"
    assert detect_language("py", ["x"]) == "python"
    assert detect_language("", ["def f():", "    pass"]) == "python"
    assert detect_language("", ["class Foo {", "} "]) == "text/code"
    assert detect_language("", ["#!/bin/bash", "echo hi"]) == "bash"
    assert detect_language("", ["plain prose here"]) == "text"


def test_infer_filename_from_def():
    assert infer_filename("python", ["def my_func():"], 1) == "my_func.py"
    assert infer_filename("bash", ["#!/bin/bash", "echo hi"], 2).endswith(".sh")


# ── rendering / wrapping / summarising ──────────────────────────────────────
def test_wrap_text_width():
    wrapped = wrap_text("one two three four", 10)
    assert all(len(l) <= 10 for l in wrapped)


def test_wrap_preserves_newlines():
    wrapped = wrap_text("a\nb", 80)
    assert wrapped == ["a", "b"]


def test_render_plain_no_ansi():
    blocks = [TextBlock("hi"), ArtifactBlock(CodeArtifact(1, "python", "a.py", ["x=1"]))]
    out = render_plain(blocks)
    assert "\x1b" not in out
    assert "a.py" in out
    assert "x=1" in out


def test_render_plain_wraps_wide():
    blocks = [TextBlock("wide " * 40)]
    out = render_plain(blocks, width=40)
    assert all(len(l) <= 40 for l in out.splitlines())


# ── visual text: tables / charts / ascii art ────────────────────────────────
def test_render_markdown_table_bordered():
    src = ("Results:\n"
           "| model | vram |\n"
           "|---|---|\n"
           "| qwen | 13 |\n"
           "| tiny | 1 |")
    out = render_plain(parse_response(src), width=60)
    assert "│" in out and "─" in out
    assert "┌" in out and "└" in out
    assert "model" in out and "qwen" in out


def test_render_table_bar_chart():
    src = ("| model | tok/s |\n"
           "|---|---:|\n"
           "| qwen | 65 |\n"
           "| tiny | 30 |\n"
           "| lfm  | 48 |")
    out = render_plain(parse_response(src), width=60)
    assert "█" in out
    assert "▸ tok/s" in out


def test_table_no_chart_when_not_numeric():
    src = "| a | b |\n|---|---|\n| x | y |\n| z | w |"
    out = render_plain(parse_response(src), width=60)
    assert "│" in out
    assert "█" not in out


def test_lone_pipe_is_not_a_table():
    out = render_plain(parse_response("just a | pipe"), width=40)
    assert "│" not in out
    assert "pipe" in out


def test_ascii_art_preserved_unwrapped():
    art = "┌─────┐\n│ box │\n└─────┘"
    out = render_plain(parse_response(art), width=10)
    assert "┌─────┐" in out
    assert "│ box │" in out
    assert "└─────┘" in out


def test_heading_accent():
    out = render_plain(parse_response("# Title\n\nbody"), width=40)
    assert "▎ Title" in out


def test_format_visual_no_ansi():
    out = format_visual("| a |\n|---|\n| 1 |", width=30)
    assert "\x1b" not in out
    assert "┌" in out


def test_summarize_truncates():
    s = summarize("word " * 100)
    assert len(s) <= 250
    assert s.endswith("…")


def test_summarize_empty():
    assert summarize("   \n  ") == ""


# ── event stream ────────────────────────────────────────────────────────────
def test_stream_turn_events():
    events = list(stream_turn("hello", model="m1", started_at=1.0))
    assert events[0].model == "m1"
    assert events[1].text == "hello"
    assert events[2].text == "hello"
