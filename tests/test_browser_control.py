#!/usr/bin/env python3

from __future__ import annotations

import json
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


class _FakeHTTPJson:


    def __init__(self, tabs: List[Dict[str, Any]]):
        self.tabs = tabs
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, path: str) -> Any:
        with self.lock:
            self.calls += 1
        if path == "/json":
            return list(self.tabs)
        if path == "/json/version":
            return {"Browser": "Chrome/test"}
        return {}


def _make_tab(target_id: str, url: str = "https://example.com",
              title: str = "Example") -> Dict[str, Any]:
    return {"id": target_id, "type": "page",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
            "title": title, "url": url}


class TabsCacheTests(unittest.TestCase):
    def setUp(self) -> None:

        bc.close()
        self._fake = _FakeHTTPJson([_make_tab("T1"), _make_tab("T2", "https://b.test")])
        self._patch = mock.patch.object(bc, "_http_json", self._fake)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        bc.close()

    def test_first_call_hits_json(self) -> None:
        bc.list_tabs()
        self.assertEqual(self._fake.calls, 1)

    def test_burst_within_ttl_hits_json_once(self) -> None:
        for _ in range(5):
            bc.list_tabs()
        self.assertEqual(self._fake.calls, 1)

    def test_after_ttl_refetches(self) -> None:
        bc.list_tabs()

        bc._tabs_cache_at -= (bc._TABS_TTL_SEC + 0.1)
        bc.list_tabs()
        self.assertEqual(self._fake.calls, 2)

    def test_new_tab_invalidates_cache(self) -> None:
        bc.list_tabs()
        self.assertEqual(self._fake.calls, 1)

        bc._invalidate_tabs_cache()
        bc.list_tabs()
        self.assertEqual(self._fake.calls, 2)


class PerTargetLockTests(unittest.TestCase):
    def setUp(self) -> None:
        bc.close()

    def test_same_target_returns_same_lock(self) -> None:
        a = bc._lock_for("T1")
        b = bc._lock_for("T1")
        self.assertIs(a, b)

    def test_different_targets_return_different_locks(self) -> None:
        a = bc._lock_for("T1")
        b = bc._lock_for("T2")
        self.assertIsNot(a, b)

    def test_concurrent_first_touch_is_safe(self) -> None:


        target = "TRACE"
        start = threading.Event()
        threads = [threading.Thread(target=lambda: (start.wait(), bc._lock_for(target)))
                   for _ in range(50)]
        for t in threads: t.start()
        start.set()
        for t in threads: t.join()
        self.assertEqual(len(bc._target_locks), 1)
        self.assertIn(target, bc._target_locks)

    def test_close_clears_per_target_locks(self) -> None:
        bc._lock_for("T1")
        bc._lock_for("T2")
        self.assertEqual(len(bc._target_locks), 2)
        bc.close()
        self.assertEqual(len(bc._target_locks), 0)


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        bc.close()
        self._fake = _FakeHTTPJson([_make_tab("T1")])
        self._patch = mock.patch.object(bc, "_http_json", self._fake)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        bc.close()

    def test_health_shape(self) -> None:


        version_resp = mock.Mock()
        version_resp.read = lambda: json.dumps({"Browser": "Chrome/test"}).encode()
        version_resp.__enter__ = lambda s: s
        version_resp.__exit__ = lambda s, *a: False
        with mock.patch.object(bc.urllib.request, "urlopen", return_value=version_resp):
            h = bc.health()
        for key in ("calls", "reconnects", "json_fetches", "retries",
                    "failures", "last_call_ms", "uptime_sec",
                    "cached_sockets", "cached_tab_list_age_ms",
                    "cdp_reachable", "browser"):
            self.assertIn(key, h, f"missing key: {key}")
        self.assertTrue(h["cdp_reachable"])
        self.assertEqual(h["browser"], "Chrome/test")

    def test_health_never_raises_on_bad_endpoint(self) -> None:
        with mock.patch.object(bc.urllib.request, "urlopen",
                               side_effect=RuntimeError("CDP down")):
            h = bc.health()
        self.assertFalse(h["cdp_reachable"])
        self.assertIn("cdp_error", h)
        self.assertIn("CDP down", h["cdp_error"])

    def test_counters_monotonic(self) -> None:
        version_resp = mock.Mock()
        version_resp.read = lambda: json.dumps({"Browser": "Chrome/test"}).encode()
        version_resp.__enter__ = lambda s: s
        version_resp.__exit__ = lambda s, *a: False
        with mock.patch.object(bc.urllib.request, "urlopen", return_value=version_resp):
            before = bc.health()
            bc.list_tabs()
            bc.list_tabs()
            after = bc.health()
        self.assertGreaterEqual(after["json_fetches"], before["json_fetches"])
        self.assertGreaterEqual(after["calls"], before["calls"])
        self.assertGreaterEqual(after["last_call_ms"], 0.0)


class ResolveTabFallbackTests(unittest.TestCase):


    def setUp(self) -> None:
        bc.close()
        self._fake = _FakeHTTPJson([
            _make_tab("ALPHA", "https://a.test"),
            _make_tab("BETA", "https://b.test"),
            _make_tab("GAMMA", "https://g.test"),
        ])
        self._patch = mock.patch.object(bc, "_http_json", self._fake)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        bc.close()

    def test_none_returns_first(self) -> None:
        self.assertEqual(bc.resolve_tab(None), "ALPHA")

    def test_int_index(self) -> None:
        self.assertEqual(bc.resolve_tab(1), "BETA")
        self.assertEqual(bc.resolve_tab(99), "ALPHA")

    def test_url_prefix(self) -> None:
        self.assertEqual(bc.resolve_tab("https://g.test"), "GAMMA")

    def test_unknown_string_falls_back_to_first(self) -> None:
        self.assertEqual(bc.resolve_tab("https://nope.test"), "ALPHA")

    def test_target_id_passthrough(self) -> None:
        self.assertEqual(bc.resolve_tab("BETA"), "BETA")

    def test_no_tabs_raises(self) -> None:
        with mock.patch.object(bc, "_http_json", _FakeHTTPJson([])):
            with self.assertRaises(RuntimeError):
                bc.resolve_tab(None)


class CloseHygieneTests(unittest.TestCase):
    def test_close_is_idempotent(self) -> None:
        bc.close()
        bc.close()
        self.assertEqual(bc._ws_cache, {})
        self.assertEqual(bc._id_counter, {})
        self.assertEqual(bc._tabs_cache, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
