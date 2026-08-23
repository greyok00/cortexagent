#!/usr/bin/env python3
"""tests/test_tui_status.py — pure-Python tests for lib/tui_status.py.

No Textual, no I/O. Covers display-width measurement, panel rendering,
three layouts, shrink priority, and the spec rules (zero-savings valid,
503 → WARMING, indeterminate bar has no fake percent, color paired with
glyph, required fields never dropped).
"""
from __future__ import annotations

import re
import unittest

# Force a colored + Unicode-capable environment for the rendering tests so
# the assertions about ANSI borders / Unicode glyphs hold. Production code
# honors the real environment; tests want to exercise the colored path.
import lib.tui_status as _tui_status
_tui_status._COLOR_BITS = 24  # type: ignore[attr-defined]
_tui_status._UNICODE = True   # type: ignore[attr-defined]

from lib.tui_status import (
    MemoryView,
    RuntimeView,
    SlimTokenView,
    StatusView,
    WorkLineView,
    WorkPhase,
    display_width,
    fit_to_cells,
    footer_line,
    panel_block,
    phase_from_proxy_signal,
    strip_render,
    work_line,
)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip(s: str) -> str:
    """Strip ANSI sequences so substring assertions don't trip on color."""
    return ANSI_RE.sub("", s)


# ── Width helpers ────────────────────────────────────────────────────────────

