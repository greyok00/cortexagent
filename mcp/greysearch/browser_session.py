#!/usr/bin/env python3
"""browser_session.py - the single connection owner for the slot browser.

The browser is a patchright-launched stealth Chromium (headless), bound to
this process's assigned task slot: port/profile resolved from RESEARCH_TASK
via browser_ports (slot assignment is automatic; a slot a live sibling
process holds is never taken). Every fetch in this process, from deep-run
pages to one-URL scrapes and fallback-lane browsing, attaches to that ONE
browser over CDP through the cached connection here. Connections are cached
per thread (playwright sync objects are greenlet/thread-bound); dropping a
connection only drops the CDP client; the browser and its tabs stay up.
Nothing here calls page.close()/context.close()/browser.close().

fetch_text() is the full-fidelity fetch core (single source of extraction):
paragraphs preserved, links/images/videos/tables/headings/code/audios/pdfs
populated from the SAME page object, injection scan on the body, honest
ok/status_code, and no silent truncation; max_chars is honored only when a
caller passes one. Extraction constants are imported from patchright_scraper
so there is exactly one definition of each extractor.

CAPTCHA WAIT: fetch_text honors a wait-the-solver contract instead of a
silent accept: one read of the page's captcha state
(recaptcha/hcaptcha/turnstile widget iframes, the empty response fields
those widgets feed, and interstitial text like "unusual traffic", "Just a
moment", or the searx.space Anubis bot-check "making sure you're not a bot")
and, when such state is present, ONE bounded wait then ONE
more of the same length, reading solve evidence every poll (the response
token filled, or every widget and interstitial marker gone); then either
proceed normally (the mark rides the fetch metadata) or fail honestly with
"captcha persisted after solver wait + bounded retry (...)" so the scrape
lane records an honest skip. Never loops past the two phases, so the worst
added wall per captcha'd page is the sum of the two wait lengths plus one
poll each and the waits land inside the caller's own deadline, as any
other fetch does.
Knobs, read at call time so tests and lanes can set them: the two wait
lengths come from GREYSEARCH_CAPTCHA_WAIT_MIN_S (default 30, the first
wait) and GREYSEARCH_CAPTCHA_WAIT_MAX_S (default 60, the second wait; the
two-phase 30-60 s design replaced the old single-length default);
the older GREYSEARCH_CAPTCHA_WAIT_S, when set, pins both waits to its one
length (default 45; 0 or negative keeps the immediate-fail behavior where
present captcha marks persist without waiting);
GREYSEARCH_CAPTCHA_POLL_S (default 5, the read interval inside a wait;
real wait phases also stay inside their length). Every WAIT and SOLVE
decision in the lane runs behind GREYSEARCH_CAPTCHA_SOLVER (off/0/false
means the local solver is never consulted; the wait itself stays bounded
and honest either way), set in the one place, captcha_solve. The singleton
read functions here are the ONE definition every driver shares, so the
browser search lane and the page scrapes wait on the same evidence.
LOCAL SOLVER: when the bounded wait leaves a page captcha'd anyway,
fetch_text (and the search lane's cycle wrapper through searx_fallback)
takes the local captcha_solve module's ONE solver step (captcha_solver_step
here). The step does nothing unless GREYSEARCH_CAPTCHA_SOLVER allows, and
its answer carries only when a bounded re-wait of the MIN phase length
(GREYSEARCH_CAPTCHA_WAIT_MIN_S) then sees the challenge lifted - the
re-wait's result governs, not the solver's word. The solver's honest note
rides the record as a NEW metadata key ("captcha_solved" on a proceed, or
"captcha_skip" on the persisted skip) without touching the persisted
wording, and every solver failure degrades to the pre-solver behavior
exactly.

BROWSER SEARCH PACE: browser-lane SEARCH requests to ONE engine keep a
human spacing in this process, GREYSEARCH_BROWSER_PACE_S (default 30, floor 1) plus
0-GREYSEARCH_BROWSER_PACE_JITTER_S (default 15) between two same-engine
requests. The guard is browser_pace_wait: a sleep only when this engine
already saw a search request in this process, never before the first and
never around page fetches (page fetches keep their own politeness and
never touch the guard). Exactly 0 is the inert bypass tests and emergency
runs use; the caller records a nonzero wait in its lane's digest.
"""
from __future__ import annotations

import atexit
import math
import os
import random
import re
import threading
import time
import urllib.request
from contextlib import contextmanager
from typing import Any, Dict, Optional

try:
    from . import browser_ports
except ImportError:
    import browser_ports

