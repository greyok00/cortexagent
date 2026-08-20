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


def _scheduler_steps() -> list:
    """Read scheduler/tasks.json and emit sidebar rows.

    Used as the fallback (combined view) when the REPL plan file is
    absent. Matches the REPL's status panel format: ▶ running first,
    then queued.
    """
    sched_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.json"
    p = _safe_read_json(sched_path, None)
    if not isinstance(p, dict):
        return []
    tasks = p.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return []
    out = []
    for t in tasks:
        state = (t.get("state") or t.get("status") or "pending").lower()
        if state == "completed":
            status = "done"
        elif state in ("running", "in_progress", "active"):
            status = "current"
        elif state == "failed":
            status = "failed"
        else:
            status = "pending"
        title = (t.get("title") or t.get("name") or t.get("id") or "?")[:48]
        out.append((title, status))
    return out


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


def _browser_state() -> str:
    """Returns short status string for the BROWSER panel header."""
    tabs = _fetch_cdp_tabs()
    if not tabs:
        return "— :9222 offline —"
    n = len(tabs)
    active = sum(1 for t in tabs if t.get("active"))
    return f"{n} tab{'s' if n != 1 else ''} · {active} active"


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
    # Try wmctrl with -x for the app class first (most reliable).
    for pattern in ("Brave-browser", "brave-browser.Brave-browser",
                    "google-chrome.Google-chrome", "Chromium"):
        try:
            r = subprocess.run(
                ["wmctrl", "-x", "-a", pattern],
                capture_output=True, timeout=2)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            return False
    try:
        subprocess.run(
            ["wmctrl", "-a", "Brave"],
            capture_output=True, timeout=2)
        return True
    except FileNotFoundError:
        return False


def _focus_tab(tab: dict) -> bool:
    """Activate a CDP tab and raise the browser window.

    Tries in order:
      1. PRIMARY: xdotool name-search for the tab's title. Each Brave
         tab is its own X11 window (same PID, distinct WID) with its
         page title as the window name. This works regardless of CDP
         origin-policy / remote-debugging flags — user feedback
         2026-08-20: CDP WebSocket returns 403 because Brave was
         started without --remote-allow-origins=* (user refused the
         restart). HTTP /json/activate/<id> returns 404 (Chromium
         removed it). wmctrl not installed. The only path that
         actually focuses the right WINDOW is xdotool.
      2. FALLBACK: CDP WebSocket Page.bringToFront (works if the
         remote-allow flag is ever added later).
      3. FALLBACK: raise any Brave window (better than nothing — the
         user can then use Ctrl+Tab or the tab strip).
    Returns True if any of them succeeded.
    """
    title = (tab.get("title") or "").strip()
    if title:
        # xdotool name search uses a substring/regex match against
        # _NET_WM_NAME. CDP returns titles with HTML entities (e.g.
        # "what&#39;s" for "what's") but the X11 window name has the
        # decoded form. Decode first so the substring search lands on
        # the right window. Also strip the trailing " - Brave" suffix
        # Brave appends in some cases, since the user-visible CDP
        # title may already be truncated by the time we look.
        search_title = _html_decode(title)
        try:
            r = subprocess.run(
                ["xdotool", "search", "--name", search_title],
                capture_output=True, text=True, timeout=2,
            )
            wids = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
            if wids:
                # Prefer the FIRST match (newest in MRU order on most
                # WMs). windowactivate --sync blocks until the WM
                # acknowledges, so we know it landed.
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wids[0]],
                    capture_output=True, timeout=2,
                )
                # Also raise the whole app so the window isn't buried
                # under another window on the same desktop.
                subprocess.run(
                    ["xdotool", "windowraise", wids[0]],
                    capture_output=True, timeout=2,
                )
                return True
        except Exception:
            pass
    # Last-resort: CDP bringToFront (no-op if origin blocked, harmless).
    cdp_ok = _bring_tab_to_front_via_cdp(tab)
    if not cdp_ok:
        # Final fallback: just raise any Brave window. Better than
        # nothing if title-search missed (rare unicode mismatch).
        _raise_brave_window()
    return cdp_ok or _raise_brave_window()


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

