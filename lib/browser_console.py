#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path



_REPO_ROOT = Path(__file__).resolve().parent.parent
CORTEXAGENT_BIN = str(_REPO_ROOT / "bin" / "cortexagent")

_OVERLAY_STATE = Path.home() / ".cortexagent" / "overlay_state.json"
_SCHED_STATE_DIR = Path.home() / ".cortexagent"
MINIFY_STATS = Path.home() / ".cortexagent" / "minify_stats.json"



WIN_W_PCT, WIN_H_PCT = 0.625, 0.25
WIN_W, WIN_H = 0, 0
MARGIN = 16


SIDEBAR_W = 280







KEY_STRIP_W = 120
KEY_BTN_W = 110

REFRESH_SECS = 3




_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp",
               ".bmp", ".tif", ".tiff", ".avif"}


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTS




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
    clear_pending()


def mark_pending() -> None:
    """Mark a Console launch as imminent. raise_existing() honors this so
    the tray menu's Open Console click doesn't open a 2nd window when the
    auto-launch block already has one in flight."""
    try:
        if _OVERLAY_STATE.exists():
            cur = json.loads(_OVERLAY_STATE.read_text()) or {}
        else:
            cur = {}
    except Exception:
        cur = {}
    cur["state"] = "open"
    cur["pending"] = True
    cur["opened_at"] = time.time()
    if not cur.get("pid"):
        cur["pid"] = -1
    if not cur.get("window_id"):
        cur["window_id"] = 0
    _write_state(cur)


def clear_pending() -> None:
    """Called by Console after it writes its real state."""
    try:
        if not _OVERLAY_STATE.exists():
            return
        cur = json.loads(_OVERLAY_STATE.read_text()) or {}
    except Exception:
        return
    if cur.get("pending"):
        cur.pop("pending", None)
        _write_state(cur)


def _is_open() -> bool:
    """True if the Console process is alive (overlay_state has a real pid)."""
    try:
        if not _OVERLAY_STATE.exists():
            return False
        st = json.loads(_OVERLAY_STATE.read_text()) or {}
    except Exception:
        return False
    pid = st.get("pid")
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def close() -> bool:
    """Kill the running Console process + clear overlay state. Returns True
    if a process was found and killed."""
    pid = None
    try:
        if _OVERLAY_STATE.exists():
            st = json.loads(_OVERLAY_STATE.read_text()) or {}
            pid = st.get("pid")
    except Exception:
        pass
    if not pid or pid <= 0:
        pid = None
    try:
        import subprocess as _sp
        r = _sp.run(["pgrep", "-f", "lib/browser_console.py"],
                    capture_output=True, text=True, timeout=2)
        for line in (r.stdout or "").splitlines():
            try:
                p = int(line.strip())
                if p != os.getpid():
                    try:
                        os.kill(p, 15)
                    except (ProcessLookupError, PermissionError):
                        pass
            except ValueError:
                pass
    except Exception:
        pass
    if pid:
        try:
            os.kill(pid, 15)
        except (ProcessLookupError, PermissionError):
            pass
        except OSError:
            pass
    try:
        _OVERLAY_STATE.unlink()
    except Exception:
        pass
    return True


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

    plan_path = Path.home() / ".cortexagent" / "overseer_plan.json"
    p = _safe_read_json(plan_path, {})
    if p:
        name = p.get("name") or "?"
        total = p.get("total_steps", 0)
        current = p.get("current_step", 0)
        return f"{name}  ·  step {current}/{total}"

    sched = _scheduler_summary()
    if sched:
        return sched
    return "TASKS  ·  ✓ idle"


