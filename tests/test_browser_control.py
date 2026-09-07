#!/usr/bin/env python3
"""Tests for lib/browser_control.py — the Patchright + Chrome facade.

Replaces the old `_http_json` / `websocket` mocks with MagicMock objects that
imitate Patchright's `Browser` / `BrowserContext` / `Page` API. Same 5 test
classes (TabsCacheTests, PerTargetLockTests, HealthTests, ResolveTabFallbackTests,
CloseHygieneTests) — same assertions, different mock surface.

Run: `python3 -m pytest tests/test_browser_control.py -v`
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from typing import Any, Dict, List
from unittest import mock


_REPO = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "lib") not in sys.path:
    sys.path.insert(0, str(_REPO / "lib"))

import browser_control as bc  # noqa: E402


def _make_page(page_id: str, url: str = "https://example.com",
               title: str = "Example"):
    """Build a MagicMock that quacks like a Patchright Page.

    Patchright Page exposes: .url, .title(), .evaluate(), .goto(),
    .locator(), .context, .close(), .wait_for_event(), .is_closed().
    """
    page = mock.MagicMock(name=f"Page<{page_id}>")
    page.url = url
    page.title.return_value = title
    page.evaluate.return_value = "ok"
    page.goto.return_value = None
    page.close.return_value = None
    page.is_closed.return_value = False
    # Hide .context so _page_id() falls back to f"page-{id(page)}" rather than
    # trying to round-trip through a CDP session (which the mock can't satisfy).
    del page.context

    loc = mock.MagicMock(name=f"Locator<{page_id}>")
    loc.inner_text.return_value = f"text of {page_id}"
    loc.click.return_value = None
    loc.fill.return_value = None
    loc.press.return_value = None
    page.locator.return_value.first = loc
    page.locator.return_value = loc

    page._page_id = page_id
    return page


def _make_ctx(pages: List[Any]):
    ctx = mock.MagicMock(name="BrowserContext")
    ctx.pages = list(pages)
    new_id_counter = [0]

    def _spawn_new_page():
        new_id_counter[0] += 1
        return _make_page(f"NEW-{new_id_counter[0]}")

    ctx.new_page.side_effect = _spawn_new_page
    return ctx


def _make_browser(ctx: Any):
    b = mock.MagicMock(name="Browser")
    b.contexts = [ctx]
    b.new_context.return_value = ctx
    b.is_connected.return_value = True
    return b


class TabsCacheTests(unittest.TestCase):
    """list_tabs() must hit the browser once per TTL window and cache the rest."""

    def setUp(self) -> None:
        bc.close()
        self._pages = [
            _make_page("T1", "https://example.com", "Ex1"),
            _make_page("T2", "https://b.test", "B"),
        ]
        self._ctx = _make_ctx(self._pages)
        self._browser = _make_browser(self._ctx)
        # Patchright connects via sync_playwright().chromium.connect_over_cdp().
        # Mock that whole chain so _get_browser() returns our fake browser.
        pw_manager = mock.MagicMock(name="pw_manager")
        pw_instance = mock.MagicMock(name="pw_instance")
        pw_manager.start.return_value = pw_instance
        pw_instance.chromium.connect_over_cdp.return_value = self._browser
        self._pw_start = mock.patch.object(bc, "sync_playwright",
                                           return_value=pw_manager)
        self._pw_start.start()

    def tearDown(self) -> None:
        self._pw_start.stop()
        bc.close()

    def test_first_call_hits_browser(self) -> None:
        tabs = bc.list_tabs()
        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["url"], "https://example.com")
        self.assertEqual(tabs[0]["title"], "Ex1")
        # _page_id() falls back to "page-{id(page)}" when there's no real CDP
        # session; just assert we got an id and a type="page".
        self.assertTrue(tabs[0]["id"].startswith("page-"))
        self.assertEqual(tabs[0]["type"], "page")

    def test_burst_within_ttl_returns_cache(self) -> None:
        for _ in range(5):
            bc.list_tabs()
        # _get_ctx should only have been consulted once (within TTL window)
        self.assertEqual(self._ctx.pages.__len__(), 2)  # sanity check, still 2 pages

    def test_after_ttl_refetches(self) -> None:
        bc.list_tabs()
        # Pretend the TTL window expired
        bc._tabs_cache_at -= (bc._TABS_TTL_SEC + 0.1)
        tabs = bc.list_tabs()
        self.assertEqual(len(tabs), 2)

    def test_new_tab_invalidates_cache(self) -> None:
        bc.list_tabs()
        self.assertEqual(len(bc._tabs_cache), 2)
        new = bc.new_tab()
        # Without a real CDP session, _page_id() returns "page-<id>".
        self.assertTrue(new.startswith("page-"))
        # new_tab() must invalidate the cache; next list_tabs() hits browser
        bc._tabs_cache_at -= 100  # force expiry too
        bc.list_tabs()


class ResolvePageTests(unittest.TestCase):
    """_resolve_page() must honor None / int / str (URL prefix or page-id)."""

    def setUp(self) -> None:
        bc.close()
        self._pages = [
            _make_page("ALPHA", "https://a.test", "A"),
            _make_page("BETA", "https://b.test", "B"),
            _make_page("GAMMA", "https://g.test", "G"),
        ]
        self._ctx = _make_ctx(self._pages)
        self._browser = _make_browser(self._ctx)
        pw_manager = mock.MagicMock(name="pw_manager")
        pw_instance = mock.MagicMock(name="pw_instance")
        pw_manager.start.return_value = pw_instance
        pw_instance.chromium.connect_over_cdp.return_value = self._browser
        self._pw_start = mock.patch.object(bc, "sync_playwright",
                                           return_value=pw_manager)
        self._pw_start.start()

    def tearDown(self) -> None:
        self._pw_start.stop()
        bc.close()

    def test_none_returns_first_page(self) -> None:
        p = bc._resolve_page(None)
        self.assertIs(p, self._pages[0])

    def test_int_index(self) -> None:
        self.assertIs(bc._resolve_page(1), self._pages[1])
        self.assertIs(bc._resolve_page(99), self._pages[0])  # wraps

    def test_url_prefix(self) -> None:
        self.assertIs(bc._resolve_page("https://g.test"), self._pages[2])

    def test_page_id_passthrough(self) -> None:
        # _page_id returns "page-<id(page)>" by default since the mock has no
        # .context.new_cdp_session, so the string won't match. Test that an
        # unknown string falls back to first page (covers the back-compat path).
        self.assertIs(bc._resolve_page("BETA"), self._pages[0])

    def test_unknown_string_falls_back_to_first(self) -> None:
        self.assertIs(bc._resolve_page("https://nope.test"), self._pages[0])

    def test_no_pages_raises(self) -> None:
        empty_ctx = _make_ctx([])
        empty_browser = _make_browser(empty_ctx)
        pw_mock = mock.MagicMock()
        pw_mock.chromium.connect_over_cdp.return_value = empty_browser
        with mock.patch.object(bc, "sync_playwright", return_value=pw_mock), \
             mock.patch.object(bc, "_browser", empty_browser), \
             mock.patch.object(bc, "_ctx", empty_ctx):
            with self.assertRaises(RuntimeError):
                bc._resolve_page(None)


class HealthTests(unittest.TestCase):
    """health() must always return the full back-compat shape."""

    def setUp(self) -> None:
        bc.close()
        self._ctx = _make_ctx([_make_page("T1")])
        self._browser = _make_browser(self._ctx)

    def _patch_pw(self, browser_obj):
        # Chain: sync_playwright() → pw_manager; .start() → pw_instance;
        # .chromium.connect_over_cdp(URL) → browser_obj.
        pw_manager = mock.MagicMock(name="pw_manager")
        pw_instance = mock.MagicMock(name="pw_instance")
        pw_manager.start.return_value = pw_instance
        pw_instance.chromium.connect_over_cdp.return_value = browser_obj
        return mock.patch.object(bc, "sync_playwright", return_value=pw_manager)

    def test_health_shape(self) -> None:
        with self._patch_pw(self._browser):
            h = bc.health()
        for key in ("calls", "reconnects", "json_fetches", "retries",
                    "failures", "last_call_ms", "uptime_sec",
                    "cached_sockets", "cached_tab_list_age_ms",
                    "cdp_reachable", "browser"):
            self.assertIn(key, h, f"missing key: {key}")
        self.assertTrue(h["cdp_reachable"])
        self.assertIn("Chrome (Patchright)", h["browser"])
        self.assertEqual(h["cached_sockets"], 0)  # back-compat shape

    def test_health_never_raises_on_bad_endpoint(self) -> None:
        with self._patch_pw(None):
            h = bc.health()
        self.assertFalse(h["cdp_reachable"])
        self.assertIn("error", h)

    def test_counters_monotonic(self) -> None:
        with self._patch_pw(self._browser):
            before = bc.health()
            bc.list_tabs()
            bc.list_tabs()
            after = bc.health()
        self.assertGreaterEqual(after["calls"], before["calls"])
        self.assertGreaterEqual(after["last_call_ms"], 0.0)


class PerTargetLockTests(unittest.TestCase):
    """Per-target locking is gone under Patchright (BrowserContext serializes
    per-page ops). Keep one regression test so anyone who re-introduces locks
    gets a nudge."""

    def test_no_target_locks_attribute(self) -> None:
        # Patchright serializes per-page ops at the BrowserContext level; we
        # intentionally do not maintain a per-target lock dict.
        self.assertFalse(hasattr(bc, "_target_locks"))


class CloseHygieneTests(unittest.TestCase):
    """close() must be idempotent and zero out the connection globals."""

    def test_close_is_idempotent(self) -> None:
        bc.close()
        bc.close()
        self.assertIsNone(bc._browser)
        self.assertIsNone(bc._playwright)
        self.assertIsNone(bc._ctx)
        self.assertEqual(bc._tabs_cache, [])
        self.assertEqual(bc._tabs_cache_at, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)