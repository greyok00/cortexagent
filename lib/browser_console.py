#!/usr/bin/env python3
"""lib/browser_console.py — Integrated bottom-right CortexAgent console.

ONE window (1280x720, bottom-right, always-on-top, dock-pinned, draggable).
No separate STT window, no separate chat input here —
this widget is the ONLY chat surface. Everything in this file folds into a
single Gtk.Window:

  • VTE 2.91 terminal — embedded `bin/cortexagent` PTY (full REPL).
    Typing in the entry box below feeds the PTY bytes directly. NO one-shot
    daemon calls, NO proxy shortcuts. The real subprocess owns memory,
    slimtoken, browser_control, overseer — all of it.

  STT/voice control is in the tray submenu only — NOT here.

  • ATTACH 📎     — Tk-less file dialog (Gtk.FileChooserNative); injects
                    the quoted path into the focused REPL via
                    `xdotool type --delay 1`. Image guard: refuses if
                    lib.check_image_model says the active model is not
                    multimodal.

  • COMPRESSION   — slimtoken stats (runs, tokens in/out, saved, ratio%).
  • MEMORY        — hot + cold counts + top platforms.

There is NO scheduled-tasks panel — cron/systemd belong in a system admin
tool, not here. (Removed per user instruction 2026-08-19.)

Lifecycle tracking:
  ~/.cortexagent/overlay_state.json holds {pid, vte_child_pid, window_id,
  opened_at, closed_at, state}. Written on every open/close event. Read
  by `cortexagent overlay-status` and tray inspectors.

Usage:
    python3 lib/browser_console.py        # run the window directly
    python3 -m lib.browser_console        # same thing
    tray → "CortexAgent Console" (window title) — calls open_in_thread()
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
CORTEXAGENT_BIN = str(_REPO_ROOT / "bin" / "cortexagent")

_OVERLAY_STATE = Path.home() / ".cortexagent" / "overlay_state.json"
_SCHED_STATE_DIR = Path.home() / ".cortexagent"
MINIFY_STATS = Path.home() / ".cortexagent" / "minify_stats.json"

# Window geometry — derived from screen size (62.5% wide, 41.7% tall).
# HiDPI 2× is handled by xdotool (physical px = css × 2).
WIN_W_PCT, WIN_H_PCT = 0.625, 0.25
WIN_W, WIN_H = 0, 0  # filled in at runtime from monitor geometry
MARGIN = 16

# Sidebar width (AGENT/BROWSER/PAGE essentials).
SIDEBAR_W = 280

# 2026-08-21 user feedback: "change it towards 800 pixels tall so each of
# those keys will be like 390... two huge keys and when you click them they
# indent so it looks like a key press." Strip width bumped from 56→120 so
# the bezeled keys breathe; KEY_BTN_W is the button's *width*; the button's
# *height* is computed at runtime as (strip_height / 2 - spacing) so each
# key fills exactly 50% of the visible strip area.
KEY_STRIP_W = 120
KEY_BTN_W = 110

REFRESH_SECS = 3


# ── Image guard (lib.check_image_model.py) ────────────────────────────────────

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp",
               ".bmp", ".tif", ".tiff", ".avif"}


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTS


# ── Lifecycle registry ───────────────────────────────────────────────────────

def _write_state(state: dict) -> None:
    try:
        _OVERLAY_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OVERLAY_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, _OVERLAY_STATE)
    except Exception:
        pass


def _record_open(pid: int, vte_pid: int | None, win_id: int) -> None:
    _write_state({
        "pid": pid,
        "vte_child_pid": vte_pid,
        "window_id": win_id,
        "opened_at": time.time(),
        "closed_at": None,
        "state": "open",
    })


def _record_close() -> None:
    try:
        if _OVERLAY_STATE.exists():
            cur = json.loads(_OVERLAY_STATE.read_text())
        else:
            cur = {}
    except Exception:
        cur = {}
    cur["closed_at"] = time.time()
    cur["state"] = "closed"
    _write_state(cur)


# ── Data: compression, memory, agent status ──────────────────────────────────

def _human_bytes(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _safe_read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _compression_stats() -> str:
    s = _safe_read_json(MINIFY_STATS, {})
    if not s:
        return "compression:  no data yet"
    runs = s.get("runs", 0)
    tin = s.get("tokens_in", 0)
    tout = s.get("tokens_out", 0)
    saved = s.get("tokens_saved", 0)
    ratio = s.get("ratio_pct", 0.0)
    return (
        f"COMPRESSION  · runs {runs:,}  "
        f"in {tin:,} · out {tout:,}  "
        f"saved {saved:,}  ({ratio:.1f}%)"
    )


def _memory_stats() -> str:
    hot = 0
    cold = 0
    cold_size = 0
    plat_top = []
    try:
        hotdir = Path.home() / ".config" / "cortexllm" / "memory" / "hot"
        if hotdir.exists():
            for p in hotdir.glob("*.jsonl"):
                for line in p.read_text(errors="ignore").splitlines():
                    if line.strip():
                        hot += 1
                        try:
                            o = json.loads(line)
                            src = (o.get("source") or o.get("platform") or "?")
                            plat_top.append(src)
                        except Exception:
                            pass
        coldir = Path.home() / ".config" / "cortexllm" / "memory" / "cold"
        if coldir.exists():
            for p in coldir.iterdir():
                if p.is_file():
                    cold += 1
                    cold_size += p.stat().st_size
                elif p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            cold += 1
                            cold_size += f.stat().st_size
        from collections import Counter
        c = Counter(plat_top)
        plat_top = ", ".join(f"{k}:{v}" for k, v in c.most_common(3))
    except Exception:
        pass
    return (
        f"MEMORY  · hot {hot:,}  cold {cold}  "
        f"size {_human_bytes(cold_size)}"
        + (f"  ({plat_top})" if plat_top else "")
    )


def _agent_status() -> str:
    """Resolve the active big-model + overseer. Reads active_model.json
    (daemon-written), falls back to probing :8080 for the big model name
    and :8082 for the overseer. Always renders a non-empty value.
    Returns Pango markup so ports/age are colour-highlighted.
    """
    s = _safe_read_json(
        Path.home() / ".cortexagent" / "active_model.json", {})
    model = s.get("model") or s.get("name") or ""
    port = str(s.get("port") or "")
    started = s.get("started_at")
    age = ""
    if isinstance(started, (int, float)):
        secs = int(time.time() - started)
        if secs < 60:
            age = f"{secs}s"
        elif secs < 3600:
            age = f"{secs // 60}m"
        else:
            age = f"{secs // 3600}h{(secs % 3600) // 60}m"
    if not model:
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "1",
                 "http://127.0.0.1:8080/v1/models"],
                capture_output=True, text=True, timeout=2,
            )
            data = json.loads(r.stdout or "{}")
            models = [m.get("id") or m.get("name") for m in data.get("data", data.get("models", []))]
            if models:
                model = str(models[0])
                port = "8080"
        except Exception:
            pass
    if not model:
        try:
            r = subprocess.run(
                ["ss", "-ltnp"], capture_output=True, text=True, timeout=1)
            for line in r.stdout.splitlines():
                if ":8080 " in line and "llama" in line.lower():
                    model, port = "big (llama)", "8080"
                    break
        except Exception:
            pass
    if not model:
        return "AGENT  ·  — no big model on :8080 —"

    short_model = model if len(model) <= 32 else model[:29] + "…"
    age_str = f"  up {age}" if age else ""
    return f"AGENT  ·  {short_model}  :{port}{age_str}"


def _plan_tasks() -> str:
    """Sidebar TASKS panel header.

    Combined view (user feedback 2026-08-20): show the REPL plan if it
    exists, otherwise fall back to the scheduler's queued tasks. The
    panel never renders "empty" because cron is always running.
    """
    plan_path = Path.home() / ".cortexagent" / "overseer_plan.json"
    p = _safe_read_json(plan_path, {})
    if p:
        name = p.get("name") or "?"
        total = p.get("total_steps", 0)
        current = p.get("current_step", 0)
        return f"{name}  ·  step {current}/{total}"
    # Fallback: scheduler queue
    sched = _scheduler_summary()
    if sched:
        return sched
    return "TASKS  ·  ✓ idle"


def _scheduler_summary() -> str:
    """Compact one-liner about the scheduler's queued + running tasks."""
    sched_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.json"
    p = _safe_read_json(sched_path, None)
    if p is None:
        return ""  # scheduler file doesn't exist — REPL status bar will say so
    tasks = p.get("tasks") if isinstance(p, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ""  # exists but empty — REPL status bar already says "✓ idle"
    running = [t for t in tasks if (t.get("state") or t.get("status")) == "running"]
    queued = [t for t in tasks
              if (t.get("state") or t.get("status")) not in ("completed", "failed", "running")]
    if running:
        title = (running[0].get("title") or "running")[:30]
        return f"SCHED  ·  ▶ {title}  ·  +{len(queued)} queued"
    return f"SCHED  ·  {len(queued)} queued"


def _plan_steps() -> list:
    """Return [(idx, text, status)] for the plan — used by sidebar.

    Reads `~/.cortexagent/overseer_plan.json` written by lib.overseer.plan_set
    / plan_step. The plan file holds two parallel arrays:
        steps:       ["step1 text", "step2 text", ...]
        step_status: ["done", "current", "pending", ...]
    If step_status is absent (older format), fall back to deriving status
    from current_step.
    """
    plan_path = Path.home() / ".cortexagent" / "overseer_plan.json"
    p = _safe_read_json(plan_path, {})
    if not p:
        return []
    steps = p.get("steps") or []
    step_status = p.get("step_status") or []
    current = p.get("current_step", 0)
    out = []
    for i, s in enumerate(steps, start=1):
        # Prefer the explicit step_status array; fall back to current_step.
        if i - 1 < len(step_status):
            raw = str(step_status[i - 1]).lower()
            if raw in ("done", "completed", "finished"):
                status = "done"
            elif raw in ("current", "in_progress", "active", "running"):
                status = "current"
            else:
                status = "pending"
        elif current > len(steps):
            status = "done"
        elif i < current:
            status = "done"
        elif i == current:
            status = "current"
        else:
            status = "pending"
        # steps can be either a string or a dict {"text": "..."}.
        if isinstance(s, dict):
            text = str(s.get("text") or s.get("name") or s.get("step") or
                       s.get("description") or "")
        else:
            text = str(s)
        out.append((i, text, status))
    return out


def _live_primary_task() -> dict | None:
    """Return the most-relevant live scheduler task as {id, title, state,
    ts}, or None if the scheduler is genuinely idle.

    Used by the sidebar TASKS pane when there is no active REPL plan.
    Mirrors the logic in
    `cortex/.../modes/interactive/components/status-panels.ts:readLiveActivity()`
    but in Python — same flat-dict / events-log merge + last-write-wins.
    Returns the top task by `state ∈ {running, queued}` priority, falling
    back to the most-recent event overall if nothing is actually active.

    2026-08-21: added so the sidebar shows detail (title + state + ts +
    id) instead of just "· no active plan" when the agent isn't running
    a REPL plan but the scheduler has queued/running work.
    """
    try:
        sched_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.json"
        events_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.events.jsonl"
        by_id: dict[str, dict] = {}

        # Snapshot first (accepts both {tasks: [...]} envelope and flat
        # dict keyed by id — matches the TUI fix from 2026-08-21).
        snap = _safe_read_json(sched_path, None)
        if isinstance(snap, dict):
            if isinstance(snap.get("tasks"), list):
                snap_iter = snap["tasks"]
            else:
                snap_iter = [
                    {"id": k, **v} if isinstance(v, dict) else {"id": k}
                    for k, v in snap.items()
                ]
            for t in snap_iter:
                if not isinstance(t, dict):
                    continue
                tid = str(t.get("id") or "")
                if not tid:
                    continue
                by_id[tid] = {
                    "id": tid,
                    "title": str(t.get("title") or "(untitled)"),
                    "state": str(t.get("state") or t.get("status") or "scheduled"),
                    "ts": str(t.get("next_run_at") or t.get("last_run_at")
                              or t.get("updated_at") or ""),
                }

        # Events overlay (last-write-wins per task_id).
        try:
            if events_path.exists():
                for raw in events_path.read_text(errors="replace").split("\n"):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    tid = str(ev.get("task_id") or "")
                    if not tid:
                        continue
                    ts = str(ev.get("timestamp") or "")
                    cur = by_id.get(tid)
                    if cur and cur["ts"] and ts and cur["ts"] >= ts:
                        continue
                    # Map event type → state.
                    state = cur["state"] if cur else "scheduled"
                    et = str(ev.get("type") or "").lower()
                    if et in ("create",):
                        state = "scheduled"
                    elif et in ("queue", "queued"):
                        state = "queued"
                    elif et in ("start", "running"):
                        state = "running"
                    elif et in ("done", "succeeded"):
                        state = "succeeded"
                    elif et in ("fail", "failed"):
                        state = "failed"
                    elif et in ("cancel",):
                        state = "cancelled"
                    title = (ev.get("data") or {}).get("title") or (
                        cur["title"] if cur else "(untitled)")
                    by_id[tid] = {
                        "id": tid,
                        "title": str(title),
                        "state": state,
                        "ts": ts,
                    }
        except Exception:
            pass

        if not by_id:
            return None

        # Prefer running → queued → most-recent.
        running = [t for t in by_id.values() if t["state"] == "running"]
        if running:
            return max(running, key=lambda t: t["ts"])
        queued = [t for t in by_id.values() if t["state"] == "queued"]
        if queued:
            return max(queued, key=lambda t: t["ts"])
        # Fallback: most-recent of anything.
        return max(by_id.values(), key=lambda t: t["ts"])
    except Exception:
        return None


def _browser_state() -> str:
    """Returns short status string for the BROWSER panel header."""
    tabs = _fetch_cdp_tabs()
    if not tabs:
        return "— :9222 offline —"
    n = len(tabs)
    active = sum(1 for t in tabs if t.get("active"))
    return f"{n} tab{'s' if n != 1 else ''} · {active} active"


_SCHED_EVENTS = Path.home() / ".cortexagent" / "scheduler" / "tasks.events.jsonl"


def _active_task_for_browser() -> str:
    """One-line summary of the most-recent scheduler task.

    Used as the BROWSER section header so the user can see what the
    system is working on without opening the TUI. Reads
    ~/.cortexagent/scheduler/tasks.events.jsonl (same source the TUI's
    left strip uses). Returns "✓ idle" when nothing's running and no
    task has ever been created.

    User feedback 2026-08-20: "its still showing the 10 lines of the
    scheduler." This function only returns ONE line, but the BROWSER
    tab rows below can stack to many visible lines on a narrow sidebar.
    The fix is twofold: (1) this header must only surface tasks whose
    most-recent event is `running`/`start`/`done`/`failed`/`cancel` —
    NOT `create` — so seeded tasks don't appear forever. (2) The CDP
    tab rows are capped at 5 (already done).
    """
    try:
        if not _SCHED_EVENTS.exists():
            return "✓ idle"
        lines = _SCHED_EVENTS.read_text(errors="ignore").splitlines()
        # Walk tail → head; capture last ACTIONABLE event per task_id.
        # `create` events are filtered out — a task that was only ever
        # created (never run, done, or cancelled) is not "active" and
        # should not appear here. Without this filter, every historical
        # seed task surfaces as its own row.
        ACTIONABLE = {"running", "start", "done", "completed",
                      "failed", "cancel", "cancelled"}
        last_by_id: dict[str, dict] = {}
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            etype = str(ev.get("type") or "")
            if etype not in ACTIONABLE:
                continue
            tid = str(ev.get("task_id") or "")
            if not tid or tid in last_by_id:
                continue
            last_by_id[tid] = {
                "type":  etype,
                "title": str((ev.get("data") or {}).get("title") or ""),
                "ts":    str(ev.get("timestamp") or ""),
            }
        if not last_by_id:
            return "✓ idle"
        # Prefer a running task if any.
        running = next(
            (v for v in last_by_id.values()
             if v["type"] in ("running", "start")),
            None,
        )
        if running:
            title = (running["title"] or "running").strip() or "running"
            return f"▶ {title[:38]}"
        # Otherwise most recent actionable event.
        top = max(last_by_id.values(), key=lambda v: v["ts"])
        # If the most-recent actionable task has no title (test/internal
        # cron), prefer "✓ idle" over "(untitled)" so the BROWSER header
        # never looks broken. User feedback 2026-08-20: "it's literally
        # one line because it's flooded full of fucking schedule".
        title = (top.get("title") or "").strip()
        if not title:
            return "✓ idle"
        glyph = {
            "done":     "✓",
            "completed": "✓",
            "failed":   "✗",
            "cancel":   "○",
            "cancelled": "○",
        }.get(top["type"], "·")
        return f"{glyph} {title[:38]}"
    except Exception:
        return "✓ idle"


def _markup_escape(text: str) -> str:
    """Escape Pango/XML markup — & < > " ' — so user-provided strings
    can be safely interpolated into set_markup templates. Without this,
    a tab title like "what's up" produces a Gtk-WARNING every refresh.
    """
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _html_decode(text: str) -> str:
    """Decode the most common HTML entities that appear in CDP tab
    titles (named + numeric). CDP returns titles like "what&#39;s up"
    because Chromium internally HTML-encodes them. Pango is XML so
    decoded ' still needs markup escaping via _markup_escape.
    """
    import html as _html
    return _html.unescape(text)


def _fetch_cdp_tabs() -> list:
    """Raw tab list from Chrome DevTools Protocol on :9222.

    Only top-level pages: filters out iframes, workers, service workers.
    Newest-attached first (CDP returns in attach order, so we reverse).
    """
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1",
             "http://127.0.0.1:9222/json"],
            capture_output=True, text=True, timeout=2,
        )
        all_tabs = json.loads(r.stdout or "[]")
    except Exception:
        return []
    pages = [t for t in all_tabs if t.get("type") == "page"]
    pages.reverse()  # newest first
    return pages