def _scheduler_summary() -> str:

    sched_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.json"
    p = _safe_read_json(sched_path, None)
    if p is None:
        return ""
    tasks = p.get("tasks") if isinstance(p, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ""
    running = [t for t in tasks if (t.get("state") or t.get("status")) == "running"]
    queued = [t for t in tasks
              if (t.get("state") or t.get("status")) not in ("completed", "failed", "running")]
    if running:
        title = (running[0].get("title") or "running")[:30]
        return f"SCHED  ·  ▶ {title}  ·  +{len(queued)} queued"
    return f"SCHED  ·  {len(queued)} queued"


def _plan_steps() -> list:

    plan_path = Path.home() / ".cortexagent" / "overseer_plan.json"
    p = _safe_read_json(plan_path, {})
    if not p:
        return []
    steps = p.get("steps") or []
    step_status = p.get("step_status") or []
    current = p.get("current_step", 0)
    out = []
    for i, s in enumerate(steps, start=1):

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

        if isinstance(s, dict):
            text = str(s.get("text") or s.get("name") or s.get("step") or
                       s.get("description") or "")
        else:
            text = str(s)
        out.append((i, text, status))
    return out


def _live_primary_task() -> dict | None:

    try:
        sched_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.json"
        events_path = Path.home() / ".cortexagent" / "scheduler" / "tasks.events.jsonl"
        by_id: dict[str, dict] = {}



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


        running = [t for t in by_id.values() if t["state"] == "running"]
        if running:
            return max(running, key=lambda t: t["ts"])
        queued = [t for t in by_id.values() if t["state"] == "queued"]
        if queued:
            return max(queued, key=lambda t: t["ts"])

        return max(by_id.values(), key=lambda t: t["ts"])
    except Exception:
        return None


def _browser_state() -> str:

    tabs = _fetch_cdp_tabs()
    if not tabs:
        return "— :9223 offline —"
    n = len(tabs)
    active = sum(1 for t in tabs if t.get("active"))
    return f"{n} tab{'s' if n != 1 else ''} · {active} active"


_SCHED_EVENTS = Path.home() / ".cortexagent" / "scheduler" / "tasks.events.jsonl"


def _active_task_for_browser() -> str:

    try:
        if not _SCHED_EVENTS.exists():
            return "✓ idle"
        lines = _SCHED_EVENTS.read_text(errors="ignore").splitlines()





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

        running = next(
            (v for v in last_by_id.values()
             if v["type"] in ("running", "start")),
            None,
        )
        if running:
            title = (running["title"] or "running").strip() or "running"
            return f"▶ {title[:38]}"

        top = max(last_by_id.values(), key=lambda v: v["ts"])




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

    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _html_decode(text: str) -> str:

    import html as _html
    return _html.unescape(text)


def _fetch_cdp_tabs() -> list:

    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "1",
             "http://127.0.0.1:9223/json"],
            capture_output=True, text=True, timeout=2,
        )
        all_tabs = json.loads(r.stdout or "[]")
    except Exception:
        return []
    pages = [t for t in all_tabs if t.get("type") == "page"]
    pages.reverse()
    return pages


def _bring_tab_to_front_via_cdp(tab: dict) -> bool:

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


                return True
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception:
        return False


def _raise_brave_window() -> bool:




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


    _ft_dprint = (lambda *a, **k:
                  print(*a, file=sys.stderr, **k)
                  if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1"
                  else None)




    cdp_ok = _bring_tab_to_front_via_cdp(tab)
    _ft_dprint(f"[focus_tab] CDP bringToFront: {cdp_ok}")
    if cdp_ok:



        try:
            win.set_keep_above(False)
        except Exception:
            pass
        if _raise_brave_window():
            return True



    title = (tab.get("title") or "").strip()
    if title:
        decoded = _html_decode(title)

        candidates = [decoded, f"{decoded} - Brave", f"{decoded} – Brave"]

        seen = set()
        candidates = [c for c in candidates
                      if c and not (c in seen or seen.add(c))]

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

                best = _pick_best_wid(wids, decoded)
                if best:









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


    cdp_ok = _bring_tab_to_front_via_cdp(tab)




    _raise_brave_window()
    return cdp_ok or True


def _pick_best_wid(wids: list[str], title: str) -> str | None:

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

    tabs = _fetch_cdp_tabs()
    if not tabs:
        return "PAGE  ·  — :9223 offline —"





    focused = next((t for t in tabs if t.get("active")), tabs[0])
    title = (focused.get("title") or "?")[:40]
    url = focused.get("url") or "?"
    if len(url) > 50:
        url = url[:47] + "…"
    return f"PAGE  ·  {title}  ·  {url}"




def _metrics_line() -> str:


    big_ok = _port_open(8080)
    proxy_ok = _port_open(8081)
    health = (
        f"{'●' if big_ok else '○'} big :8080   "
        f"{'●' if proxy_ok else '○'} proxy :8081"
    )

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

    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except Exception:
        return False


def _apply_theme(name: str) -> None:

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


