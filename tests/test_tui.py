import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_splash_geometry():
    from ui.splash import SPLASH_TEXT, SPLASH_MIN_W
    assert SPLASH_MIN_W() == 71   # fork label "stock MoE (VRAM card)" width law
    import re as _re
    visible = [_re.sub(r"\x1b\[[0-9;]*m", "", r) for r in SPLASH_TEXT.split("\n")]
    assert max(len(r) for r in visible) <= 90
    assert "MODEL: stock MoE (VRAM card)" in SPLASH_TEXT
    assert "AUTHOR: greyok00" in SPLASH_TEXT


def test_palette_is_8bit_monochrome():
    from ui.splash import shade
    for i in range(8):
        assert shade(i).startswith("\x1b[38;5;")
    assert not any("38;2;" in shade(i) for i in range(8))


def test_compact_splash_is_narrow():
    from ui.splash import compact_splash
    lines = compact_splash().split("\n")
    assert max(len(l) for l in lines) < 80   # compact stays terminal-narrow
    assert any("CORTEXAGENT" in l for l in lines)
    assert any("AUTHOR: greyok00" in l for l in lines)


def test_big_number_renders():
    from ui.splash import big_number
    rows = big_number(12.7).split("\n")
    assert len(rows) == 5
    assert len(rows[0]) == len(rows[4])


def test_ticker_line_has_three_stats():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    text = app.ticker_text()
    assert "model" in text
    assert "comp" in text
    assert "mem" in text


def test_ticker_write_emits_prompt():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    app._state["buffer"] = "say hi"
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.ticker_write()
    out = buf.getvalue()
    assert "╰─" in out and "say hi" in out
    assert "model" in out


def test_log_write_streams_text():
    import ui.app as app
    app._state["cols"], app._state["rows"] = 120, 40
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.log_write("> test line")
    out = buf.getvalue()
    assert "> test line" in out


def test_no_textual_dependency():
    import ui.app as app
    assert not hasattr(app, "compose")
    assert not hasattr(app, "CSS")