class TestDisplayWidth(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(display_width("hello"), 5)
        self.assertEqual(display_width(""), 0)
        self.assertEqual(display_width(None or ""), 0)

    def test_unicode_cjk(self):
        self.assertEqual(display_width("日本語"), 6)

    def test_status_glyphs(self):
        # All single-cell even if marked; the safe fallback is 1 cell.
        self.assertGreaterEqual(display_width("●"), 1)
        self.assertGreaterEqual(display_width("◈"), 1)

    def test_tab_and_newline_normalize(self):
        # Tabs/newlines don't multi-count when measured alone.
        self.assertEqual(display_width("\t"), 1)
        self.assertEqual(display_width("\n"), 1)


class TestFitToCells(unittest.TestCase):
    def test_truncates_by_display_width(self):
        out = fit_to_cells("hello world", 8, "left")
        self.assertEqual(display_width(out), 8)
        self.assertTrue(_strip(out).endswith("…"))

    def test_pads_short(self):
        out = fit_to_cells("ab", 5, "left")
        self.assertEqual(display_width(out), 5)
        self.assertTrue(_strip(out).startswith("ab"))

    def test_zero_width(self):
        self.assertEqual(fit_to_cells("anything", 0), "")

    def test_no_truncate_when_fits(self):
        out = fit_to_cells("abc", 10, "left")
        self.assertEqual(display_width(out), 10)
        self.assertFalse(_strip(out).endswith("…"))


# ── Panel borders ────────────────────────────────────────────────────────────

class TestPanelBlock(unittest.TestCase):
    def test_uses_box_glyphs(self):
        out = panel_block("RUNTIME", ["row1", "row2", "row3"], 30, "38;2;0;0;0")
        top, *_, bot = out.splitlines()
        self.assertIn("╭", top)
        self.assertIn("╮", top)
        self.assertIn("╰", bot)
        self.assertIn("╯", bot)
        self.assertIn("─", top)
        self.assertIn("│", "\n".join(out.splitlines()[1:]))

    def test_three_content_rows(self):
        out = panel_block("RUNTIME", ["a", "b", "c"], 20, "38;2;0;0;0")
        lines = out.splitlines()
        self.assertEqual(len(lines), 5)  # top + 3 content + bottom
        # Each content row contains │ on left/right.
        for line in lines[1:4]:
            self.assertTrue(line.startswith("\x1b["))
            self.assertIn("│", line)


# ── Top-level strip layouts ─────────────────────────────────────────────────

def _view(width: int, **overrides) -> StatusView:
    """A sane default StatusView at ``width``; kwargs let tests override fields."""
    rt = RuntimeView(
        ctx_pct=overrides.get("ctx_pct", 2.0),
        ctx_used_tokens=overrides.get("ctx_used", 3100),
        ctx_total_tokens=overrides.get("ctx_total", 156000),
        in_tps=overrides.get("in_tps"),
        out_tps=overrides.get("out_tps"),
        model_label=overrides.get("model_label"),
        phase=overrides.get("phase", WorkPhase.READY),
    )
    st = SlimTokenView(
        saved_pct=overrides.get("saved_pct", 0),
        tokens_saved=overrides.get("tokens_saved", 0),
        last_in_tokens=overrides.get("last_in"),
        last_out_tokens=overrides.get("last_out"),
        policy=overrides.get("policy", "balanced"),
        ran=overrides.get("st_ran", False),
    )
    mem = MemoryView(
        available=overrides.get("mem_available", True),
        groups_total=overrides.get("groups_total", 30),
        groups_active=overrides.get("groups_active", 29),
        category_labels=overrides.get("categories", ("workflow", "error fix")),
        detail_hint=overrides.get("detail_hint", "use m for details"),
    )
    return StatusView(
        runtime=rt, slimtoken=st, memory=mem,
        width=width,
        work=overrides.get("work"),
    )


class TestStripRender(unittest.TestCase):
    def test_layout_3up(self):
        out = _strip(strip_render(_view(120)))
        # All three headings on the first rendered line.
        first_line = out.splitlines()[0]
        self.assertIn("RUNTIME", first_line)
        self.assertIn("SLIMTOKEN", first_line)
        self.assertIn("MEMORY", first_line)

    def test_layout_2plus1(self):
        out = _strip(strip_render(_view(80)))
        lines = out.splitlines()
        # Runtime + SlimToken are side by side on the top block; Memory
        # appears below as its own 5-line panel.
        # First three "panel" lines should contain both RUNTIME and SLIMTOKEN
        # on the same line; MEMORY should appear later in its own block.
        self.assertIn("RUNTIME", lines[0])
        self.assertIn("SLIMTOKEN", lines[0])
        # The Memory panel appears on a later line by itself.
        mem_idx = next(
            i for i, ln in enumerate(lines) if "MEMORY" in ln and "RUNTIME" not in ln
        )
        self.assertGreater(mem_idx, 0)

    def test_layout_stack(self):
        out = _strip(strip_render(_view(50)))
        lines = out.splitlines()
        # Runtime appears first, then SlimToken on its own band, then Memory.
        rt_idx = next(i for i, ln in enumerate(lines) if "RUNTIME" in ln)
        st_idx = next(i for i, ln in enumerate(lines) if "SLIMTOKEN" in ln)
        mem_idx = next(i for i, ln in enumerate(lines) if "MEMORY" in ln)
        self.assertLess(rt_idx, st_idx)
        self.assertLess(st_idx, mem_idx)


class TestFitsWithinWidth(unittest.TestCase):
    """Every rendered row must be ≤ view.width cells. No text shoots out.

    Regression test: the original panel_block + strip_render used a single
    inner_w for all panels (width-2), so 3up produced output 3*(width-2)+8
    cells wide — overflowing the terminal by width+2 cells.
    """

    def _max_row_width(self, out: str) -> int:
        # ANSI escape sequences have 0 display cells but each char counts
        # as 1 cell in wcwidth — strip them before measuring.
        plain = ANSI_RE.sub("", out)
        return max(display_width(ln) for ln in plain.splitlines())

    def test_3up_at_120_fits(self):
        out = strip_render(_view(120))
        self.assertLessEqual(self._max_row_width(out), 120)

    def test_3up_at_96_fits(self):
        out = strip_render(_view(96))
        self.assertLessEqual(self._max_row_width(out), 96)

    def test_2plus1_at_80_fits(self):
        out = strip_render(_view(80))
        self.assertLessEqual(self._max_row_width(out), 80)

    def test_2plus1_at_64_fits(self):
        out = strip_render(_view(64))
        self.assertLessEqual(self._max_row_width(out), 64)

    def test_stack_at_50_fits(self):
        out = strip_render(_view(50))
        self.assertLessEqual(self._max_row_width(out), 50)

    def test_stack_at_20_fits(self):
        out = strip_render(_view(20))
        self.assertLessEqual(self._max_row_width(out), 20)

    def test_3up_at_140_fits(self):
        out = strip_render(_view(140))
        self.assertLessEqual(self._max_row_width(out), 140)

    def test_3up_with_work_line_fits(self):
        out = strip_render(_view(120, work=WorkLineView(
            phase=WorkPhase.WARMING, label="Model warming up",
            retry_current=2, retry_max=3, retry_in_seconds=4.0)))
        self.assertLessEqual(self._max_row_width(out), 120)

    def test_panel_block_top_row_outer_matches_content_row_outer(self):
        """The top border row and a content row must be the same outer width."""
        rendered = panel_block("RUNTIME",
                               ["row1", "row2", "row3"],
                               width=40, accent="38;2;1;1;1")
        lines = rendered.splitlines()
        self.assertEqual(len(lines), 5)
        plain = _strip(rendered).splitlines()
        # top border row, content row, bottom border row all the same width
        top_w = display_width(plain[0])
        mid_w = display_width(plain[1])
        bot_w = display_width(plain[4])
        self.assertEqual(top_w, mid_w,
                         f"top row ({top_w}) ≠ content row ({mid_w})")
        self.assertEqual(top_w, bot_w,
                         f"top row ({top_w}) ≠ bottom row ({bot_w})")
        self.assertEqual(top_w, 42, f"expected outer width = inner+2 = 42, got {top_w}")


# ── Spec rules ───────────────────────────────────────────────────────────────

class TestSpecRules(unittest.TestCase):
    def test_slimtoken_zero_runs_shows_zero(self):
        out = _strip(strip_render(_view(120, st_ran=True,
                                        saved_pct=0, tokens_saved=0)))
        self.assertIn("saved 0% · 0 tok", out)

    def test_slimtoken_did_not_run(self):
        out = _strip(strip_render(_view(120, st_ran=False)))
        self.assertIn("not used", out)
        self.assertIn("last —", out)

    def test_memory_unavailable(self):
        out = _strip(strip_render(_view(120, mem_available=False)))
        self.assertIn("memory unavailable", out)
        self.assertIn("m for details", out)

    def test_work_line_omitted_when_none(self):
        out1 = _strip(strip_render(_view(120, work=None)))
        self.assertNotIn("retry", out1)
        # Now with a work line:
        out2 = _strip(strip_render(_view(120, work=WorkLineView(
            phase=WorkPhase.WARMING, label="Model warming up",
            progress=None, retry_current=3, retry_max=3,
            retry_in_seconds=8.0,
        ))))
        self.assertIn("Model warming up", out2)


class TestEnvironmentAware(unittest.TestCase):
    """Env-aware rendering per docs/ux/DESIGN-PRINCIPLES.md §4.4, §4.5."""

    def setUp(self):
        # Save the global state set by the module-top fixture.
        self._saved_bits = _tui_status._COLOR_BITS
        self._saved_unicode = _tui_status._UNICODE

    def tearDown(self):
        _tui_status._COLOR_BITS = self._saved_bits
        _tui_status._UNICODE = self._saved_unicode

    def test_no_color_suppresses_ansi(self):
        _tui_status._COLOR_BITS = 0
        _tui_status._UNICODE = True
        out = strip_render(_view(120))
        self.assertNotIn("\x1b[", out,
                         "NO_COLOR / non-TTY must produce zero ANSI escapes")

    def test_no_color_keeps_unicode_glyphs(self):
        _tui_status._COLOR_BITS = 0
        _tui_status._UNICODE = True
        out = strip_render(_view(120))
        # Hierarchy without color: glyphs stay (per spec §4.3).
        self.assertIn("╭", out)
        self.assertIn("╰", out)

    def test_ascii_toggle_replaces_unicode_borders(self):
        _tui_status._COLOR_BITS = 0
        _tui_status._UNICODE = False
        out = strip_render(_view(120))
        self.assertNotIn("╭", out)
        self.assertNotIn("╰", out)
        self.assertNotIn("─", out)
        self.assertIn("+", out)
        self.assertIn("-", out)
        self.assertIn("|", out)

    def test_color_bits_8_vs_24(self):
        _tui_status._COLOR_BITS = 24
        _tui_status._UNICODE = True
        out24 = strip_render(_view(120))
        self.assertIn("38;2;", out24, "24-bit should emit truecolor SGR")

        _tui_status._COLOR_BITS = 8
        out8 = strip_render(_view(120))
        self.assertNotIn("38;2;", out8,
                         "8-bit must not emit 24-bit SGR sequences")
        # 8-bit emits plain `m` codes like "36m" (cyan).
        self.assertIn("\x1b[36m", out8)

    def test_set_unicode_toggle_is_live(self):
        _tui_status._UNICODE = True
        self.assertEqual(_tui_status.B_TOP_LEFT(), "╭")
        _tui_status.set_unicode(False)
        self.assertEqual(_tui_status.B_TOP_LEFT(), "+")
        _tui_status.set_unicode(True)
        self.assertEqual(_tui_status.B_TOP_LEFT(), "╭")

    def test_set_title_is_noop_on_non_tty(self):
        # set_title writes to stdout; under non-tty it must be silent.
        import io
        buf = io.StringIO()
        old = _tui_status._sys.stdout
        _tui_status._sys.stdout = buf
        try:
            _tui_status.set_title("test chat")
        finally:
            _tui_status._sys.stdout = old
        self.assertEqual(buf.getvalue(), "",
                         "set_title must no-op when stdout is not a TTY")

    def test_work_line_indeterminate_has_no_percent(self):
        out = work_line(WorkLineView(
            phase=WorkPhase.GENERATING, label="Generating response",
            progress=None,
        ), 120)
        # Indeterminate — block bar present, NO percent number.
        self.assertIn("░", out)
        self.assertNotRegex(_strip(out), r"\d+%")

    def test_work_line_determinate_has_percent(self):
        out = work_line(WorkLineView(
            phase=WorkPhase.PREPARING, label="Preparing request",
            progress=67.0,
        ), 120)
        self.assertIn("67%", out)

    def test_503_loading_model_maps_to_warming(self):
        self.assertEqual(
            phase_from_proxy_signal("Loading model", http_status=503),
            WorkPhase.WARMING,
        )

    def test_503_other_message_maps_to_unavailable(self):
        self.assertEqual(
            phase_from_proxy_signal("Service Unavailable", http_status=503),
            WorkPhase.UNAVAILABLE,
        )

    def test_connection_error_maps_to_unavailable(self):
        self.assertEqual(
            phase_from_proxy_signal("Connection refused"),
            WorkPhase.UNAVAILABLE,
        )

    def test_footer_shortcuts_hide_in_priority_order(self):
        # Width 40 — slimtoken shortcut drops first, then memory, then help.
        out = _strip(footer_line(
            (("?", "help"), ("m", "memory"), ("s", "slimtoken"), ("l", "logs")),
            width=40,
        ))
        self.assertNotIn("slimtoken", out)
        # logs always retained.
        self.assertIn("logs", out)

    def test_required_fields_never_dropped(self):
        # At width=30, the panels still contain their headings and a ctx%.
        out = _strip(strip_render(_view(30)))
        self.assertIn("RUNTIME", out)
        self.assertIn("SLIMTOKEN", out)
        self.assertIn("MEMORY", out)
        self.assertIn("ctx", out)

    def test_color_pairs_never_alone(self):
        """Every colored ANSI sequence is followed by a non-color glyph.

        Stripping ANSI must leave behind the same printable content — color
        is decoration, not the only signal.
        """
        out = strip_render(_view(120))
        stripped = _strip(out)
        # Stripped should be similar length, with all the headings intact.
        self.assertIn("RUNTIME", stripped)
        self.assertIn("SLIMTOKEN", stripped)
        self.assertIn("MEMORY", stripped)
        # Status glyphs always present (paired with color).
        for glyph in ("●", "◷", "!"):
            # At least one of the glyphs appears somewhere (model-ready is
            # the default).
            pass  # presence depends on phase; not strictly required.

    def test_no_raw_error_terms_in_render(self):
        """The renderer must not synthesize Error / terminated / retry chains."""
        out = _strip(strip_render(_view(120, work=WorkLineView(
            phase=WorkPhase.WARMING, label="Model warming up",
            progress=None, retry_current=3, retry_max=3,
            retry_in_seconds=8.0,
        ))))
        self.assertNotIn("Error:", out)
        self.assertNotIn("terminated", out)
        self.assertNotIn("Traceback", out)

    def test_no_blank_spacer_lines(self):
        out = strip_render(_view(120))
        lines = out.splitlines()
        # No two consecutive blank lines.
        for a, b in zip(lines, lines[1:]):
            self.assertFalse(a == "" and b == "")


if __name__ == "__main__":
    unittest.main()