def raise_existing(from_process: bool = False) -> bool:
    """Raise the existing Console window if one is running.

    Returns True if an existing window was found and raised. False otherwise.

    Two modes:
    - from_process=False (default): assumes this code is running in the same
      process as the GUI. We reach into the live Tk root if exposed. If no root
      is registered (the GUI was opened in a different process), fall through
      to the cross-process path using _OVERLAY_STATE.
    - from_process=True: this code is running in the launcher process and the
      GUI is elsewhere. We use _OVERLAY_STATE (pid + window_id) + xdotool/wmctrl.
    """
    state = {}
    try:
        if _OVERLAY_STATE.exists():
            state = json.loads(_OVERLAY_STATE.read_text())
    except Exception:
        state = {}
    if not state or state.get("state") != "open":
        return False
    # Pending sentinel: launcher wrote this and Console hasn't opened yet.
    # Treat as "another Console is imminent" so the tray no-ops.
    if state.get("pending"):
        return True
    pid = state.get("pid")
    win_id = state.get("window_id")

    if not from_process:

        try:
            if pid and os.path.exists(f"/proc/{pid}") and _GUI_TK_ROOT is not None:
                try:
                    _GUI_TK_ROOT.deiconify()
                    _GUI_TK_ROOT.lift()
                    _GUI_TK_ROOT.focus_force()
                    _GUI_TK_ROOT.attributes("-topmost", True)
                    _GUI_TK_ROOT.after(
                        250, lambda: _GUI_TK_ROOT.attributes("-topmost", False))
                    return True
                except Exception:
                    pass
        except Exception:
            pass


    try:
        import shutil, subprocess
        if win_id:

            r = subprocess.run(
                ["xdotool", "search", "--name", "Cortex Console"],
                capture_output=True, text=True, timeout=1,
            )
            for s in (r.stdout or "").split():
                if s.strip().isdigit():
                    subprocess.run(
                        ["wmctrl", "-i", "-a", s.strip()],
                        capture_output=True, timeout=1,
                    )
                    return True

        if pid and os.path.exists(f"/proc/{pid}"):
            r = subprocess.run(
                ["xdotool", "search", "--name", "Cortex Console"],
                capture_output=True, text=True, timeout=1,
            )
            for s in (r.stdout or "").split():
                if s.strip().isdigit():
                    subprocess.run(
                        ["wmctrl", "-i", "-a", s.strip()],
                        capture_output=True, timeout=1,
                    )
                    return True
    except FileNotFoundError:

        pass
    except Exception:
        pass
    return False


_GUI_TK_ROOT = None