import proxy_mode as _proxy_mode

try:
    from .patchright_scraper import (
        _HTML_CAP, _SCROLL_JS, _LINKS_JS, _IMAGES_JS, _VIDEO_TAG_JS,
        _IFRAME_VIDEO_JS, _TABLES_JS, _HEADINGS_JS, _CODE_JS, _META_JS,
        _AUDIO_JS, _PDF_JS, _CANVAS_JS, _IFRAME_JS, _BOILER_LINES,
        _BOILER_INLINE, wayback_rescue, wayback_dead_status,
    )
    from . import research_injection as _rij
except ImportError:
    from patchright_scraper import (
        _HTML_CAP, _SCROLL_JS, _LINKS_JS, _IMAGES_JS, _VIDEO_TAG_JS,
        _IFRAME_VIDEO_JS, _TABLES_JS, _HEADINGS_JS, _CODE_JS, _META_JS,
        _AUDIO_JS, _PDF_JS, _CANVAS_JS, _IFRAME_JS, _BOILER_LINES,
        _BOILER_INLINE, wayback_rescue, wayback_dead_status,
    )
    import research_injection as _rij

DEFAULT_TASK = "task-3"

try:
    from patchright.sync_api import sync_playwright
except Exception as e:
    raise ImportError(
        f"patchright is required for the slot browser ({e}); no vanilla "
        "playwright fallback exists by design")

_SLOT_TLS = threading.local()

def set_thread_slot(tid: str) -> None:
    """Pin THIS thread's fetches to browser slot <tid> ("task-3"). The
    portal binds one lane per run; its scrape-pool threads inherit that
    binding through the job arguments, never through process-wide env
    (runner threads share one process; env would leak across runs). An
    empty string un-pins and falls back to RESEARCH_TASK then task-3."""
    _SLOT_TLS.task = str(tid or "")

def clear_thread_slot() -> None:
    """Drop this thread's lane binding (request threads are reused)."""
    _SLOT_TLS.task = ""

def current_thread_slot() -> str:
    return getattr(_SLOT_TLS, "task", "") or ""

def _cfg() -> dict:
    tid = getattr(_SLOT_TLS, "task", "") or \
        os.environ.get("RESEARCH_TASK", DEFAULT_TASK)
    return browser_ports.resolve(tid)

def _slot_key() -> str:
    try:
        return str(_cfg().get("key") or "")
    except Exception:
        return ""

def cdp_url() -> str:
    return browser_ports.cdp_http(_cfg())

