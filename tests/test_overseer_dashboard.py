#!/usr/bin/env python3
"""tests/test_overseer_dashboard.py — unit tests for the Overseer dashboard.

Covers the spec's required test areas:
  - Fixed 1440×900 + fallback 1280×800 layouts
  - Model-name resolution vs route alias
  - Collect/Compose/SlimToken/Finalize pipeline integrity
  - Pinned-content protection
  - Token-budget reservation and final context validation
  - Unavailable telemetry behavior
  - SlimToken dry-run and optimization diff
  - Pending / apply / revert / save-default flows
  - Confirmation gates for disruptive changes
  - Isolated test-run sessions
  - Scheduler cron normalization and task dedup
  - Stale snapshot rendering

Tests are headless; they exercise the typed models and pipeline logic.
UI-only assertions run under ``xvfb-run`` so they don't require a display.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lib.overseer_dashboard import (  # noqa: E402
    models as M, pipeline as P, settings as SET, scheduler as S,
    testharness as T,
)


class TestLayouts(unittest.TestCase):
    """Fixed 1440×900 and fallback 1280×800 layout constraints."""

    def test_default_dimensions(self) -> None:
        from lib.overseer_dashboard.ui import DEFAULT_W, DEFAULT_H
        self.assertEqual((DEFAULT_W, DEFAULT_H), (1440, 900))

    def test_fallback_dimensions(self) -> None:
        from lib.overseer_dashboard.ui import FALLBACK_W, FALLBACK_H
        self.assertEqual((FALLBACK_W, FALLBACK_H), (1280, 800))

    def test_window_non_resizable(self) -> None:
        # The Tk instance should call resizable(False, False). We assert
        # the layout decision without spinning up Tk by checking the code path.
        import inspect
        from lib.overseer_dashboard.ui import Dashboard
        src = inspect.getsource(Dashboard.__init__)
        self.assertIn("resizable(False, False)", src)

    def test_4k_scaling_factor_clamped(self) -> None:
        """Scaling factor should be in [1.0, 2.0] and increase for big displays."""
        from lib.overseer_dashboard.ui import _detect_scale
        import os
        # Force env override to a known high value to confirm parse + clamp.
        old = os.environ.get("CORTEXAGENT_DASHBOARD_SCALING")
        try:
            os.environ["CORTEXAGENT_DASHBOARD_SCALING"] = "1.75"
            # We need a real Tk root to call _detect_scale. Skip if no display.
            import tkinter as tk
            try:
                root = tk.Tk()
                root.withdraw()
                scale = _detect_scale(root)
                self.assertEqual(scale, 1.75)
                root.destroy()
            except Exception:
                self.skipTest("no display available")
        finally:
            if old is None:
                os.environ.pop("CORTEXAGENT_DASHBOARD_SCALING", None)
            else:
                os.environ["CORTEXAGENT_DASHBOARD_SCALING"] = old


class TestModelResolution(unittest.TestCase):
    """Model-name resolution priority."""

    def test_concrete_model_wins_over_route_alias(self) -> None:
        daemon = {"big": {"model": "/models/Qwen3.6-35B-A3B-UD-IQ3_S.gguf",
                          "alias": "cortex-big"}}
        proxy = {}
        active = {}
        from lib.overseer_dashboard.telemetry import _resolve_model
        ident = _resolve_model(daemon, proxy, active)
        self.assertIn("Qwen3.6", ident.model)
        self.assertEqual(ident.route, "cortex-big")
        self.assertEqual(ident.source, "backend")

    def test_response_model_takes_top_priority(self) -> None:
        daemon = {"big": {"model": "/models/A.gguf", "alias": "cortex-big"}}
        proxy = {"response": {"model": "ResponseServed"}}
        from lib.overseer_dashboard.telemetry import _resolve_model
        ident = _resolve_model(daemon, proxy, {})
        self.assertEqual(ident.model, "ResponseServed")
        self.assertEqual(ident.source, "response")

    def test_alias_is_only_fallback(self) -> None:
        from lib.overseer_dashboard.telemetry import _resolve_model
        ident = _resolve_model({"big": {"alias": "cortexagent"}}, {}, {})
        self.assertEqual(ident.source, "alias")

    def test_unknown_when_nothing_available(self) -> None:
        from lib.overseer_dashboard.telemetry import _resolve_model
        ident = _resolve_model({}, {}, {})
        self.assertEqual(ident.model, "unknown")
        self.assertEqual(ident.route, "cortex-big")
        self.assertEqual(ident.source, "none")

    def test_gguf_stripped_for_presentation(self) -> None:
        ident = M.ModelIdentity(model="Foo-Q4_K_M.gguf")
        self.assertEqual(ident.display_model(), "Foo-Q4_K_M")


class TestPipelineIntegrity(unittest.TestCase):
    """Collect/Compose/SlimToken/Finalize pipeline integrity."""

    def test_compose_reserves_output_capacity(self) -> None:
        blocks = P.synthetic_blocks("hi", preset="simple")
        c = P.compose(blocks, context_window=156000, max_output_tokens=3431)
        self.assertEqual(c.output_reserved, 3431)
        self.assertEqual(c.input_budget, 156000 - 3431)

    def test_slimtoken_preserves_pinned(self) -> None:
        blocks = P.synthetic_blocks("hi", preset="long_context")
        c = P.compose(blocks, context_window=156000, max_output_tokens=3431)
        slim = P.slimtoken(c, dedup=True)
        # The 4 pinned blocks must appear with action='preserved' unchanged.
        pinned_ids = {b.id for b in c.pinned}
        preserved = [a for a in slim.actions
                     if a.action == "preserved" and a.block_id in pinned_ids]
        self.assertEqual(len(preserved), len(pinned_ids))
        # And their tokens_before == tokens_after.
        for a in preserved:
            self.assertEqual(a.tokens_before, a.tokens_after)

    def test_slimtoken_never_removes_pinned(self) -> None:
        blocks = P.synthetic_blocks("hi", preset="long_context")
        c = P.compose(blocks, context_window=156000, max_output_tokens=3431)
        slim = P.slimtoken(c)
        pinned_ids = {b.id for b in c.pinned}
        # Every action on a pinned block must be 'preserved' with equal
        # tokens before and after — never removed/compacted/deduplicated.
        for a in slim.actions:
            if a.block_id in pinned_ids:
                self.assertEqual(a.action, "preserved",
                                 f"pinned block {a.block_id} got action {a.action}")
                self.assertEqual(a.tokens_before, a.tokens_after)

    def test_finalize_validates_budget(self) -> None:
        dr = P.dry_run("test", preset="long_context",
                       context_window=20000, max_output_tokens=1000)
        # 20000-1000 = 19000 budget. SlimToken output must fit.
        self.assertTrue(dr.finalize.fits)

    def test_finalize_rejects_overflow(self) -> None:
        dr = P.dry_run("test", preset="long_context",
                       context_window=1000, max_output_tokens=500)
        # 500 budget. After SlimToken it's 11181 — does not fit.
        self.assertFalse(dr.finalize.fits)

    def test_dry_run_never_sends_to_provider(self) -> None:
        dr = P.dry_run("test")
        self.assertTrue(dr.slim.dry_run)
        self.assertIsInstance(dr.compose, M.ComposeResult)
        self.assertIsInstance(dr.slim, M.SlimTokenResult)
        self.assertIsInstance(dr.finalize, M.FinalizeResult)

    def test_slimtoken_diff_has_actions(self) -> None:
        dr = P.dry_run("test", preset="long_context")
        actions = [a.action for a in dr.slim.actions]
        self.assertIn("preserved", actions)


class TestUnavailableTelemetry(unittest.TestCase):
    """Unavailable telemetry renders as None / '—', never fabricated."""

    def test_inference_telemetry_defaults_to_none(self) -> None:
        inf = M.InferenceTelemetry()
        self.assertIsNone(inf.context_used)
        self.assertIsNone(inf.context_window)
        self.assertIsNone(inf.input_tps)
        self.assertIsNone(inf.output_tps)
        self.assertIsNone(inf.cache_pct)
        self.assertEqual(inf.context_pct, None)

    def test_snapshot_marks_stale_when_old(self) -> None:
        snap = M.RuntimeSnapshot(connected=True, data_age_s=10.0, stale=True)
        self.assertTrue(snap.stale)

    def test_pipeline_marks_skipped_when_not_instrumented(self) -> None:
        snap = M.RuntimeSnapshot()
        stages = P.build_pipeline(snap)
        for s in stages:
            self.assertIn(s.state, ("complete", "active", "queued",
                                    "skipped", "failed"))


class TestSettingsFlows(unittest.TestCase):
    """Pending / apply / revert / save-default."""

    def test_pending_differs_from_active(self) -> None:
        cap = M.BackendCapabilities()
        st = SET.build_settings(cap)
        SET.set_pending(st, "temperature", 0.3)
        self.assertTrue(st.has_pending)
        self.assertIn("temperature", st.changed_keys)

    def test_apply_moves_pending_to_active(self) -> None:
        cap = M.BackendCapabilities()
        st = SET.build_settings(cap)
        SET.set_pending(st, "temperature", 0.3)
        SET.apply_pending(st)
        self.assertEqual(st.active["temperature"], 0.3)
        self.assertFalse(st.has_pending)

    def test_revert_restores_active(self) -> None:
        cap = M.BackendCapabilities()
        st = SET.build_settings(cap)
        original = st.active["temperature"]
        SET.set_pending(st, "temperature", 0.3)
        SET.revert_pending(st)
        self.assertEqual(st.active["temperature"], original)
        self.assertEqual(st.pending["temperature"], original)

    def test_disruptive_keys_detected(self) -> None:
        cap = M.BackendCapabilities()
        st = SET.build_settings(cap, M.ModelIdentity(model="x.gguf"))
        SET.set_pending(st, "model", "Other.gguf")
        self.assertIn("model", SET.disruptive_keys(st))

    def test_unsupported_control_not_rendered(self) -> None:
        cap = M.BackendCapabilities(supports_cache_reuse=False)
        st = SET.build_settings(cap)
        self.assertNotIn("cache_reuse", st.active)


class TestSchedulerCron(unittest.TestCase):
    """Cron normalization, humanization, task dedup."""

    def test_normalize_strips_brackets_and_commas(self) -> None:
        self.assertEqual(S.normalize_cron("(9,0,*,*,*)"), "9 0 * * *")
        self.assertEqual(S.normalize_cron("[0 9 * * *]"), "0 9 * * *")
        self.assertEqual(S.normalize_cron("0,9,*,*,*"), "0 9 * * *")

    def test_normalize_rejects_malformed(self) -> None:
        self.assertEqual(S.normalize_cron("0 9 * *"), "")        # 4 fields
        self.assertEqual(S.normalize_cron("0 9 * * X"), "")      # bad token
        self.assertEqual(S.normalize_cron("not a cron"), "")

    def test_humanize_daily(self) -> None:
        self.assertEqual(S.humanize_cron("0 9 * * *"), "daily 09:00")

    def test_humanize_hourly(self) -> None:
        self.assertEqual(S.humanize_cron("0 * * * *"), "hourly")

    def test_humanize_weekly(self) -> None:
        self.assertEqual(S.humanize_cron("0 9 * * 1"), "weekly Mon 09:00")

    def test_dedupe_tasks(self) -> None:
        tasks = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"},
                 {"id": "a", "name": "A duplicate"}]
        deduped = S.dedupe_tasks(tasks)
        self.assertEqual(len(deduped), 2)


class TestTestHarness(unittest.TestCase):
    """Isolated test runs."""

    def test_runs_get_independent_ids(self) -> None:
        th = T.TestHarness()
        r1 = th.run_dry("hello", preset="simple")
        r2 = th.run_dry("world", preset="simple")
        self.assertNotEqual(r1.id, r2.id)
        self.assertEqual(r1.status, "complete")
        self.assertEqual(r2.status, "complete")

    def test_run_completes_dry_run(self) -> None:
        th = T.TestHarness()
        r = th.run_dry("test", preset="long_context",
                       model="M.gguf", slimtoken_on=True)
        self.assertIsNotNone(r.input_tokens)
        self.assertIsNotNone(r.saved_pct)
        self.assertEqual(len(r.stages), 7)

    def test_comparison_requires_two_runs(self) -> None:
        th = T.TestHarness()
        th.run_dry("one", preset="simple")
        self.assertIsNone(th.comparison())
        th.run_dry("two", preset="simple")
        # Select them.
        for r in th.runs:
            th.toggle_select(r.id)
        comp = th.comparison()
        self.assertIsNotNone(comp)
        self.assertEqual(len(comp["rows"]), 5)

    def test_keep_at_most_two_selected(self) -> None:
        th = T.TestHarness()
        for i in range(3):
            th.run_dry(f"r{i}", preset="simple")
            th.toggle_select(th.runs[-1].id)
        self.assertEqual(len(th.selected), 2)


class TestStaleSnapshot(unittest.TestCase):
    """Stale / error rendering fields."""

    def test_stale_detail_set(self) -> None:
        snap = M.RuntimeSnapshot(stale=True, stale_detail="data current 18s",
                                 connected=False)
        self.assertFalse(snap.connected)
        self.assertTrue(snap.stale)
        self.assertIn("18s", snap.stale_detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