def build_window() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte, GLib, Gdk, Pango

    win = Gtk.Window()
    win.set_title("Cortex Console")
    win.set_keep_above(True)













    global WIN_W, WIN_H
    explicit_size = None
    try:







        _REPO = str(Path(__file__).resolve().parent.parent)
        if _REPO not in sys.path:
            sys.path.insert(0, _REPO)
        from lib.popup_themes import load_settings
        s = load_settings()
        res = s.get("resolution")
        if isinstance(res, (list, tuple)) and len(res) == 2:
            try:
                w, h = int(res[0]), int(res[1])





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


    try:
        if os.environ.get("CORTEXAGENT_CONSOLE_DEBUG") == "1":
            print(f"[browser_console] WIN_W={WIN_W} WIN_H={WIN_H}", file=sys.stderr)
    except Exception:
        pass

    win.set_default_size(WIN_W, WIN_H)
    win.set_size_request(WIN_W, WIN_H)








    try:
        win.set_titlebar(None)
    except Exception:
        pass
    try:
        win.set_decorated(False)
    except Exception:
        pass



    win.set_resizable(True)







    existing = []
    try:
        r = subprocess.run(
            ["xdotool", "search", "--name", "Cortex Console"],
            capture_output=True, text=True, timeout=1,
        )
        existing = [w for w in (r.stdout or "").split() if w.strip().isdigit()]
    except Exception:
        existing = []



    try:
        state = _safe_read_json(_OVERLAY_STATE, {})
        own_wid = str(state.get("window_id") or "")
    except Exception:
        own_wid = ""
    existing = [w for w in existing if w != own_wid]
    if existing:

        for wid in existing:
            try:
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wid],
                    capture_output=True, timeout=2)

                subprocess.run(
                    ["wmctrl", "-i", "-a", wid],
                    capture_output=True, timeout=2)
            except Exception:
                continue
        return 0













    window_ovl = Gtk.Overlay()
    win.add(window_ovl)


    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    window_ovl.add(outer)






    top_strip = Gtk.EventBox()
    top_strip.get_style_context().add_class("top-strip")
    top_strip.set_size_request(-1, 24)
    top_strip.set_above_child(False)
    outer.pack_start(top_strip, False, False, 0)


    _drag_state = {"x": 0, "y": 0, "button": 0}

    def _on_strip_press(_eb, event):
        _drag_state["x"] = event.x_root
        _drag_state["y"] = event.y_root
        _drag_state["button"] = event.button
        return False

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


    strip_row.pack_start(Gtk.Box(), True, True, 0)


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


    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    body.set_border_width(0)
    outer.pack_start(body, True, True, 0)


    bottom_strip = Gtk.Box()
    bottom_strip.set_size_request(-1, 4)
    bottom_strip.get_style_context().add_class("body-strip")
    outer.pack_start(bottom_strip, False, False, 0)




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
    _browser_rows: list[Gtk.Button] = []

    def _add_panel(name: str, title_text: str):

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
        _sidebar_labels[name] = body_lbl
        return body_lbl

    def _add_panel_box(name: str, title_text: str):

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

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        list_box.get_style_context().add_class("sidebar-list")
        list_box.set_margin_bottom(4)
        sidebar.pack_start(list_box, False, False, 0)
        _sidebar_labels[name] = body_lbl
        _sidebar_labels[name + "_list"] = list_box  # type: ignore[assignment]
        return body_lbl, list_box






    _browser_lbl, _browser_list = _add_panel_box("browser", "BROWSER")
    _tasks_lbl, _tasks_list = _add_panel_box("tasks", "TASKS")


    vte = Vte.Terminal()
    vte.set_scrollback_lines(2000)
    vte.set_audible_bell(False)
    vte.set_mouse_autohide(True)



    try:
        vte.set_input_enabled(True)
    except Exception:
        pass



    try:
        vte.connect("button-press-event", _on_vte_button)
    except Exception:
        pass




    font = Pango.FontDescription("Mono 11")
    vte.set_font(font)

    vte_frame = Gtk.Frame()
    vte_frame.set_shadow_type(Gtk.ShadowType.IN)
    vte_frame.get_style_context().add_class("terminal-frame")
    vte_frame.add(vte)







    vte_overlay = Gtk.Overlay()
    vte_overlay.add(vte_frame)
    body.pack_start(vte_overlay, True, True, 0)

    def _make_corner_btn(icon_char: str, css_class: str | None,
                         on_click, size: int = 36) -> Gtk.Button:

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







    def _on_enter(_btn):
        try:
            vte.feed_child(b"\r")
        except Exception:
            pass

    enter_btn = _make_corner_btn("↵", None, _on_enter)






    def _on_escape(_btn):
        try:
            vte.feed_child(b"\x1b")
        except Exception:
            pass



    esc_btn = _make_corner_btn("Esc.", None, _on_escape, size=KEY_BTN_W)












    ctrl_strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ctrl_strip.set_size_request(KEY_STRIP_W, -1)
    ctrl_strip.set_halign(Gtk.Align.CENTER)
    ctrl_strip.get_style_context().add_class("side-strip")
    ctrl_strip.set_margin_top(6)
    ctrl_strip.set_margin_bottom(6)
    ctrl_strip.set_margin_end(6)


    spacer = Gtk.Box()
    ctrl_strip.pack_start(spacer, True, True, 0)



    esc_btn.set_halign(Gtk.Align.CENTER)
    ctrl_strip.pack_start(esc_btn, False, False, 0)
    enter_btn.set_size_request(KEY_BTN_W, KEY_BTN_W)
    enter_btn.set_halign(Gtk.Align.CENTER)
    ctrl_strip.pack_start(enter_btn, False, False, 0)
    body.pack_start(ctrl_strip, False, False, 0)




    def _resize_keys(_win=None, _alloc=None):
        alloc_h = ctrl_strip.get_allocated_height()
        if alloc_h <= 0:
            return


        key_h = max(40, (alloc_h - 12 - 6) // 2)
        esc_btn.set_size_request(KEY_BTN_W, key_h)
        enter_btn.set_size_request(KEY_BTN_W, key_h)
    win.connect("size-allocate", _resize_keys)


    def _refresh_browser_rows():

        tabs = _fetch_cdp_tabs()

        for row in _browser_rows:
            _browser_list.remove(row)
        _browser_rows.clear()
        has_tasks = bool(_plan_steps())
        has_page_info = any(t.get("active") for t in tabs)


        cap = 5
        for t in tabs[:cap]:
            title = (t.get("title") or "?")[:42]
            url = (t.get("url") or "?")
            if len(url) > 42:
                url = url[:39] + "…"



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












                try:
                    win.unfocus()
                except Exception:
                    pass
                try:
                    win.set_keep_above(False)
                except Exception:
                    pass
                _focus_tab(tab)



            btn.connect("clicked", _on_tab_click)
            _browser_list.pack_start(btn, False, False, 0)
            _browser_rows.append(btn)
        _browser_list.show_all()

    def _refresh_tasks_rows():

        tasks_list = _sidebar_labels.get("tasks_list")
        if tasks_list is None:
            return

        for child in tasks_list.get_children():
            tasks_list.remove(child)

        rows = []





        for idx, text, status in _plan_steps()[:8]:
            rows.append((idx, text, status))

        if not rows:







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


                if len(title) > 38:
                    title = title[:35] + "…"
                short_id = tid[:8] if tid else "—"
                ts_short = ts[11:16] if len(ts) >= 16 else ""
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

        _sidebar_labels["browser"].set_text(_browser_state())

        active_lbl = _sidebar_labels.get("browser_active")
        if active_lbl is not None:
            active_lbl.set_text(_active_task_for_browser())

        _sidebar_labels["tasks"].set_text(_plan_tasks())
        _refresh_browser_rows()
        _refresh_tasks_rows()
        return True

    GLib.timeout_add_seconds(REFRESH_SECS, _refresh_sidebar)
    GLib.idle_add(_refresh_sidebar)





    def _on_vte_button(widget, event):
        if event.button == 2:
            try:
                sel = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
                text = sel.wait_for_text()
                if text:
                    widget.feed_child(text.encode("utf-8"))
                    return True
            except Exception:
                pass
        if event.button == 3:
            try:



                menu = Gtk.Menu()

                mi_copy = Gtk.MenuItem(label="Copy")
                mi_copy.show()
                def _do_copy(_i):
                    try:
                        widget.copy_clipboard()
                    except Exception:
                        pass
                mi_copy.connect("activate", _do_copy)
                menu.append(mi_copy)

                mi_paste = Gtk.MenuItem(label="Paste")
                mi_paste.show()
                def _do_paste_cb(_i):
                    try:
                        widget.paste_clipboard()
                    except Exception:
                        pass
                mi_paste.connect("activate", _do_paste_cb)
                menu.append(mi_paste)

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


                toplevel = widget.get_toplevel()
                if toplevel is not None:
                    menu.attach_to_widget(toplevel, None)
                menu.popup(None, None, None, None, event.button, event.time)
                return True
            except Exception:


                try:
                    sel = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
                    text = sel.wait_for_text()
                    if text:
                        widget.feed_child(text.encode("utf-8"))
                        return True
                except Exception:
                    pass
        return False





    def _on_win_keypress(_widget, event):
        try:
            if event.keyval == Gdk.KEY_Escape:
                _on_escape()
                return True
        except Exception:
            pass
        return False






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

    nvm_root = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm_root):
        for entry in sorted(os.listdir(nvm_root), reverse=True):
            candidate = os.path.join(nvm_root, entry, "bin")
            if os.path.isdir(candidate):
                user_path_dirs.append(candidate)

    safe_path = ":".join(user_path_dirs + [base_path])
    env_overrides = {
        "TERM": "xterm-256color",
        "CORTEXAGENT_BOOT_ANIM": "0",
        "CORTEXAGENT_TICKER": "0",
        "PYTHONUNBUFFERED": "1",
        "CORTEXAGENT_FORCE_TUI": "1",
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






    def _on_escape():
        pid = vte_pid_holder[0]
        if pid is None:

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
        pass
    try:
        _atexit.register(_record_close)
    except Exception:
        pass




    def _record_lifecycle():
        try:
            wid = win.get_window().get_xid() if win.get_window() else 0
        except Exception:
            wid = 0
        _record_open(os.getpid(), vte_pid_holder[0], int(wid) if wid else 0)
        return False

    GLib.idle_add(_record_lifecycle)


    def _on_destroy(*_a):
        _record_close()
        try:
            Gtk.main_quit()
        except Exception:
            pass

    win.connect("destroy", _on_destroy)
    win.connect("key-press-event", _on_win_keypress)





    def _on_window_click(_w, _event):
        try:
            win.set_keep_above(True)
        except Exception:
            pass
        return False
    win.connect("button-press-event", _on_window_click)



    try:
        from lib.popup_themes import load_settings
        _apply_theme(load_settings().get("theme", "amber"))
    except Exception:
        pass
    win.show_all()




    def _dprint(*a):


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
        return False

    GLib.timeout_add(400, _enforce_once)
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