def build_window() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte, GLib, Gdk, Pango

    win = Gtk.Window()
    win.set_title("CortexAgent Console")
    win.set_keep_above(True)

    # Resolve screen-size-derived dimensions BEFORE any size hints so the
    # WM honors them. If we can't reach the display yet, fall back to a
    # conservative 1200x500 default.
    global WIN_W, WIN_H
    try:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        mg = monitor.get_geometry()
        WIN_W = max(800, int(mg.width * WIN_W_PCT))
        WIN_H = max(300, int(mg.height * WIN_H_PCT))
    except Exception:
        WIN_W, WIN_H = 1200, 500

    win.set_default_size(WIN_W, WIN_H)
    win.set_size_request(WIN_W, WIN_H)
    # HeaderBar with just the ✕ close. This is what gives the WM
    # chrome to draw — without it, Muffin collapses the window to a
    # 20×20 stub. Hide the title/subtitle text so it stays minimal.
    header = Gtk.HeaderBar()
    header.set_show_close_button(False)  # only our X
    header.set_title("")
    header.set_subtitle("")
    header.set_decoration_layout("")  # no menu/title
    header.get_style_context().add_class("thin-headerbar")
    hb_close = Gtk.Button(label="x")
    hb_close.set_relief(Gtk.ReliefStyle.NONE)
    hb_close.set_size_request(20, 18)
    hb_close.set_margin_top(0)
    hb_close.set_margin_bottom(0)
    hb_close.get_style_context().add_class("close-btn")
    # Belt-and-suspenders close: quit -> destroy -> os._exit so the
    # thread cannot get stuck. User feedback 2026-08-19: "X doesn't work".
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
    hb_close.connect("clicked", _on_close_x)
    header.pack_end(hb_close)
    win.set_titlebar(header)
    # Lock the size AFTER setting the titlebar (which can reset resizable).
    # User feedback 2026-08-19: "don't allow changing the size of it".
    win.set_resizable(False)

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

    # ── CSS provider: dark theme ────────────────────────────────────────────
    css = b"""
    window { background: #0d0a07; color: #e8e0d0; }
    .title { color: #d4a050; font-weight: bold; }
    .panel-title { color: #d4a050; font-weight: bold; padding-top: 6px; }
    .panel-body { color: #c0bfb5; font-family: monospace; font-size: 11px; }
    .status-bar { color: #8a7d68; font-size: 10px; }
    /* Sidebar - polished section headers and tab/task rows */
    .sidebar-header {
        color: #d4a050;
        font-weight: bold;
        font-size: 11px;
        background: #1a1612;
        border: 1px solid #3a3530;
        border-radius: 4px;
        padding: 4px 8px;
        margin-top: 8px;
    }
    .sidebar-body { color: #cdcdcd; font-family: monospace; font-size: 10px;
                    padding: 2px 4px; }
    .sidebar-list { background: transparent; }
    /* Full sidebar background -- fills the entire left panel so it reads
    as a solid brown surface, not just a header band. Applied to the
    ScrolledWindow + inner Box so the scrollbar track also takes the
    theme. */
    .sidebar { background: #1a1612; }
    scrolledwindow.sidebar scrollbar trough { background: #1a1612; }
    scrolledwindow.sidebar scrollbar slider { background: #3a3530; }
    .sidebar-tab-row {
        background: #0d0a07;
        color: #cdcdcd;
        border: 1px solid #2a2520;
        border-radius: 3px;
        padding: 4px 6px;
        margin: 1px 0;
        font-family: monospace;
    }
    .sidebar-tab-row:hover { background: #1a1612; border-color: #d4a050; }
    .sidebar-tab-active { border-left: 3px solid #d4a050; background: #1a1612; }
    .entry { background: #1a1612; color: #e8e0d0; border: 1px solid #3a3530; padding: 6px; }
    /* Thin HeaderBar - minimal vertical padding so the X sits in a thin strip. */
    headerbar.thin-headerbar { min-height: 0; padding: 0; margin: 0; }
    headerbar.thin-headerbar button { padding: 0 4px; margin: 0; min-height: 18px; }
    /* Close X button: no border, hover hint only. */
    .close-btn {
        background: transparent;
        color: #d4a050;
        border: none;
        padding: 0;
        font-weight: bold;
    }
    .close-btn:hover { background: #5a3d3d; color: #e8d4c8; }
    /* Top + bottom brown strips around the body (theme header color). */
    .body-strip { background: #1a1612; border-top: 1px solid #3a3530;
                  border-bottom: 1px solid #3a3530; }
    /* Brown corner strip on the right - matches the sidebar header color.
    Visible rounded outline + subtle drop-shadow so the strip reads as
    "sticking out" of the window even when the window's own border is
    dark. */
    .corner-strip {
        background: #1a1612;
        border: 1px solid #d4a050;
        border-radius: 6px;
        padding: 4px;
        box-shadow: 0 0 0 1px #d4a050, 0 2px 6px rgba(0,0,0,0.6);
    }
    /* Bordered terminal: thin brown frame so the VTE looks intentional. */
    /* Bordered terminal: thin brown frame so the VTE looks intentional. */
    frame.terminal-frame { border: 1px solid #3a3530; background: #1a1612; padding: 2px; }
    vte { border: 1px solid #3a3530; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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

    # (Window ✕ close lives in the HeaderBar set above. No in-body bar.)

    # ── Top brown strip (theme header color) ─────────────────────────────
    top_strip = Gtk.Box()
    top_strip.set_size_request(-1, 4)
    top_strip.get_style_context().add_class("body-strip")
    outer.pack_start(top_strip, False, False, 0)

    # ── Body: sidebar (narrow) | VTE (fills rest) ─────────────────────────
    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    body.set_border_width(0)
    outer.pack_start(body, True, True, 0)

    # ── Bottom brown strip (theme header color) ──────────────────────────
    bottom_strip = Gtk.Box()
    bottom_strip.set_size_request(-1, 4)
    bottom_strip.get_style_context().add_class("body-strip")
    outer.pack_start(bottom_strip, False, False, 0)

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
        # List container for clickable rows
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        list_box.get_style_context().add_class("sidebar-list")
        list_box.set_margin_bottom(4)
        sidebar.pack_start(list_box, False, False, 0)
        _sidebar_labels[name] = body_lbl
        _sidebar_labels[name + "_list"] = list_box  # type: ignore[assignment]
        return body_lbl, list_box

    _browser_lbl, _browser_list = _add_panel_box("browser", "BROWSER")
    _tasks_lbl, _tasks_list = _add_panel_box("tasks", "TASKS")
    _add_panel("page", "PAGE")

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
        """Icon-only square button. NO text, NO padding, fixed size.

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
        # 'large' (not 'x-large') keeps the icon glyph inside the box.
        lbl.set_markup(f"<span size='large'>{icon_char}</span>")
        lbl.set_halign(Gtk.Align.CENTER)
        lbl.set_valign(Gtk.Align.CENTER)
        btn.add(lbl)
        if css_class:
            btn.get_style_context().add_class(css_class)
        btn.connect("clicked", on_click)
        return btn

    # ── ATTACH (bottom-right, no background) ────────────────────────────
    def _on_attach(_btn):
        chooser = Gtk.FileChooserNative.new(
            "Attach a file", win,
            Gtk.FileChooserAction.OPEN, "_Open", "_Cancel")
        all_filt = Gtk.FileFilter()
        all_filt.set_name("All files")
        all_filt.add_pattern("*")
        chooser.add_filter(all_filt)
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        img_filter.add_mime_type("image/*")
        chooser.add_filter(img_filter)
        chooser.set_modal(True)

        def _on_response(dialog, response):
            try:
                if response != Gtk.ResponseType.ACCEPT:
                    return
                chosen = chooser.get_filename()
                if not chosen:
                    return
                # Type the raw path (no quoting) so the REPL can read it
                # as a filename. --delay 1 keeps the REPL input stable.
                # User feedback 2026-08-20: paperclip is JUST a path-typer.
                # No vision routing, no model swap — those are separate
                # concerns. Image handling is the REPL's job, not the
                # console's.
                subprocess.run(
                    ["xdotool", "type", "--delay", "1", str(chosen)],
                    check=False, timeout=5)
            finally:
                chooser.destroy()

        chooser.connect("response", _on_response)
        chooser.show()

    # No CSS class on these — no background. Icon only.
    attach_btn = _make_corner_btn("📎", None, _on_attach)

    # ── ENTER (bottom-right, no background) ─────────────────────────────
    def _on_enter(_btn):
        try:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "Return"],
                check=False, timeout=1)
        except Exception:
            pass

    enter_btn = _make_corner_btn("↵", None, _on_enter)

    # Stack paperclip + enter vertically inside the overlay (REVERTED
    # 2026-08-20: a separate undecorated window caused SIGSEGV + a
    # runaway idle_add that starved the main loop and broke the
    # console entirely. Restoring the original in-overlay placement.
    bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    bottom_box.set_halign(Gtk.Align.END)
    bottom_box.set_valign(Gtk.Align.END)
    bottom_box.set_margin_end(0)
    bottom_box.set_margin_bottom(6)
    bottom_box.set_size_request(56, 96)
    bottom_box.get_style_context().add_class("corner-strip")
    bottom_box.pack_start(attach_btn, False, False, 0)
    bottom_box.pack_start(enter_btn, False, False, 0)
    window_ovl.add_overlay(bottom_box)

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
                _focus_tab(tab)
                # Return focus to the embedded REPL so the user can keep typing.
                try:
                    vte.grab_focus()
                except Exception:
                    pass
            btn.connect("clicked", _on_tab_click)
            _browser_list.pack_start(btn, False, False, 0)
            _browser_rows.append(btn)
        _browser_list.show_all()

    def _refresh_tasks_rows():
        """Rebuild the TASKS list under the tasks panel.

        Combined view (user feedback 2026-08-20): plan steps first if
        the REPL has an active plan, then fall back to scheduler rows.
        """
        tasks_list = _sidebar_labels.get("tasks_list")
        if tasks_list is None:
            return
        # Clear.
        for child in tasks_list.get_children():
            tasks_list.remove(child)

        rows = []
        # Source 1: REPL plan steps
        for idx, text, status in _plan_steps()[:8]:
            rows.append((idx, text, status))
        # Source 2 (fallback): scheduler rows when no plan steps exist
        if not rows:
            for text, status in _scheduler_steps()[:8]:
                rows.append((None, text, status))

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
        for key, src in (("browser", _browser_state),
                          ("page", _page_snapshot)):
            _sidebar_labels[key].set_text(src())
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