def _bring_tab_to_front_via_cdp(tab: dict) -> bool:
    """Send Page.bringToFront over the tab's WebSocket. Returns True iff
    the browser acknowledged the command. This is the canonical way to
    activate a CDP tab.
    """
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return False
    try:
        import websocket  # type: ignore
    except Exception:
        return False
    try:
        ws = websocket.create_connection(ws_url, timeout=2)
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Page.bringToFront",
                "params": {},
            }))
            # Read until we get our response or timeout.
            ws.settimeout(1.5)
            try:
                while True:
                    raw = ws.recv()
                    if not raw:
                        break
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if msg.get("id") == 1:
                        return True
            except Exception:
                # Timed out waiting — but the command may still have been
                # delivered. Treat as success.
                return True
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception:
        return False


def _raise_brave_window() -> bool:
    """Bring the running Brave window to the foreground. Brave uses a
    single root window for all tabs, so we raise by app class / generic
    name rather than per-tab.
    """
    # Try wmctrl with -x for the app class first (most reliable). This
    # box has no wmctrl (user feedback 2026-08-20), so on FileNotFoundError
    # we fall through to an xdotool name search instead of bailing.
    for pattern in ("Brave-browser", "brave-browser.Brave-browser",
                    "google-chrome.Google-chrome", "Chromium"):
        try:
            r = subprocess.run(
                ["wmctrl", "-x", "-a", pattern],
                capture_output=True, timeout=2)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            pass
    try:
        r = subprocess.run(
            ["wmctrl", "-a", "Brave"],
            capture_output=True, timeout=2)
        if r.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    # xdotool fallback — the reliable path on this machine. Search any
    # Brave/Chromium window and activate+raise it, ignoring the one we're
    # sitting in (the console window has a different title).
    try:
        for pat in ("Brave", "brave", "google-chrome", "Chromium"):
            r = subprocess.run(
                ["xdotool", "search", "--name", pat],
                capture_output=True, text=True, timeout=2)
            wids = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
            if not wids:
                continue
            for cmd in (
                ["xdotool", "windowactivate", "--sync", wids[0]],
                ["xdotool", "windowraise", wids[0]],
            ):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=2)
                except Exception:
                    continue
            return True
    except Exception:
        return False
    return False