def cdp_alive(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(cdp_url() + "/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def ensure_daemon(wait_s: float = 45.0) -> bool:
    """Ensure the slot browser is up (auto-launches detached if down)."""
    return bool(browser_ports.ensure(_cfg(), wait_s=int(wait_s)))

_CONN_LOCK = threading.Lock()
_CONNECTIONS: Dict[int, Dict[str, Any]] = {}

def _diag_dump(err: str, path: str = "/tmp/greysearch-sync-start-diag.log") -> None:
    """Full process snapshot at a sync_playwright start failure: the calling
    thread's own stack plus every live thread's frame, so the intermittent
    'Sync API inside the asyncio loop' crash can be root-caused with real
    evidence instead of theory. Diagnostics only; never part of a result."""
    try:
        import sys as _sys
        import traceback as _tb
        ident = threading.get_ident()
        this = _sys._current_frames().get(ident)
        lines = ["", time.strftime("%Y-%m-%dT%H:%M:%S"),
                 f"ident={ident} slot={_slot_key()} err={err[:200]}"]
        if this:
            lines += _tb.format_stack(this)
        for tid, fr in _sys._current_frames().items():
            lines.append(f"--- thread {tid}")
            frame_lines = _tb.format_stack(fr)
            lines += frame_lines[-6:]
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

def _discard_stale(conn: Dict[str, Any] | None = None) -> None:
    """Stop a stale cached connection's sync playwright BEFORE dropping it.

    Known crash class, root-caused against patchright 1.62.1 source: the sync
    dispatcher sets asyncio._set_running_loop
    on every call and only an orderly pw.stop() clears it. The two cache
    invalidation paths used to pop without stopping, so the parked dispatcher
    held the sentinel and EVERY later sync_playwright().start() in the thread
    raised 'Playwright Sync API inside the asyncio loop' (3 of 6 sources
    were rejected in a single run, each twice via fetch_url's retry). The
    browser and its tabs stay up: stopping the CDP client costs nothing."""
    if not conn:
        return
    pw = conn.get("pw")
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            pass

def _reset_loop_sentinel() -> None:
    """Clear asyncio's running-loop sentinel for the CURRENT thread.

    Belt-and-braces for a thread already poisoned by an older leak: no module
    in this repo ever starts a real asyncio loop, so a set sentinel here can
    only be a leaked patchright dispatcher's; the reset is always safe in
    this code base."""
    try:
        import asyncio
        asyncio._set_running_loop(None)
    except Exception:
        pass

_CAPTCHA_DEFAULT_WAIT_S = 45.0
_CAPTCHA_WAIT_MIN_DEFAULT_S = 30.0
_CAPTCHA_WAIT_MAX_DEFAULT_S = 60.0

_CAPTCHA_STATE_JS = """() => {
    const state = {widget_iframes: 0, empty_response: 0,
                   filled_response: 0, interstitial: false};
    const re = /recaptcha|hcaptcha|turnstile/i;
    for (const f of Array.from(
            document.querySelectorAll('iframe')).slice(0, 200)) {
        if (re.test((f.src || '') + (f.title || ''))) {
            state.widget_iframes++;
        }
    }
    const names = [
        'textarea[name="g-recaptcha-response"]',
        'textarea[name="h-captcha-response"]',
        'textarea[name="cf-turnstile-response"]',
        'input[name="g-recaptcha-response"]',
        'input[name="h-captcha-response"]',
        'input[name="cf-turnstile-response"]'].join(',');
    for (const el of Array.from(document.querySelectorAll(names))) {
        if ((el.value || '').trim().length > 10) {
            state.filled_response++;
        } else {
            state.empty_response++;
        }
    }
    const t = (((document.body || {})).innerText || '').slice(0, 4000);
    state.interstitial =
        /unusual traffic from your computer network/i.test(t) ||
        /making sure you('re| are) not a bot/i.test(t) ||
        (t.trim().length < 500 && (
            /just a moment/i.test(t) ||
            /checking your browser/i.test(t) ||
            /\\banubis\\b/i.test(t) ||
            /verify (that )?you (are|'re) (a )?human/i.test(t) ||
            /are you (a )?robot/i.test(t)));
    return state;
}"""

_ANUBIS_TEXT_RE = re.compile(
    r"making\s+sure\s+you(?:['’]re|\s+are)\s+not\s+a\s+bot", re.IGNORECASE)

def _env_float(name: str, default: float) -> float:
    try:
        v = float(str(os.environ.get(name, "") or default).strip() or default)
    except (TypeError, ValueError):
        v = float(default)
    return v if v >= 0 else float(default)

def captcha_phase_waits():
    """The two wait lengths the captcha WAIT contract runs with, read at
    call time and returned as (first, second). The pair comes from
    GREYSEARCH_CAPTCHA_WAIT_MIN_S (default 30) and
    GREYSEARCH_CAPTCHA_WAIT_MAX_S (default 60), ordered so the second never
    falls under the first; when the older GREYSEARCH_CAPTCHA_WAIT_S is set
    it pins BOTH lengths to its one value so the two-knob contract and the
    single-length contract stay one machinery. Junk or negative knob values
    fall back to their defaults."""
    pinned = str(os.environ.get("GREYSEARCH_CAPTCHA_WAIT_S", "") or "").strip()
    if pinned:
        both = _env_float("GREYSEARCH_CAPTCHA_WAIT_S", _CAPTCHA_DEFAULT_WAIT_S)
        return both, both
    wait_min = _env_float("GREYSEARCH_CAPTCHA_WAIT_MIN_S",
                          _CAPTCHA_WAIT_MIN_DEFAULT_S)
    wait_max = _env_float("GREYSEARCH_CAPTCHA_WAIT_MAX_S",
                          _CAPTCHA_WAIT_MAX_DEFAULT_S)
    return wait_min, max(wait_max, wait_min)

_BROWSER_PACE_DEFAULT_S = 30.0
_BROWSER_PACE_JITTER_DEFAULT_S = 15.0
_BROWSER_PACE_LOCK = threading.Lock()
_BROWSER_PACE_AT: Dict[str, float] = {}

def browser_pace_settings():
    """The (pace_s, jitter_s) pair the browser-lane search pace guard runs
    with, read at call time: GREYSEARCH_BROWSER_PACE_S default 30, floor 1
    (a value in (0, 1) clamps up to the 1 s floor) plus
    GREYSEARCH_BROWSER_PACE_JITTER_S default 15, floor 0. Exactly 0 is the
    inert bypass tests and emergency runs use; junk or negative values fall
    back to their defaults."""
    v = _env_float("GREYSEARCH_BROWSER_PACE_S", _BROWSER_PACE_DEFAULT_S)
    pace = 0.0 if v <= 0.0 else (1.0 if v < 1.0 else float(v))
    jitter = max(0.0, _env_float("GREYSEARCH_BROWSER_PACE_JITTER_S",
                                 _BROWSER_PACE_JITTER_DEFAULT_S))
    return pace, jitter

def browser_pace_at():
    """The pace guard's per-engine last-search timestamps as a read-only
    copy (engine name -> epoch seconds). Browser-lane search requests are
    the only writers; page fetches never write here."""
    with _BROWSER_PACE_LOCK:
        return dict(_BROWSER_PACE_AT)

def browser_pace_reset() -> None:
    """Empty the pace guard's per-engine state (tests and lane resets)."""
    with _BROWSER_PACE_LOCK:
        _BROWSER_PACE_AT.clear()

def browser_pace_wait(engine, sleep=None, now=None) -> float:
    """The human-pace guard for browser-lane SEARCH requests. Search pace:
    one search, then open the resulting links; never bombard Google-like
    engines from the machine's own IP. When this engine already saw a search
    request in this process, sleep long enough to keep at least
    GREYSEARCH_BROWSER_PACE_S plus 0-GREYSEARCH_BROWSER_PACE_JITTER_S
    seconds between the two requests, and return the seconds slept:
    0.0 for an engine's first search request of the process, when the last
    one is already old enough, and always when the guard is inert (pace
    < 1 exactly, GREYSEARCH_BROWSER_PACE_S=0). A sleep happens only between
    two same-engine search requests; page fetches never come through here,
    their politeness stays the separate 3 s per-domain wait. The caller
    records a nonzero return in its lane's digest line. The wait runs under
    the guard's one lock, so a same-engine lane queues behind a pending
    wait instead of racing it. sleep/now are injectable for offline tests."""
    sleeper = sleep if sleep is not None else time.sleep
    clock = now if now is not None else time.time
    key = str(engine or "").strip()
    pace, jitter = browser_pace_settings()
    if not key or pace < 1.0:
        return 0.0
    waited = 0.0
    with _BROWSER_PACE_LOCK:
        last = _BROWSER_PACE_AT.get(key, 0.0)
        if last > 0.0:
            gap = last + pace + (
                random.uniform(0.0, jitter) if jitter > 0.0 else 0.0) - clock()
            if gap > 0:
                waited = gap
                sleeper(gap)
        _BROWSER_PACE_AT[key] = clock()
    return round(waited, 2)

def captcha_state(page) -> Optional[Dict[str, Any]]:
    """One read of a page's captcha widget state (None when the page object
    could not be read: the read is the only thing it ever asks of the tab)."""
    st = _safe_eval(_CAPTCHA_STATE_JS, None, page)
    return st if isinstance(st, dict) else None

def captcha_present(state: Any) -> bool:
    """True when the page shows solvable captcha state right now: a widget
    iframe, an empty response field it feeds, or a solver interstitial."""
    if not isinstance(state, dict):
        return False
    return bool(int(state.get("widget_iframes") or 0)
                or int(state.get("empty_response") or 0)
                or state.get("interstitial"))

def captcha_solved(state: Any) -> bool:
    """True when the page's captcha state shows solve evidence or cleared
    entirely: the response token arrived with no empty field left and no
    interstitial marker, or every widget, empty field and interstitial
    marker is gone (a token already filled counts even when the anchor
    iframe is still mounted, which is how a solved reCAPTCHA looks)."""
    if not isinstance(state, dict):
        return False
    return (not state.get("interstitial")
            and not int(state.get("empty_response") or 0)
            and (int(state.get("filled_response") or 0) > 0
                 or not int(state.get("widget_iframes") or 0)))

def captcha_wait_cycle(page,
                       wait_s: Optional[float] = None,
                       poll_s: Optional[float] = None) -> Dict[str, Any]:
    """The WAIT-the-solver contract for one page: read the captcha state,
    and when present bound TWO wait phases (every
    GREYSEARCH_CAPTCHA_POLL_S seconds one solve-evidence read; a wait phase
    never runs past either the read count or its own length), the first of
    GREYSEARCH_CAPTCHA_WAIT_MIN_S seconds and the second of
    GREYSEARCH_CAPTCHA_WAIT_MAX_S (the two-phase 30-60 s wait design), then
    return the honest record {engaged, solved, waited_s}. A caller-supplied
    wait_s, or the set GREYSEARCH_CAPTCHA_WAIT_S, pins both phases to that
    one length instead. Never loops past the two phases, so the added wall
    time stays bounded by the two phase lengths plus at most one poll each;
    an absent or unreadable state returns engaged False and adds nothing.
    Poll sleeps ride the page (page.wait_for_timeout), so the evidence
    reads always follow a real settle."""
    phase1, phase2 = captcha_phase_waits()
    if poll_s is None:
        poll_s = _env_float("GREYSEARCH_CAPTCHA_POLL_S", 5.0)
    record = {"engaged": False, "solved": False, "waited_s": 0.0}
    state = captcha_state(page)
    if not captcha_present(state):
        return record
    record["engaged"] = True
    started = time.time()
    resolved = False
    for _phase in (1, 2):
        len_s = wait_s if wait_s is not None else (phase1 if _phase == 1
                                                   else phase2)
        deadline = time.time() + max(0.0, len_s)
        reads = max(1, math.ceil(max(0.0, len_s) / max(poll_s, 1e-6))) \
            if len_s > 0 else 0
        while reads > 0:
            reads -= 1
            if poll_s > 0:
                try:
                    page.wait_for_timeout(int(poll_s * 1000))
                except Exception:
                    pass
            state = captcha_state(page)
            if time.time() >= deadline or captcha_solved(state):
                break
        resolved = captcha_solved(state)
        if resolved:
            break
    record["solved"] = bool(resolved)
    record["waited_s"] = round(time.time() - started, 2)
    return record

def captcha_mark(record: Dict[str, Any]) -> str:
    """The honest mark line for a captcha wait record: the solved form names
    the waited seconds; the non-solved form says exactly what happened after
    the bounded retry. Empty when the cycle never engaged."""
    if not isinstance(record, dict) or not record.get("engaged"):
        return ""
    if record.get("solved"):
        return ("captcha: solver waited "
                f"{int(record.get('waited_s') or 0)}s (solved)")
    return "captcha: persisted (solver wait + retry exhausted)"

def captcha_solver_step(page,
                        cyc: Dict[str, Any]
                        ) -> "tuple[Dict[str, Any], Dict[str, str]]":
    """The local solver's one step under the lane's WAIT contract: called
    only after a wait cycle ended engaged-but-unsolved, it does nothing at
    all unless the kill switch allows (GREYSEARCH_CAPTCHA_SOLVER; the lane
    never consults a model otherwise), picks the turnstile rung for a
    turnstile-shaped wall and the capture ladder for anything else by the
    detected provider - and because the re-wait's result governs, not the
    solver's word, a solve is handed back to the lane only when a bounded
    re-wait of the same MIN phase length the contract's first phase uses
    (GREYSEARCH_CAPTCHA_WAIT_MIN_S) then sees the challenge lifted: the
    filled token, or every captcha marker gone entirely. The
    non-resolving paths return the caller's own record unchanged plus the
    honest skip note ("captcha_skip") only when the solver actually
    engaged its own record; every failure mode - the module not
    resolvable, the solver raising, a page it cannot read - degrades to
    the record it was given and no metadata, so the caller's persisted
    contract keeps its exact shape. Returns (record the lane goes on
    with, extra metadata keys for the lane's record)."""
    extra: Dict[str, str] = {}
    if not (isinstance(cyc, dict) and cyc.get("engaged")
            and not cyc.get("solved")):
        return cyc, extra
    try:
        import captcha_solve  # lazy: an ordinary page imports nothing here
        if not captcha_solve.solver_enabled():
            return cyc, extra
        prov = captcha_solve.detect_provider(page)
        res = (captcha_solve.solve_turnstile(page)
               if prov == "turnstile"
               else captcha_solve.solve_challenge(page, prov))
        rounds = int(res.get("rounds") or 0)
        prov = str(res.get("provider") or prov or "?")
        if res.get("solved"):
            # the re-wait governs, not the solver's word: the same bounded
            # MIN phase the contract's first phase decides, and a captcha
            # page whose evidence vanished is lifted by the same standard
            # the wait contract itself judges a CLEAR state by
            rew = captcha_wait_cycle(
                page,
                wait_s=_env_float("GREYSEARCH_CAPTCHA_WAIT_MIN_S",
                                  _CAPTCHA_WAIT_MIN_DEFAULT_S))
            if rew.get("solved") or not rew.get("engaged"):
                extra["captcha_solved"] = (
                    f"provider={prov},"
                    f"rung={res.get('rung') or '?'},rounds={rounds}")
                # a token state passes through exactly as the re-wait
                # wrote it; a page whose captcha evidence vanished is
                # reported engaged-and-solved on the same standard the
                # contract judges a CLEAR state solved evidence by
                return ({"engaged": True, "solved": True,
                         "waited_s": rew.get("waited_s", 0.0)}, extra)
            # no skip note rides on the claim the re-wait denied except
            # through the honest branch below
        if res.get("engaged"):
            extra["captcha_skip"] = f"provider={prov},rounds={rounds}"
    except Exception:
        pass
    return cyc, extra

def _connection() -> Dict[str, Any]:
    """Cached per-thread {pw, browser, ctx, page} for the slot browser, keyed
    by thread AND slot (a RESEARCH_TASK change drops the old connection)."""
    ident = threading.get_ident()
    key = (ident, _slot_key())
    with _CONN_LOCK:
        conn = _CONNECTIONS.get(ident)
    if conn:
        if conn["key"] != key:
            _discard_stale(conn)
            with _CONN_LOCK:
                _CONNECTIONS.pop(ident, None)
            conn = None
        else:
            try:
                if conn["browser"].is_connected():
                    return conn
            except Exception:
                pass
            _discard_stale(conn)
            with _CONN_LOCK:
                _CONNECTIONS.pop(ident, None)
            conn = None
    if not cdp_alive():
        if not ensure_daemon():
            raise RuntimeError(
                f"the {_slot_key() or DEFAULT_TASK} greysearch browser is not "
                "reachable and could not be launched")
    try:
        pw = sync_playwright().start()
    except Exception as pw_exc:
        if "asyncio loop" not in str(pw_exc):
            raise
        _diag_dump(str(pw_exc))
        _discard_stale(conn)
        with _CONN_LOCK:
            leaked = _CONNECTIONS.pop(ident, None)
        _discard_stale(leaked)
        _reset_loop_sentinel()
        pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url())
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    conn = {"key": key, "pw": pw, "browser": browser, "ctx": ctx, "page": page}
    with _CONN_LOCK:
        _CONNECTIONS[ident] = conn
    return conn

def page() -> Any:
    """The shared page on the slot browser (reuse, never close)."""
    return _connection()["page"]

def browser() -> Any:
    """The shared browser handle (attach-only, never close)."""
    return _connection()["browser"]

def context() -> Any:
    """The shared default context (the slot profile)."""
    return _connection()["ctx"]

def drop_connection() -> None:
    """Drop this thread's CDP client only (browser/tab stay up)."""
    ident = threading.get_ident()
    with _CONN_LOCK:
        conn = _CONNECTIONS.pop(ident, None)
    if conn:
        try:
            conn["pw"].stop()
        except Exception:
            pass

def drop_all_connections() -> None:
    """Stop every cached CDP client, in every thread. Short-lived CLIs call
    this before exit so patchright's node driver exits with them; without it
    the driver outlives the CLI, inherits a closed stdout, and dies with an
    EPIPE stack trace in the caller's log. The browser itself stays up."""
    with _CONN_LOCK:
        conns = list(_CONNECTIONS.values())
        _CONNECTIONS.clear()
    for conn in conns:
        try:
            conn["pw"].stop()
        except Exception:
            pass

def _stop_all_at_exit() -> None:
    drop_all_connections()

atexit.register(_stop_all_at_exit)

@contextmanager
def session_page():
    """Back-compat contextmanager over the cached shared page. Exiting drops
    only the CDP connection; the browser window and tabs stay open."""
    try:
        yield page()
    finally:
        drop_connection()

def _clean_text(text: str) -> str:
    """Paragraph-preserving normalization + boiler strip (same rules as
    patchright_scraper._clean_text, driven by its imported regex lists)."""
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    for pat in _BOILER_LINES:
        text = re.sub(pat, "", text)
    for pat in _BOILER_INLINE:
        text = re.sub(pat, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _safe_eval(js: str, fallback, page_obj=None):
    """page.evaluate on the Navigated page; never lets one extractor kill
    the fetch; a failed extractor yields its fallback and the fetch
    continues. Defaults to the shared slot page only when the caller has
    no page of its own."""
    try:
        return (page_obj if page_obj is not None else page()).evaluate(js)
    except Exception:
        return fallback

def fetch_text(url: str, max_chars: Optional[int] = None,
               settle_ms: int = 1200, mode: Any = None) -> dict:
    """Full-fidelity fetch of one URL through the slot browser.

    max_chars=None (the default) means the ENTIRE page; the old 14,000
    default truncation is gone. An explicit max_chars stays honored (callers
    like course_cli pass one). The scrape itself never changes transport
    (standing rule: scrapes stay direct); mode rides along so the per-URL wayback
    availability consult (the wayback backup rung) uses the same SEARCH-class opener
    contract as every search lane: direct when off, credentialed when
    a proxy mode. When the URL turns out dead (gone status or navigation
    failure), wayback_rescue tries the ARCHIVED copy before this fetch is
    declared failed, and a miss carries its own honest wayback note without
    mutating the original error text.
    """
    started = time.time()
    conn = _connection()
    pg = conn["ctx"].new_page()
    try:
        pg.set_default_timeout(60000)
    except Exception:
        pass
    own_tab = True
    status = 0
    error = ""
    try:
        resp = pg.goto(url, timeout=60000, wait_until="domcontentloaded")
        status = int(getattr(resp, "status", 0) or 0)
    except Exception as e:
        errtxt = (f"navigation failed: "
                  f"{type(e).__name__}: {str(e)[:200]}")
        try:
            pg.close()
        except Exception:
            pass
        try:
            resc, wbnote = wayback_rescue(url, dead_error=errtxt, mode=mode)
        except Exception as we:
            resc = None
            wbnote = f"unavailable ({type(we).__name__}: {str(we)[:80]})"
        if resc is not None:
            return resc
        base = {"ok": False, "url": url, "error": errtxt,
                "domain": "", "tier": "", "lane": "cdp-slot",
                "scrape_transport": _proxy_mode.scrape_guard_note()}
        if wbnote:
            base["wayback"] = wbnote
        return base
    if wayback_dead_status(status):
        try:
            pg.close()
        except Exception:
            pass
        try:
            resc, wbnote = wayback_rescue(url, dead_status=status, mode=mode)
        except Exception as we:
            resc = None
            wbnote = f"unavailable ({type(we).__name__}: {str(we)[:80]})"
        if resc is not None:
            meta2 = resc.get("metadata")
            if isinstance(meta2, dict):
                meta2["wayback_dead_status"] = status
            return resc
        base = {"ok": False, "url": url, "error": f"http {status}: page gone",
                "domain": "", "tier": "", "lane": "cdp-slot",
                "scrape_transport": _proxy_mode.scrape_guard_note(),
                "elapsed_s": round(time.time() - started, 2)}
        if wbnote:
            base["wayback"] = wbnote
        return base
    if settle_ms:
        try:
            pg.wait_for_timeout(settle_ms)
        except Exception:
            pass
    captcha_meta = ""
    cyc = {"engaged": False, "solved": False, "waited_s": 0.0}
    try:
        cyc = captcha_wait_cycle(pg)
        captcha_meta = captcha_mark(cyc)
    except Exception:
        pass
    solver_meta: Dict[str, str] = {}
    if cyc.get("engaged") and not cyc.get("solved"):
        # the wait contract stays the first response; the local solver is
        # the only thing that follows it, and its answer carries only when
        # its bounded re-wait sees the challenge lifted
        try:
            cyc, solver_meta = captcha_solver_step(pg, cyc)
            if solver_meta.get("captcha_solved"):
                captcha_meta = captcha_mark(cyc)
        except Exception:
            solver_meta = {}
    if cyc.get("engaged") and not cyc.get("solved"):
        try:
            pg.close()
        except Exception:
            pass
        # the persisted-skip record keeps today's exact wording, keys and
        # mark; the solver's honest skip note (when the local solver ran
        # and did not resolve) rides alongside as a new metadata key
        skip_meta: Dict[str, str] = ({}
                                     if not captcha_meta
                                     else {"captcha": captcha_meta})
        skip_meta.update(solver_meta)
        return {"ok": False, "url": url, "error": (
                    "captcha persisted after solver wait + bounded retry "
                    f"(waited {int(cyc.get('waited_s') or 0)}s)"),
                "metadata": skip_meta,
                "domain": "", "tier": "", "lane": "cdp-slot",
                "scrape_transport": _proxy_mode.scrape_guard_note(),
                "elapsed_s": round(time.time() - started, 2)}
    try:
        scroll_steps = int(eval_with_timeout(pg, _SCROLL_JS) or 0)
    except Exception:
        scroll_steps = 0

    raw_text = ""
    try:
        raw_text = pg.locator("body").inner_text()
    except Exception as e:
        error = f"body extract failed: {type(e).__name__}"
    html = ""
    try:
        html = pg.content()
    except Exception:
        pass
    html_capped = False
    if len(html) > _HTML_CAP:
        html = html[:_HTML_CAP]
        html_capped = True

    links = _safe_eval(_LINKS_JS, [], pg) or []
    images = _safe_eval(_IMAGES_JS, [], pg) or []
    videos = (_safe_eval(_VIDEO_TAG_JS, [], pg) or [])
    videos += (_safe_eval(_IFRAME_VIDEO_JS, [], pg) or [])
    tables = _safe_eval(_TABLES_JS, [], pg) or []
    headings = _safe_eval(_HEADINGS_JS, [], pg) or []
    code_blocks = _safe_eval(_CODE_JS, [], pg) or []
    audios = _safe_eval(_AUDIO_JS, [], pg) or []
    pdfs = _safe_eval(_PDF_JS, [], pg) or []
    canvases = _safe_eval(_CANVAS_JS, [], pg) or []
    iframes = _safe_eval(_IFRAME_JS, [], pg) or []
    try:
        meta = eval_with_timeout(pg, _META_JS) or {}
    except Exception:
        meta = {}

    text, inj_flags = _rij.sanitize_text(raw_text)
    text = _clean_text(text)
    if max_chars and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
        error = error or f"text capped by caller at {max_chars}"

    title = ""
    try:
        title = pg.title()
    except Exception:
        pass
    final_url = url
    try:
        final_url = pg.url
    except Exception:
        pass
    parsed_dom = ""
    try:
        from urllib.parse import urlparse as _up
        parsed_dom = _up(final_url).netloc.lower()
        if parsed_dom.startswith("www."):
            parsed_dom = parsed_dom[4:]
    except Exception:
        pass
    h2s = [(h.get("text") or "").strip()
           for h in headings if (h.get("level") == "h2" and h.get("text"))][:20]

    ok = bool(text.strip())
    if own_tab:
        try:
            pg.close()
        except Exception:
            pass
    result = {
        "ok": ok,
        "url": url,
        "final_url": final_url,
        "title": title,
        "status_code": status,
        "error": error if not ok else "",
        "chars": len(text),
        "text": text,
        "raw_text": raw_text,
        "html": html,
        "html_capped": html_capped,
        "links": links,
        "images": images,
        "videos": videos,
        "tables": tables,
        "headings": headings,
        "code_blocks": code_blocks,
        "audios": audios,
        "pdfs": pdfs,
        "canvases": canvases,
        "iframes": iframes,
        "injection_flags": inj_flags,
        "injection_scanned": True,
        "h2s": h2s,
        "clean": {
            "canonical_url": final_url,
            "h2s": h2s,
            "body_text": text,
            "excerpt": text[:600],
        },
        "metadata": {
            **(meta if isinstance(meta, dict) else {}),
            "extraction_method": "cdp_slot_browser",
            "scroll_steps": scroll_steps,
        },
        "domain": parsed_dom,
        "lane": "cdp-slot",
        "scrape_transport": _proxy_mode.scrape_guard_note(),
        "elapsed_s": round(time.time() - started, 2),
    }
    if captcha_meta:
        result["metadata"]["captcha"] = captcha_meta
    # the local solver's note ("captcha_solved", when it lifted the wall
    # and the re-wait saw it) rides the same record as its new key
    if solver_meta:
        result["metadata"].update(solver_meta)
    return result

_EVAL_TIMEOUT_S = 5.0

def eval_with_timeout(page, js: str, timeout_s: float = _EVAL_TIMEOUT_S):
    """page.evaluate with a hard wall, thread-affinity safe."""
    done = threading.Event()
    import threading as _t

    def _observer():
        end = time.time() + timeout_s
        while time.time() < end and not done.is_set():
            time.sleep(0.5)
        if done.is_set():
            return
        _kill_page_target_cdp()

    obs = _t.Thread(target=_observer, daemon=True)
    obs.start()
    try:
        res = page.evaluate(js)
        return res
    finally:
        done.set()

def _kill_page_target_cdp() -> None:
    """Close the slot browser's page target via raw CDP HTTP (no playwright
    objects, no thread affinity). Slot browser keeps its window."""
    import json as _json
    import urllib.request as _ur
    try:
        import browser_ports as _bp
        cfg = _bp.task_cfg()
    except Exception:
        return
    try:
        targets = _json.loads(_ur.urlopen(
            f"http://127.0.0.1:{cfg['port']}/json/list", timeout=5).read())
        pages = [t for t in targets if t.get("type") == "page"]
        for t in pages[:2]:
            try:
                _ur.urlopen(_ur.Request(
                    f"http://127.0.0.1:{cfg['port']}/json/close/{t['id']}",
                    method="PUT"), timeout=5)
            except Exception:
                pass
    except Exception:
        pass