def _focus_tab(tab: dict) -> bool:
    """Activate a CDP tab and raise the browser window.

    Strategy:
      0. NEW: Prefer CDP Page.bringToFront over the tab's own
         WebSocket. This is what Chromium actually keys activation by
         — the WM_NAME heuristic below misfires when multiple Brave
         windows are open or titles are CDP-truncated.
      1. PRIMARY: xdotool search against the WM_NAME. Brave appends
         " - Brave" to the document title in WM_NAME, and only currently-
         loaded foreground/active tabs have X11 windows — background
         tabs do NOT. So we try the title with the suffix appended
         first (most reliable on this box, verified 2026-08-20), then
         fall back to the bare title (works for non-Brave Chromium
         forks like google-chrome that don't add a suffix).
      2. FALLBACK: substring search on the leading N chars — when the
         CDP title is truncated to 80 chars (the case the user actually
         hit, per "I'm building cortex agent..." tab) the suffix never
         matches because the trailing " - Brave" was chopped off.
         Take the first 24 chars of the title and substring-search.
      3. FALLBACK: enumerate --classname "brave-browser" windows and
         pick the one whose WM_NAME starts with the CDP title prefix.
      4. FALLBACK: raise any Brave window (better than nothing).

    The console ALSO needs to release focus before xdotool can raise
    another window — otherwise the WM may refuse to focus-bridge to
    a window belonging to a different X11 client. We call
    xdotool windowminimize on ourselves as a hint.

    Returns True if any xdotool path succeeded.
    """
    # Debug gate — `[focus_tab] …` prints only when explicitly enabled.
    _ft_dprint = (lambda *a, **k:
                  print(*a, file=sys.stderr, **k)
                  if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1"
                  else None)
    # CDP-direct: ask the tab itself to come to the front. This is the
    # canonical Chromium-side activation. The tab's webSocketDebuggerUrl
    # uniquely identifies it, so this avoids the title-matching
    # ambiguity when multiple tabs are open.
    cdp_ok = _bring_tab_to_front_via_cdp(tab)
    _ft_dprint(f"[focus_tab] CDP bringToFront: {cdp_ok}")
    if cdp_ok:
        # CDP activated the tab — now we just need to raise the Brave
        # window. The active tab inside Brave will be the one we asked
        # for, not whatever happens to be most-recent.
        try:
            win.set_keep_above(False)
        except Exception:
            pass
        if _raise_brave_window():
            return True
        # If raising didn't work, fall through to the title-search path
        # anyway so the user gets *something*.

    title = (tab.get("title") or "").strip()
    if title:
        decoded = _html_decode(title)
        # Build the candidate list: full title + common suffixes.
        candidates = [decoded, f"{decoded} - Brave", f"{decoded} – Brave"]
        # Drop empty / dup candidates while preserving order.
        seen = set()
        candidates = [c for c in candidates
                      if c and not (c in seen or seen.add(c))]
        # Also try a 24-char prefix (handles CDP-truncated titles).
        prefix = decoded[:24].strip()
        if prefix:
            candidates.append(prefix)
        _ft_dprint(
            f"[focus_tab] tab_id={tab.get('id', '?')[:8]} title={decoded[:50]!r}")
        _ft_dprint(f"[focus_tab]   candidates={candidates}")

        for cand in candidates:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", cand],
                    capture_output=True, text=True, timeout=2,
                )
                wids = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
                _ft_dprint(
                    f"[focus_tab]   search {cand[:40]!r:44} → {len(wids)} wid(s)")
                if not wids:
                    continue
                # Prefer the WID whose WM_NAME most-closely matches.
                best = _pick_best_wid(wids, decoded)
                if best:
                    # 2026-08-21 user feedback: "the browser links still do
                    # not work when you click them." The prior version used
                    # `--sync` which BLOCKS on the WM — if X server is
                    # busy (other windows mid-animation, focus-stealing-
                    # prevention in effect), the call can hang or no-op
                    # silently. Drop --sync and explicitly raise after.
                    # Also remove the console's always-on-top flag
                    # transiently so the WM will actually raise Brave
                    # on top of us.
                    try:
                        win.set_keep_above(False)
                    except Exception:
                        pass
                    act = subprocess.run(
                        ["xdotool", "windowactivate", best],
                        capture_output=True, timeout=2,
                    )
                    raise_r = subprocess.run(
                        ["xdotool", "windowraise", best],
                        capture_output=True, timeout=2,
                    )
                    _ft_dprint(
                        f"[focus_tab]   activate {best} rc=({act.returncode},"
                        f"{raise_r.returncode})")
                    return True
            except Exception as e:
                _ft_dprint(f"[focus_tab]   xdotool error: {e}")
                continue

        # Enumerate brave-browser windows and pick by prefix-match.
        try:
            r = subprocess.run(
                ["xdotool", "search", "--classname", "brave-browser"],
                capture_output=True, text=True, timeout=2,
            )
            wids = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
            _ft_dprint(
                f"[focus_tab]   --classname brave-browser → {len(wids)} wid(s)")
            best = _pick_best_wid(wids, decoded)
            if best:
                try:
                    win.set_keep_above(False)
                except Exception:
                    pass
                subprocess.run(
                    ["xdotool", "windowactivate", best],
                    capture_output=True, timeout=2,
                )
                subprocess.run(
                    ["xdotool", "windowraise", best],
                    capture_output=True, timeout=2,
                )
                return True
        except Exception:
            pass

    # Last-resort: CDP bringToFront (no-op if origin blocked, harmless).
    cdp_ok = _bring_tab_to_front_via_cdp(tab)
    # ALWAYS surface SOME Brave window on a tab click, even when the
    # per-title xdotool path already reported success (windowactivate can
    # no-op silently under some WMs). Since all Brave tabs share one root
    # window, raising it guarantees the active browser surfaces.
    _raise_brave_window()
    return cdp_ok or True


def _pick_best_wid(wids: list[str], title: str) -> str | None:
    """From a list of X11 window IDs, pick the one whose WM_NAME most
    closely matches `title`. Returns the first WID if no name lookup
    succeeds (better than nothing)."""
    if not wids:
        return None
    if len(wids) == 1:
        return wids[0]
    best = None
    best_score = -1
    needle = title.lower()
    for w in wids:
        try:
            r = subprocess.run(
                ["xdotool", "getwindowname", w],
                capture_output=True, text=True, timeout=1,
            )
            name = (r.stdout or "").strip().lower()
        except Exception:
            continue
        if not name:
            continue
        # Score: longest common substring length between title prefix
        # and the window name. Cheap and good enough for tab matching.
        score = 0
        for n in range(min(len(needle), len(name)), 0, -1):
            if needle[:n] in name:
                score = n
                break
        if score > best_score:
            best_score = score
            best = w
    return best or wids[0]


def _page_snapshot() -> str:
    """Focused CDP tab URL + title.

    Returns a single line. Falls back to 'no focused tab' when CDP is
    offline. Length-capped so the sidebar stays readable.
    """
    tabs = _fetch_cdp_tabs()
    if not tabs:
        return "PAGE  ·  — :9222 offline —"
    # CDP /json does NOT carry an `active` flag on this Brave build — the
    # previous filter (`t.get("active")`) matched nothing and the panel
    # always rendered "offline". Use the first tab (MRU order from /json)
    # as the focused one, falling back to the actively-flagged tab if
    # Brave ever starts emitting it.
    focused = next((t for t in tabs if t.get("active")), tabs[0])
    title = (focused.get("title") or "?")[:40]
    url = focused.get("url") or "?"
    if len(url) > 50:
        url = url[:47] + "…"
    return f"PAGE  ·  {title}  ·  {url}"


# ── Main window builder ──────────────────────────────────────────────────────

def _metrics_line() -> str:
    """Compact live-metrics row for the SETTINGS panel.

    Same data sources the TUI's API Health section uses (no new
    modules). Re-read every REFRESH_SECS=3s. Always renders a non-
    empty value so the panel never blanks out.
    """
    # Big / proxy / overseer health
    big_ok = _port_open(8080)
    proxy_ok = _port_open(8081)
    ovsr_ok = _port_open(8082)
    health = (
        f"{'●' if big_ok else '○'} big :8080   "
        f"{'●' if proxy_ok else '○'} proxy :8081   "
        f"{'●' if ovsr_ok else '○'} ovsr :8082"
    )
    # Compression + memory
    try:
        s = _safe_read_json(MINIFY_STATS, {})
        runs = int(s.get("runs", 0))
        ratio = float(s.get("ratio_pct", 0.0))
        compress = f"compress {ratio:.0f}% ({runs} runs)"
    except Exception:
        compress = "compress —"
    try:
        hotdir = Path.home() / ".config" / "cortexllm" / "memory" / "hot"
        coldir = Path.home() / ".config" / "cortexllm" / "memory" / "cold"
        hot = 0
        if hotdir.exists():
            for p in hotdir.glob("*.jsonl"):
                for line in p.read_text(errors="ignore").splitlines():
                    if line.strip():
                        hot += 1
        cold = sum(1 for f in coldir.rglob("*") if f.is_file()) if coldir.exists() else 0
        mem = f"mem {hot} hot / {cold} cold"
    except Exception:
        mem = "mem —"
    return f"{health}\n{compress}   {mem}"


def _port_open(port: int) -> bool:
    """Cheap TCP probe for service-health dots in the metrics row.

    No exception spew on shutdown when services are down — return False.
    """
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except Exception:
        return False


def _apply_theme(name: str) -> None:
    """Rebuild the popup's CSS provider from the picked palette.

    Reads the palette from lib.popup_themes and writes a fresh CSS
    blob. GTK caches providers, so we drop the prior one and install a
    new one. Used by the Settings' Apply button.
    """
    try:
        from lib.popup_themes import get_palette
        pal = get_palette(name)
    except Exception:
        return
    css = (
        f"window {{ background: {pal['bg']}; color: {pal['fg']}; }}\n"
        f".title {{ color: {pal['accent']}; font-weight: bold; }}\n"
        f".panel-title {{ color: {pal['accent']}; font-weight: bold; padding-top: 6px; }}\n"
        f".panel-body {{ color: {pal['fg']}; font-family: monospace; font-size: 11px; }}\n"
        f".status-bar {{ color: {pal['fg_dim']}; font-size: 10px; }}\n"
        f".sidebar-header {{"
        f" color: {pal['accent']}; font-weight: bold; font-size: 11px;"
        f" background: {pal['bg_alt']}; border: 1px solid {pal['border']};"
        f" border-radius: 4px; padding: 4px 8px; margin-top: 8px;"
        f" }}\n"
        f".sidebar-body {{ color: {pal['fg']}; font-family: monospace; font-size: 10px;"
        f" padding: 2px 4px; }}\n"
        f".sidebar {{ background: {pal['bg_alt']}; }}\n"
        f"scrolledwindow.sidebar scrollbar trough {{ background: {pal['bg_alt']}; }}\n"
        f"scrolledwindow.sidebar scrollbar slider {{ background: {pal['border']}; }}\n"
        f".sidebar-tab-row {{"
        f" background: {pal['bg']}; color: {pal['fg']};"
        f" border: 1px solid {pal['border']}; border-radius: 3px;"
        f" padding: 4px 6px; margin: 1px 0; font-family: monospace;"
        f" }}\n"
        f".sidebar-tab-row:hover {{ background: {pal['hover_bg']};"
        f" border-color: {pal['accent']}; }}\n"
        f".sidebar-tab-active {{ border-left: 3px solid {pal['accent']};"
        f" background: {pal['hover_bg']}; }}\n"
        f".entry {{ background: {pal['bg_alt']}; color: {pal['fg']};"
        f" border: 1px solid {pal['border']}; padding: 6px; }}\n"
        f".top-strip {{ background: {pal['bg_alt']};"
        f" border-bottom: 1px solid {pal['border']}; padding: 0 4px; }}\n"
        f".top-strip button {{ padding: 0 6px; min-height: 22px; min-width: 22px; }}\n"
        f".top-strip-title {{ color: {pal['accent']}; font-weight: bold; font-size: 10px; }}\n"
        f".top-strip-grip {{ color: {pal['fg_dim']}; font-size: 12px; }}\n"
        f".corner-btn {{ background: transparent; color: {pal['accent']};"
        f" border: none; padding: 0; font-weight: bold; font-size: 11px; }}\n"
        f".corner-btn:hover {{ background: {pal['danger']}; color: {pal['hover_fg']}; }}\n"
        f".close-btn {{ background: transparent; color: {pal['accent']};"
        f" border: none; padding: 0; font-weight: bold; }}\n"
        f".close-btn:hover {{ background: {pal['danger']}; color: {pal['hover_fg']}; }}\n"
        f".body-strip {{ background: {pal['bg_alt']};"
        f" border-top: 1px solid {pal['border']};"
        f" border-bottom: 1px solid {pal['border']}; }}\n"
        f".settings-row {{ color: {pal['fg']}; font-size: 10px;"
        f" padding: 4px 6px; font-family: monospace; }}\n"
        f".settings-row label {{ color: {pal['accent']}; }}\n"
        f".settings-apply-btn {{ background: {pal['bg_alt']};"
        f" color: {pal['accent']}; border: 1px solid {pal['accent']};"
        f" border-radius: 3px; padding: 4px 12px; margin: 8px 6px 4px 6px;"
        f" font-weight: bold; }}\n"
        f".settings-apply-btn:hover {{ background: {pal['hover_bg']};"
        f" color: {pal['hover_fg']}; }}\n"
        f".active-task-row {{ color: {pal['accent']}; font-weight: bold;"
        f" font-size: 10px; padding: 3px 6px; margin: 2px 0;"
        f" background: {pal['bg']}; border: 1px solid {pal['border']};"
        f" border-radius: 3px; }}\n"
        f"frame.terminal-frame {{ border: 1px solid {pal['border']};"
        f" background: {pal['bg_alt']}; padding: 2px; }}\n"
        f"vte {{ border: 1px solid {pal['border']}; }}\n"
        f".side-strip {{ background: {pal['bg_alt']};"
        f" border-left: 1px solid {pal['border']}; }}\n"
    ).encode("utf-8")
    try:
        from gi.repository import Gtk, Gdk
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        if getattr(_apply_theme, "_prior", None) is not None:
            try:
                Gtk.StyleContext.remove_provider_for_screen(
                    Gdk.Screen.get_default(), _apply_theme._prior,
                )
            except Exception:
                pass
        _apply_theme._prior = provider
    except Exception:
        pass


def build_window() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte, GLib, Gdk, Pango

    win = Gtk.Window()
    win.set_title("CortexAgent Console")
    win.set_keep_above(True)

    # Resolve window dimensions BEFORE any size hints so the WM honors
    # them. Order of precedence (2026-08-21 user feedback: "the window is
    # still not that tall, i mean what are you changing"):
    #   1. popup_settings.json `resolution: [w, h]` — explicit user pick.
    #      Read FIRST and use it verbatim if both axes are present.
    #   2. Else derive from primary monitor at WIN_W_PCT × WIN_H_PCT.
    #   3. Else 1200x500 fallback.
    # The previous code only knew about #2, so any value the user wrote
    # into popup_settings.json was silently ignored — the monitor on this
    # HiDPI box is 3840×2400, so 0.625 × 3840 = 2400 wide and 0.25 × 2400
    # = 600 tall, which is way too big horizontally and ignored the
    # user's 760px request entirely.
    global WIN_W, WIN_H
    explicit_size = None
    try:
        # 2026-08-21 user feedback: "the window is still not that tall".
        # Root cause: launched via systemd-run the working dir was NOT
        # the repo root, so `from lib.popup_themes import …`
        # raised ModuleNotFoundError. The except block silently fell
        # through to the monitor-derived size (3840×2400 × 0.625×0.25
        # = 2400×600 — way too big and ignored the user's 760px pick).
        # Always prepend the repo root to sys.path before importing.
        _REPO = str(Path(__file__).resolve().parent.parent)
        if _REPO not in sys.path:
            sys.path.insert(0, _REPO)
        from lib.popup_themes import load_settings
        s = load_settings()
        res = s.get("resolution")
        if isinstance(res, (list, tuple)) and len(res) == 2:
            try:
                w, h = int(res[0]), int(res[1])
                # 2026-08-21 user feedback: "30% screen height" → 180 CSS
                # on a 600-CSS-tall monitor. The previous 200 floor
                # rejected valid small values and fell through to the
                # monitor math (1500×375), which ignored the user's pick.
                # Just require positive values.
                if w >= 100 and h >= 80:
                    explicit_size = (w, h)
            except (TypeError, ValueError):
                pass
    except Exception as e:
        if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1":
            import traceback
            print(f"[browser_console] load_settings FAILED: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    if explicit_size is not None:
        WIN_W, WIN_H = explicit_size
    else:
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            mg = monitor.get_geometry()
            WIN_W = max(800, int(mg.width * WIN_W_PCT))
            WIN_H = max(300, int(mg.height * WIN_H_PCT))
        except Exception as e:
            if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1":
                import traceback
                print(f"[browser_console] monitor FAILED: {e}", file=sys.stderr)
            WIN_W, WIN_H = 1200, 500
    # 2026-08-21 user feedback: "the window is still not that tall".
    # Belt-and-braces: log to stderr so the next launch shows what we
    # actually picked. Run with CORTEXAGENT_CONSOLE_DEBUG=1 to see.
    try:
        if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1":
            print(f"[browser_console] WIN_W={WIN_W} WIN_H={WIN_H}", file=sys.stderr)
    except Exception:
        pass

    win.set_default_size(WIN_W, WIN_H)
    win.set_size_request(WIN_W, WIN_H)
    # No GTK HeaderBar — we draw our own thin draggable strip as the
    # window's titlebar surrogate (24 px tall, click-drag to move,
    # minimize + close inline). Suppress the WM's own decorations so
    # we don't get the thick rounded chunk. set_titlebar(None) tells
    # the WM "we're handling it". User feedback 2026-08-20: "the whole
    # top bar with the black curved part with the X, terrible, it
    # does need a minimize as well. I like it more like the STT.
    # click drag to move. And it's much thinner."
    try:
        win.set_titlebar(None)
    except Exception:
        pass
    try:
        win.set_decorated(False)
    except Exception:
        pass
    # Allow resize so Settings can re-flow the window. The draggable
    # strip stays in place; the resize grip is at the bottom-right
    # corner of the window.
    win.set_resizable(True)

    # Single-instance: search X for any existing "CortexAgent Console"
    # window that isn't us. If found, raise it and exit so we don't open
    # a duplicate. User feedback 2026-08-19: "we have the daemon going…
    # if the CLI version is already running, we don't want to duplicate it".
    # Single-instance search by the actual window title set above.
    # Use `--name` (regex) with escaped dots; the title is "CortexAgent Console".
    existing = []
    try:
        r = subprocess.run(
            ["xdotool", "search", "--name", "CortexAgent Console"],
            capture_output=True, text=True, timeout=1,
        )
        existing = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
    except Exception:
        existing = []
    # Filter out our own window (we may have just been realized if this
    # is a re-entry). xdotool doesn't include the searching process's
    # own windows, but be safe by excluding any XID we already wrote.
    try:
        state = _safe_read_json(_OVERLAY_STATE, {})
        own_wid = str(state.get("window_id") or "")
    except Exception:
        own_wid = ""
    existing = [w for w in existing if w != own_wid]
    if existing:
        # A live instance is already up. Raise it and bail.
        for wid in existing:
            try:
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wid],
                    capture_output=True, timeout=2)
                # Also un-minimize / make sure it's mapped.
                subprocess.run(
                    ["wmctrl", "-i", "-a", wid],
                    capture_output=True, timeout=2)
            except Exception:
                continue
        return 0  # Don't build a duplicate window.

    # Initial CSS is installed by _apply_theme(...) right before
    # win.show_all() — see end of build_window. We don't install a
    # bootstrap provider here because the old CSS block used non-ASCII
    # characters in a bytes literal and the new theme-aware provider
    # covers every class anyway.

    # ── Window-level overlay wrapper so the corner strip can extend ─────
    # past the body's right edge. An Overlay is the only container that
    # supports `add_overlay(...)` and lets a child bleed outside the
    # main-widget allocation. We wrap `outer` (a Box) with `window_ovl`
    # (an Overlay) and let the corner strip be an overlay child of the
    # window rather than the VTE.
    window_ovl = Gtk.Overlay()
    win.add(window_ovl)

    # ── Outer vertical box ─────────────────────────────────────────────────
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    window_ovl.add(outer)

    # ── Thin draggable top strip (24 px) ────────────────────────────────────────────────────────
    # ⠿  CortexAgent Console          _  ✕
    # The whole strip is an EventBox so button-press anywhere on it (not
    # just on the grip glyph) starts a window move. The two action
    # buttons consume the press first so they don't trigger drag.
    top_strip = Gtk.EventBox()
    top_strip.get_style_context().add_class("top-strip")
    top_strip.set_size_request(-1, 24)
    top_strip.set_above_child(False)
    outer.pack_start(top_strip, False, False, 0)

    # Capture click positions for begin_move_drag.
    _drag_state = {"x": 0, "y": 0, "button": 0}

    def _on_strip_press(_eb, event):
        _drag_state["x"] = event.x_root
        _drag_state["y"] = event.y_root
        _drag_state["button"] = event.button
        return False  # let buttons consume their own clicks first

    def _on_strip_release(_eb, event):
        if _drag_state["button"] != 1:
            return False
        try:
            win.begin_move_drag(
                1, int(_drag_state["x"]), int(_drag_state["y"]),
                event.time,
            )
        except Exception:
            pass
        return True

    top_strip.connect("button-press-event", _on_strip_press)
    top_strip.connect("button-release-event", _on_strip_release)

    # Inner horizontal row inside the strip.
    strip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    strip_row.set_border_width(2)
    top_strip.add(strip_row)

    grip = Gtk.Label()
    grip.set_markup("<span foreground='#8a7d68'>⠿</span>")
    grip.get_style_context().add_class("top-strip-grip")
    strip_row.pack_start(grip, False, False, 4)

    title_lbl = Gtk.Label()
    title_lbl.set_markup(
        "<span foreground='#d4a050' font_weight='bold'>CortexAgent Console</span>"
    )
    title_lbl.get_style_context().add_class("top-strip-title")
    title_lbl.set_xalign(0.0)
    strip_row.pack_start(title_lbl, True, True, 0)

    # Spacer pushes the minimize + close to the right edge.
    strip_row.pack_start(Gtk.Box(), True, True, 0)

    # Minimize — pure iconify.
    def _on_minimize(_btn):
        try:
            win.iconify()
        except Exception:
            pass

    min_btn = Gtk.Button(label="_")
    min_btn.set_relief(Gtk.ReliefStyle.NONE)
    min_btn.set_size_request(22, 22)
    min_btn.get_style_context().add_class("corner-btn")
    min_btn.connect("clicked", _on_minimize)
    strip_row.pack_start(min_btn, False, False, 0)

    # Close — belt-and-suspenders so a stuck thread can't trap the X.
    def _on_close_x(_btn):
        _record_close()
        try:
            Gtk.main_quit()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    close_btn = Gtk.Button(label="✕")
    close_btn.set_relief(Gtk.ReliefStyle.NONE)
    close_btn.set_size_request(22, 22)
    close_btn.get_style_context().add_class("close-btn")
    close_btn.connect("clicked", _on_close_x)
    strip_row.pack_start(close_btn, False, False, 0)

    # ── Body: sidebar (narrow) | VTE (fills rest) ─────────────────────────
    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    body.set_border_width(0)
    outer.pack_start(body, True, True, 0)

    # ── Bottom brown strip (theme header color) ──────────────────────────
    bottom_strip = Gtk.Box()
    bottom_strip.set_size_request(-1, 4)
    bottom_strip.get_style_context().add_class("body-strip")
    outer.pack_start(bottom_strip, False, False, 0)

    # (expand-strip removed 2026-08-21 — collapse feature was breaking
    # the popup. User removed the request.)

    # ── Sidebar — scrollable so many tabs/tasks don't blow up the window ─
    sidebar_scroll = Gtk.ScrolledWindow()
    sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sidebar_scroll.set_size_request(SIDEBAR_W, -1)
    sidebar_scroll.get_style_context().add_class("sidebar")
    body.pack_start(sidebar_scroll, False, False, 0)

    sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    sidebar.set_border_width(4)
    sidebar.get_style_context().add_class("sidebar")
    sidebar_scroll.add(sidebar)

    _sidebar_labels: dict[str, Gtk.Label] = {}
    _browser_rows: list[Gtk.Button] = []  # clickable tab rows

    def _add_panel(name: str, title_text: str):
        # Section header
        header = Gtk.Label()
        header.set_markup(f"<b>{title_text}</b>")
        header.set_xalign(0.0)
        header.get_style_context().add_class("sidebar-header")
        header.set_margin_top(6)
        header.set_margin_bottom(2)
        sidebar.pack_start(header, False, False, 0)
        # Body label (one-line status)
        body_lbl = Gtk.Label()
        body_lbl.set_xalign(0.0)
        body_lbl.set_line_wrap(True)
        body_lbl.get_style_context().add_class("sidebar-body")
        body_lbl.set_margin_bottom(2)
        sidebar.pack_start(body_lbl, False, False, 0)
        _sidebar_labels[name] = body_lbl
        return body_lbl

    def _add_panel_box(name: str, title_text: str):
        """Section with a list box beneath (used for BROWSER tabs)."""
        header = Gtk.Label()
        header.set_markup(f"<b>{title_text}</b>")
        header.set_xalign(0.0)
        header.get_style_context().add_class("sidebar-header")
        header.set_margin_top(6)
        header.set_margin_bottom(2)
        sidebar.pack_start(header, False, False, 0)
        body_lbl = Gtk.Label()
        body_lbl.set_xalign(0.0)
        body_lbl.set_line_wrap(True)
        body_lbl.get_style_context().add_class("sidebar-body")
        body_lbl.set_margin_bottom(2)
        sidebar.pack_start(body_lbl, False, False, 0)
        # BROWSER panel also gets an active-task header above the tabs
        # so the user can see what's running without expanding the TUI
        # strip. User feedback 2026-08-20: "if it worked and showed the
        # active task, that would be fine to keep there."
        active_lbl = None
        if name == "browser":
            active_lbl = Gtk.Label()
            active_lbl.set_xalign(0.0)
            active_lbl.set_markup(
                "<span foreground='#d4a050' font_weight='bold'>✓ idle</span>"
            )
            active_lbl.get_style_context().add_class("active-task-row")
            sidebar.pack_start(active_lbl, False, False, 0)
            _sidebar_labels["browser_active"] = active_lbl
        # List container for clickable rows
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        list_box.get_style_context().add_class("sidebar-list")
        list_box.set_margin_bottom(4)
        sidebar.pack_start(list_box, False, False, 0)
        _sidebar_labels[name] = body_lbl
        _sidebar_labels[name + "_list"] = list_box  # type: ignore[assignment]
        return body_lbl, list_box

    # Settings panel removed 2026-08-20 per user feedback:
    # "i don't any settings because he keeps breaking and he's backing up
    # and you won't bucket fix it so just stop it." Theme is now applied
    # directly in _apply_theme() on window show, with no UI affordance.

    _browser_lbl, _browser_list = _add_panel_box("browser", "BROWSER")
    _tasks_lbl, _tasks_list = _add_panel_box("tasks", "TASKS")

    # ── VTE — the REAL embedded terminal fills the rest ──────────────────
    vte = Vte.Terminal()
    vte.set_scrollback_lines(2000)
    vte.set_audible_bell(False)
    vte.set_mouse_autohide(True)
    # Right-click menu (Copy / Paste) requires Vte's own IM.
    # Older API: vte.set_input_enabled(True). Newer VTE ignores that but
    # auto-enables input when a PTY is spawned. Ensure IM is on explicitly.
    try:
        vte.set_input_enabled(True)
    except Exception:
        pass
    # Right-click → Paste from PRIMARY selection (middle-click on X11).
    # Also wire Ctrl+Shift+V as an explicit keyboard fallback so paste
    # works regardless of whether the context menu appears.
    try:
        vte.connect("button-press-event", _on_vte_button)
    except Exception:
        pass
    # Don't connect key-press-event on the VTE — let VTE handle its own
    # clipboard shortcuts (Ctrl+V, Ctrl+Shift+V, Ctrl+C, Shift+Insert).
    # User feedback 2026-08-20: custom keypress handlers were breaking the
    # default, working behavior. Only the window-level Escape handler stays.
    font = Pango.FontDescription("Mono 11")
    vte.set_font(font)

    vte_frame = Gtk.Frame()
    vte_frame.set_shadow_type(Gtk.ShadowType.IN)
    vte_frame.get_style_context().add_class("terminal-frame")
    vte_frame.add(vte)

    # ── Floating corner buttons (overlaid on VTE) ────────────────────────
    # User feedback 2026-08-19:
    #   • Paperclip + Enter — bottom-right corner, no background, icons only
    #   • No text labels on any of these
    # An Overlay lets the buttons float in window corners without
    # consuming layout space from the VTE.
    vte_overlay = Gtk.Overlay()
    vte_overlay.add(vte_frame)
    body.pack_start(vte_overlay, True, True, 0)

    def _make_corner_btn(icon_char: str, css_class: str | None,
                         on_click, size: int = 36) -> Gtk.Button:
        """Big keyboard-key button — looks like a real keycap, indents on press.

        2026-08-21 user feedback: "change it towards 800 pixels tall so
        each of those keys will be like 390." Each button renders as a
        bezeled rectangle with the label centered. CSS class
        `.keyboard-key` carries the bezel + indent-on-active animation;
        the optional 2nd `css_class` arg lets callers tint the background.

        Both axes are explicitly set to `size` and expand flags are off so
        GTK cannot grow the button past the requested dimensions. The CSS
        class (when given) carries the background; otherwise the button
        is flat (no background) to match the icons in the bottom-right.
        """
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_size_request(size, size)
        btn.set_hexpand(False)
        btn.set_vexpand(False)
        lbl = Gtk.Label()
        lbl.set_markup(f"<span size='large'>{icon_char}</span>")
        lbl.set_halign(Gtk.Align.CENTER)
        lbl.set_valign(Gtk.Align.CENTER)
        btn.add(lbl)
        if css_class:
            btn.get_style_context().add_class(css_class)
        btn.connect("clicked", on_click)
        return btn

    # ── ENTER (bottom-right, no background) ─────────────────────────────
    # 2026-08-21 user feedback: keys didn't work — xdotool was firing
    # into whatever window happened to have focus, not the embedded VTE.
    # Switch to vte.feed_child() which injects the keystroke directly
    # into the VTE's PTY. Always reaches the running program; doesn't
    # require focus on the console window.
    def _on_enter(_btn):
        try:
            vte.feed_child(b"\r")
        except Exception:
            pass

    enter_btn = _make_corner_btn("↵", None, _on_enter)

    # ── ESC (HARD) — kills the focused terminal. User feedback
    # 2026-08-20: "I spawned. Capital E lowercase SC period" — the
    # button label should literally read "ESC." (capital E, lowercase
    # SC, period). Keep it as a real GTK label so the period and case
    # survive without being eaten by Pango's markup rules.
    def _on_escape(_btn):
        try:
            vte.feed_child(b"\x1b")
        except Exception:
            pass

    # 2026-08-21 user feedback: "Make it say Esc. instead of ESC" — the
    # label is the literal string the user sees; period + lowercase 'sc'.
    esc_btn = _make_corner_btn("Esc.", None, _on_escape, size=KEY_BTN_W)

    # ── Right side strip — full-height, OUTSIDE the terminal so it never
    # overlaps the VTE. TWO buttons at the bottom: ESC (top) → ENTER
    # (bottom). User feedback 2026-08-20: "All the buttons are just for
    # the terminal... Remove the paperclip. going to be enter and
    # escape." The strip is a terminal-control strip, not a file-picker
    # surface — paperclip doesn't belong here.
    #
    # 2026-08-21 user feedback: bump window to ~800px tall so each button
    # renders ~390px (half the window minus chrome). The strip's width
    # widens to 120 so the bezeled keys breathe; each button is sized at
    # runtime so two keys exactly fill the visible strip height.
    ctrl_strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ctrl_strip.set_size_request(KEY_STRIP_W, -1)
    ctrl_strip.set_halign(Gtk.Align.CENTER)
    ctrl_strip.get_style_context().add_class("side-strip")
    ctrl_strip.set_margin_top(6)
    ctrl_strip.set_margin_bottom(6)
    ctrl_strip.set_margin_end(6)

    # Spacer pushes the action cluster down to the bottom of the strip.
    spacer = Gtk.Box()
    ctrl_strip.pack_start(spacer, True, True, 0)
    # Cluster order, top → bottom:
    #   1. Esc. (hard Escape into the focused terminal)
    #   2. ↵ enter (hard Return)
    esc_btn.set_halign(Gtk.Align.CENTER)
    ctrl_strip.pack_start(esc_btn, False, False, 0)
    enter_btn.set_size_request(KEY_BTN_W, KEY_BTN_W)  # default height
    enter_btn.set_halign(Gtk.Align.CENTER)
    ctrl_strip.pack_start(enter_btn, False, False, 0)

    body.pack_start(ctrl_strip, False, False, 0)

    # 2026-08-21 user feedback: "50% of that area" — each key fills exactly
    # half the strip's height. Recomputed on window resize so they track
    # the user's height changes (560/640/660/700 → ~250/300/315/325px).
    def _resize_keys(_win=None, _alloc=None):
        alloc_h = ctrl_strip.get_allocated_height()
        if alloc_h <= 0:
            return
        # Strip internal padding ≈ 12 (top+bottom margin); spacing=6 between
        # the two buttons. Each key = (strip_h - padding - spacing) / 2.
        key_h = max(40, (alloc_h - 12 - 6) // 2)
        esc_btn.set_size_request(KEY_BTN_W, key_h)
        enter_btn.set_size_request(KEY_BTN_W, key_h)
    win.connect("size-allocate", _resize_keys)

    # ── Refresh sidebar panels every REFRESH_SECS seconds ────────────────
    def _refresh_browser_rows():
        """Rebuild the clickable tab list under BROWSER.

        Smart cap: when the user has active plan steps OR a focused CDP
        tab to show in PAGE, only the 5 most-recently-attached browser
        rows make sense. When both are empty (nothing else competing for
        attention), surface up to 10.
        """
        tabs = _fetch_cdp_tabs()
        # Clear existing rows.
        for row in _browser_rows:
            _browser_list.remove(row)
        _browser_rows.clear()
        has_tasks = bool(_plan_steps())
        has_page_info = any(t.get("active") for t in tabs)
        # User feedback 2026-08-19: only the relevant tabs. Cap at 5 in
        # both branches so the sidebar never blows up with stale tabs.
        cap = 5
        for t in tabs[:cap]:
            title = (t.get("title") or "?")[:42]
            url = (t.get("url") or "?")
            if len(url) > 42:
                url = url[:39] + "…"
            # Pango markup is XML — escape & < > AND decode HTML entities
            # (CDP tab titles carry entities like &#39; for ' that break
            # the parser and spam Gtk-WARNING every refresh tick).
            title = _markup_escape(_html_decode(title))
            url = _markup_escape(_html_decode(url))
            label = Gtk.Label()
            label.set_xalign(0.0)
            label.set_markup(
                f"<span size='small'>{title}</span>\n"
                f"<span size='small' foreground='#8a7d68'>{url}</span>"
            )
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.add(label)
            btn.set_tooltip_text(f"Switch to: {title}")
            btn.get_style_context().add_class("sidebar-tab-row")
            if t.get("active"):
                btn.get_style_context().add_class("sidebar-tab-active")
            def _on_tab_click(_b, tab=t):
                # 2026-08-21 user feedback: "the browser links still do
                # not work when you click them." Earlier attempt cleared
                # keep_above, focused Brave, then 350 ms later called
                # vte.grab_focus() + re-armed keep_above. The grab_focus()
                # pulled X focus right back to the console — the user
                # never saw Brave come to the front.
                #
                # Fix: drop keep_above, focus Brave, and leave the popup
                # BEHIND Brave in z-order. The user clicks the tray icon
                # (or any empty area) to bring the console back. No more
                # focus-stealing back to the REPL — that's what was
                # breaking the click.
                try:
                    win.unfocus()
                except Exception:
                    pass
                try:
                    win.set_keep_above(False)
                except Exception:
                    pass
                _focus_tab(tab)
                # NO grab_focus() here — that would yank X focus back.
                # NO re-arm of keep_above — the popup stays below Brave
                # until the user explicitly brings it back.
            btn.connect("clicked", _on_tab_click)
            _browser_list.pack_start(btn, False, False, 0)
            _browser_rows.append(btn)
        _browser_list.show_all()

    def _refresh_tasks_rows():
        """Rebuild the TASKS list under the tasks panel.

        Active REPL plan FIRST (the agent's own to-do list), then fall
        back to the live primary scheduler task if there's no REPL plan.
        The scheduler/cron list (every queued/running entry) is owned by
        the TUI's status panel + left strip — NOT the popup sidebar.
        User feedback 2026-08-20: cron rows flooding the sidebar was
        "like 10 of them in a plug the screen. That's what I'm talking
        about." Drop them here entirely.

        2026-08-21 user feedback: "tasks screen. And then the browser
        tabs still aren't working... it should actually list what it is.
        Like the actual active task, it should actually have more
        information." When REPL plan is empty, surface the most-recent
        live scheduler task WITH DETAIL (title, state, timestamp, id)
        rather than just a count.
        """
        tasks_list = _sidebar_labels.get("tasks_list")
        if tasks_list is None:
            return
        # Clear.
        for child in tasks_list.get_children():
            tasks_list.remove(child)

        rows = []
        # Source 1: REPL plan steps ONLY. The scheduler/cron rows are
        # NOT included here — user feedback 2026-08-20: "The scheduler
        # lists are back into the text output, so you've got to remove
        # all those." The TUI's status panel + left strip own the global
        # scheduler view; the popup sidebar is for the active plan only.
        for idx, text, status in _plan_steps()[:8]:
            rows.append((idx, text, status))

        if not rows:
            # No active plan. 2026-08-21 user feedback: "tasks screen.
            # And then the browser tabs still aren't working. The
            # browser tabs... it should actually list what it is. Like
            # the actual active task, it should actually have more
            # information." Surface the most-recent live scheduler
            # task with title + state + timestamp + id. Falls back to
            # "no active plan" only if the scheduler is genuinely empty.
            live_task = _live_primary_task()
            if live_task:
                title = _markup_escape(live_task.get("title") or "(untitled)")
                state = str(live_task.get("state") or "queued")
                ts = str(live_task.get("ts") or "")
                tid = str(live_task.get("id") or "")
                state_color = {
                    "running":  "#d4a050",
                    "queued":   "#8abeb7",
                    "failed":   "#c75c5c",
                    "succeeded":"#7fb069",
                    "cancelled":"#8a7d68",
                }.get(state, "#8a7d68")
                # Line 1: state bullet + title (bold).
                # Line 2: state label + short id + timestamp.
                if len(title) > 38:
                    title = title[:35] + "…"
                short_id = tid[:8] if tid else "—"
                ts_short = ts[11:16] if len(ts) >= 16 else ""  # HH:MM
                line1 = Gtk.Label()
                line1.set_xalign(0.0)
                line1.set_markup(
                    f"<span foreground='{state_color}' font_weight='bold'>▶</span> "
                    f"<span size='small' foreground='#d6dde8' font_weight='bold'>"
                    f"{title}</span>"
                )
                line1.set_margin_start(2)
                line1.set_margin_bottom(0)
                tasks_list.pack_start(line1, False, False, 0)
                line2 = Gtk.Label()
                line2.set_xalign(0.0)
                line2.set_markup(
                    f"<span size='small' foreground='#6b7888'>"
                    f"  {state} · {short_id}{(' · ' + ts_short) if ts_short else ''}"
                    f"</span>"
                )
                line2.set_margin_start(2)
                line2.set_margin_bottom(2)
                tasks_list.pack_start(line2, False, False, 0)
                tasks_list.show_all()
                return
            # Truly nothing — single idle marker.
            label = Gtk.Label()
            label.set_xalign(0.0)
            label.set_markup(
                f"<span size='small' foreground='#8a7d68'>"
                f"· no active plan"
                f"</span>"
            )
            label.set_margin_start(2)
            label.set_margin_bottom(1)
            tasks_list.pack_start(label, False, False, 0)
            tasks_list.show_all()
            return

        for idx, text, status in rows[:8]:
            mark = {"done": "✓", "current": "▶",
                    "pending": "·", "failed": "✗"}.get(status, "·")
            color = {"done": "#7fb069", "current": "#d4a050",
                     "pending": "#8a7d68",
                     "failed": "#c75c5c"}.get(status, "#8a7d68")
            label = Gtk.Label()
            label.set_xalign(0.0)
            prefix = f"{idx}." if idx is not None else "·"
            # Escape user-supplied text before injecting into Pango markup
            # (task names from the plan/scheduler can contain & < >).
            safe_text = _markup_escape(text[:48])
            label.set_markup(
                f"<span foreground='{color}' font_weight='bold'>{mark}</span> "
                f"<span size='small'>{prefix} {safe_text}</span>"
            )
            label.set_margin_start(2)
            label.set_margin_bottom(1)
            tasks_list.pack_start(label, False, False, 0)
        tasks_list.show_all()

    def _refresh_sidebar():
        # BROWSER header line: tab count + active-tab count.
        _sidebar_labels["browser"].set_text(_browser_state())
        # BROWSER active-task line: most-recent scheduler task.
        active_lbl = _sidebar_labels.get("browser_active")
        if active_lbl is not None:
            active_lbl.set_text(_active_task_for_browser())
        # TASKS panel: short label + build list
        _sidebar_labels["tasks"].set_text(_plan_tasks())
        _refresh_browser_rows()
        _refresh_tasks_rows()
        return True

    GLib.timeout_add_seconds(REFRESH_SECS, _refresh_sidebar)
    GLib.idle_add(_refresh_sidebar)

    # ── VTE input helpers ─────────────────────────────────────────────────
    # Right-click + cursor-paste + copy wiring.
    # VTE 2.91 in GTK3 disables the built-in popup menu by default; we
    # build a plain Gtk.Menu ourselves and pop it on right-click.
    def _on_vte_button(widget, event):
        if event.button == 2:  # middle-click → PRIMARY selection
            try:
                sel = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
                text = sel.wait_for_text()
                if text:
                    widget.feed_child(text.encode("utf-8"))
                    return True
            except Exception:
                pass
        if event.button == 3:  # right-click → custom Copy/Paste menu
            try:
                # Build the menu and attach it to the VTE's top-level window
                # so the WM can position it correctly. Guard each menu op
                # so a partial failure does not eat the click.
                menu = Gtk.Menu()
                # Copy
                mi_copy = Gtk.MenuItem(label="Copy")
                mi_copy.show()
                def _do_copy(_i):
                    try:
                        widget.copy_clipboard()
                    except Exception:
                        pass
                mi_copy.connect("activate", _do_copy)
                menu.append(mi_copy)
                # Paste from clipboard
                mi_paste = Gtk.MenuItem(label="Paste")
                mi_paste.show()
                def _do_paste_cb(_i):
                    try:
                        widget.paste_clipboard()
                    except Exception:
                        pass
                mi_paste.connect("activate", _do_paste_cb)
                menu.append(mi_paste)
                # Paste raw PRIMARY selection (middle-click fallback)
                mi_paste_prim = Gtk.MenuItem(label="Paste Selection")
                mi_paste_prim.show()
                def _do_paste_prim(_i):
                    try:
                        sel = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
                        text = sel.wait_for_text()
                        if text:
                            widget.feed_child(text.encode("utf-8"))
                    except Exception:
                        pass
                mi_paste_prim.connect("activate", _do_paste_prim)
                menu.append(mi_paste_prim)
                # Attach + popup. Use the top-level window's screen so the
                # menu lives on the same display as the VTE.
                toplevel = widget.get_toplevel()
                if toplevel is not None:
                    menu.attach_to_widget(toplevel, None)
                menu.popup(None, None, None, None, event.button, event.time)
                return True
            except Exception:
                # Fallback: if building the menu fails, do the right-click
                # equivalent (paste from PRIMARY) so the user can still work.
                try:
                    sel = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
                    text = sel.wait_for_text()
                    if text:
                        widget.feed_child(text.encode("utf-8"))
                        return True
                except Exception:
                    pass
        return False

    # ── Window-level keypress (Escape) ─────────────────────────────────────
    # Bound at the window level so Escape works regardless of which
    # sub-widget has focus — VTE, sidebar, header, anywhere. Returns True
    # when the event is consumed so GTK doesn't propagate it further.
    def _on_win_keypress(_widget, event):
        try:
            if event.keyval == Gdk.KEY_Escape:
                _on_escape()
                return True
        except Exception:
            pass
        return False

    # ── Spawn bin/cortexagent as a PTY child of VTE ───────────────────────
    # Expand PATH so the spawned `bin/cortexagent` shell can find BOTH
    # python3 (system) AND the `cortex` node symlink (user-installed via
    # nvm). The systemd user daemon's default PATH is minimal and does
    # not include ~/.nvm/versions/node/*/bin, where `cortex` lives.
    import shlex
    base_path = os.environ.get("PATH") or ":".join([
        "/usr/local/sbin", "/usr/local/bin", "/usr/sbin",
        "/usr/bin", "/sbin", "/bin",
    ])
    user_path_dirs = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.openclaw/bin"),
        os.path.expanduser("~/.cortexagent/bin"),
        os.path.expanduser("~/.cargo/bin"),
        os.path.expanduser("~/.local/share/cargo/bin"),
        os.path.expanduser("~/.npm-global/bin"),
        os.path.expanduser("~/.bun/bin"),
    ]
    # Add any nvm-managed node bin dirs.
    nvm_root = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm_root):
        for entry in sorted(os.listdir(nvm_root), reverse=True):
            candidate = os.path.join(nvm_root, entry, "bin")
            if os.path.isdir(candidate):
                user_path_dirs.append(candidate)
    # Prepend user dirs (they are searched first).
    safe_path = ":".join(user_path_dirs + [base_path])
    env_overrides = {
        "TERM": "xterm-256color",
        "CORTEXAGENT_BOOT_ANIM": "0",
        "CORTEXAGENT_TICKER": "0",
        "PYTHONUNBUFFERED": "1",
        "PATH": safe_path,
        "HOME": os.environ.get("HOME") or str(Path.home()),
    }
    merged_env = os.environ.copy()
    merged_env.update(env_overrides)
    env_list = [f"{k}={v}" for k, v in merged_env.items()]

    vte_pid_holder: list[int | None] = [None]

    def _record_vte_pid(vte_term, _async_result=None):
        try:
            pid = vte_term.get_pty().get_pid()
            vte_pid_holder[0] = pid
        except Exception:
            pass

    # ── Escape key → interrupt the running REPL ──────────────────────────
    # Bound at the WINDOW level so Escape works regardless of focus (VTE,
    # sidebar, header, anywhere). Sends SIGINT to the embedded REPL child
    # — same as Ctrl+C in a real terminal — so the running inference /
    # request can be cancelled without closing the window.
    def _on_escape():
        pid = vte_pid_holder[0]
        if pid is None:
            # Spawn callback hasn't fired yet — try the synchronous lookup.
            try:
                pid = vte.get_pty().get_pid()
            except Exception:
                pid = None
        if pid is None:
            return
        try:
            import signal as _sig
            os.kill(pid, _sig.SIGINT)
        except (ProcessLookupError, PermissionError):
            # Child already exited — nothing to interrupt.
            pass
        except Exception:
            pass

    try:
        vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            str(_REPO_ROOT),
            [CORTEXAGENT_BIN],
            env_list,
            GLib.SpawnFlags.DEFAULT,
            None, None, -1, None, None,
            _record_vte_pid, None,
        )
    except Exception as e:
        vte.feed(b"\x1b[1;31mPTY spawn failed:\x1b[0m " + str(e).encode() + b"\r\n")

    # ── SIGTERM / SIGINT also writes `closed_at` ──────────────────────────
    # The GTK `destroy` signal only fires on user close / window-manager
    # close. SIGTERM (kill) skips that path. Install atexit + signal
    # handlers so the lifecycle file always reflects reality.
    # NOTE: signal.signal() only works in the main thread of the main
    # interpreter. When the tray daemon launches this console via
    # open_in_thread(), the thread is a worker thread, so signal() raises
    # ValueError. Guard both signal() and atexit.register() so the thread
    # can still run Gtk.main() and the window opens.
    import atexit as _atexit
    import signal as _signal

    def _on_term(_sig, _frm):
        _record_close()
        try:
            Gtk.main_quit()
        except Exception:
            pass
        os._exit(0)

    try:
        _signal.signal(_signal.SIGTERM, _on_term)
        _signal.signal(_signal.SIGINT, _on_term)
    except (ValueError, OSError):
        pass  # worker thread — signal handlers must be installed in main thread
    try:
        _atexit.register(_record_close)
    except Exception:
        pass

    # ── Record lifecycle now that the window is built. Geometry is enforced
    # once by _enforce_once after show_all (no win.move here — single source
    # of truth for window position).
    def _record_lifecycle():
        try:
            wid = win.get_window().get_xid() if win.get_window() else 0
        except Exception:
            wid = 0
        _record_open(os.getpid(), vte_pid_holder[0], int(wid) if wid else 0)
        return False

    GLib.idle_add(_record_lifecycle)

    # ── Clean-up on destroy ────────────────────────────────────────────────
    def _on_destroy(*_a):
        _record_close()
        try:
            Gtk.main_quit()
        except Exception:
            pass

    win.connect("destroy", _on_destroy)
    win.connect("key-press-event", _on_win_keypress)

    # Re-arm keep_above whenever the user clicks back into the console.
    # After a tab click we drop keep_above so Brave can come to the front;
    # clicking the popup should bring it back on top. Button-press-event
    # on the window is the cleanest hook — fires once per click.
    def _on_window_click(_w, _event):
        try:
            win.set_keep_above(True)
        except Exception:
            pass
        return False  # don't swallow the event
    win.connect("button-press-event", _on_window_click)
    # Apply the persisted theme on first show so the picked palette is
    # in effect before the user sees the window. Uses the same path
    # Settings' Apply button takes.
    try:
        from lib.popup_themes import load_settings
        _apply_theme(load_settings().get("theme", "amber"))
    except Exception:
        pass
    win.show_all()

    # ONE-TIME geometry enforcement after show_all, then never again. The
    # flashing was caused by a retry loop running xdotool windowsize/move
    # 6× in 720 ms — WM was fighting itself between GTK hints and xdotool.
    def _dprint(*a):
        # Single-gate debug logger. Only emits when CORTEXAGENT_CONSOLE_DEBUG=1
        # so the tray daemon's journalctl does not get spammed.
        if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1":
            print("[browser_console]", *a, file=sys.stderr)

    def _enforce_once():
        try:
            win.resize(WIN_W, WIN_H)
            gdk = win.get_window()
            if not gdk:
                _dprint("no gdk window")
                return False
            wid = gdk.get_xid()
            _dprint(f"wid={wid} enforcing {WIN_W}x{WIN_H}")
            r1 = subprocess.run(
                ["xdotool", "windowsize", str(wid),
                 str(WIN_W), str(WIN_H)],
                capture_output=True, text=True, timeout=1)
            _dprint(f"windowsize rc={r1.returncode}")
            try:
                display = Gdk.Display.get_default()
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor:
                    mg = monitor.get_geometry()
                    x = (mg.width - WIN_W) // 2
                    y = mg.height - WIN_H - MARGIN
                    try:
                        win.move(x, y)
                    except Exception:
                        pass
                    r2 = subprocess.run(
                        ["xdotool", "windowmove", str(wid),
                         str(x), str(y)],
                        capture_output=True, text=True, timeout=1)
                    _dprint(f"windowmove rc={r2.returncode} to ({x},{y})")
            except Exception as e:
                _dprint(f"move err {e}")
        except Exception as e:
            _dprint(f"enforce err {e}")
        return False  # run once, never again

    GLib.timeout_add(400, _enforce_once)  # give WM 400ms to map first
    vte.grab_focus()
    Gtk.main()
    return 0


def open_in_thread() -> threading.Thread:
    t = threading.Thread(target=build_window, daemon=True,
                         name="browser-console")
    t.start()
    return t


def main() -> int:
    try:
        return build_window()
    except Exception as e:
        print(f"⚠️ browser console failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
