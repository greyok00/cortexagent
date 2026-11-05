# lib/status_panels.py
"""Panel bar: boxed status panels (Compression | Tokens, Memory, Scheduler).

Rendered under the banner at session start, redrawable in place with --live.
Every row is width-measured so the borders always line up.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import socket
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_HIDDEN = {0x200D, 0xFE0F}          # ZWJ, emoji variation selector

def display_width(s: str) -> int:
    w = 0
    for ch in s:
        o = ord(ch)
        if o in _HIDDEN or unicodedata.combining(ch):
            continue
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w

def fit_cell(s: str, w: int) -> str:
    """Truncate and pad to exactly w display columns (borders never shift)."""
    out = ""
    for ch in s:
        candidate = out + ch
        if display_width(candidate) > w:
            break
        out = candidate
    return out + " " * (w - display_width(out))

def box(title: str, lines: Iterable[str], w: int) -> list[str]:
    """Render one box: title row, body rows, border rows, all width w."""
    head = "─ " + title + " "
    rows = ["┌" + head + "─" * max(0, w - 2 - display_width(head)) + "┐"]
    rows += ["│ " + fit_cell(ln, w - 4) + " │" for ln in lines]
    rows.append("└" + "─" * (w - 2) + "┘")
    return rows

_COMPRESSION_LIVE_S = 600

def _state_root(state_root: Path | None) -> Path:
    if state_root is not None:
        return Path(state_root)
    env = os.environ.get("CORTEXAGENT_STATE_DIR")
    return Path(env) if env else Path.home() / ".cortexagent"

def _read_stats(path: Path) -> dict:
    try:
        s = json.loads(path.read_text()) or {}
    except Exception:
        return {}
    if not isinstance(s, dict):
        return {}
    for key in ("total", "proxy"):          # same unwrap as event_feed
        if isinstance(s.get(key), dict):
            s = s[key]
            break
    return s

def _num(v, default=0):
    """Fail-soft numeric cast for reader inputs; default on coercion failure.

    Decimal strings ("42.7") still coerce via float and truncate to the
    default's type, so a ratio quoted as a string survives instead of
    zeroing out a whole panel."""
    try:
        return type(default)(v)
    except (TypeError, ValueError):
        try:
            return type(default)(float(v))
        except (TypeError, ValueError):
            return default

def read_compression(state_root: Path | None = None) -> dict:
    root = _state_root(state_root)
    # The slimtoken fallback lives under $HOME regardless of root; only the
    # default root uses the full event_feed chain, so an explicitly passed
    # root (as the isolated tests use) never falls through to the live file.
    sources = (
        root / "token_tracker.json",
        root / "minify_stats.json",
        *((Path.home() / ".local" / "state" / "slimtoken" / "stats.json",)
          if state_root is None else ()),
    )
    best_path, best_mtime = None, -1.0
    for p in sources:
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > best_mtime:
            best_path, best_mtime = p, m
    if best_path is None:
        return {"ok": False, "ratio_pct": 0.0, "runs": 0,
                "tokens_in": 0, "tokens_out": 0, "live": False}
    s = _read_stats(best_path)
    return {
        "ok": True,
        "ratio_pct": _num(s.get("ratio_pct"), 0.0),
        "runs": _num(s.get("runs"), 0),
        "tokens_in": _num(s.get("tokens_in"), 0),
        "tokens_out": _num(s.get("tokens_out"), 0),
        "live": (time.time() - best_mtime) < _COMPRESSION_LIVE_S,
    }

def read_tokens(control_sock: Path | None = None,
                metrics_port: int | None = None) -> dict:
    # Lane metrics: HTTP /metrics endpoint (fallback chain identical to
    # lib/statusline.py). Context: UNIX control socket asking {"cmd":"status"}
    # with the same context_window fallback chain as status_ticker._ctx_str.
    # Each source is fully exception-guarded: on any failure it contributes
    # its field defaults instead of raising.
    port: int | None = metrics_port
    if port is None:
        # A malformed CORTEXAGENT_LANE_METRICS_PORT degrades to lane-down
        # instead of raising out of the reader.
        try:
            port = int(os.environ.get("CORTEXAGENT_LANE_METRICS_PORT", "11436"))
        except (TypeError, ValueError):
            port = None
    sock_path = (Path(control_sock) if control_sock is not None
                 else Path.home() / ".cortexagent" / "control.sock")

    metrics: dict = {}
    if port is not None:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/metrics",
                                         method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
            if isinstance(data, dict):
                metrics = data
        except Exception:
            pass

    ctl: dict = {}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(str(sock_path))
        s.sendall(b'{"cmd":"status"}\n')
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        s.close()
        data = json.loads(buf.split(b"\n", 1)[0])
        if isinstance(data, dict):
            ctl = data
    except Exception:
        pass

    cw = ctl.get("context_window") or {}
    if not isinstance(cw, dict):
        cw = {}
    used = cw.get("used") or cw.get("used_tokens") or cw.get("current") or 0
    total = cw.get("total") or cw.get("limit") or cw.get("max") or 0

    return {
        "ok": bool(metrics),
        "out_tokens": metrics.get("completion_tokens", 0) or 0,
        "in_tps": metrics.get("current_in_tps", 0) or 0,
        "out_tps": metrics.get("current_out_tps")
                   or metrics.get("current_tok_s", 0) or 0,
        "requests": metrics.get("requests", 0) or 0,
        "ctx_used": used,
        "ctx_total": total,
    }

_MEMORY_RECENT_S = 600

def _memory_root(memory_dir: Path | None) -> Path:
    # Mirrors _state_root: an explicit dir is used verbatim so the isolated
    # tests never fall through to the live ~/.cortexagent/memory tree.
    if memory_dir is not None:
        return Path(memory_dir)
    env = os.environ.get("CORTEXAGENT_MEMORY_DIR")
    return Path(env) if env else Path.home() / ".cortexagent" / "memory"

def read_memory(memory_dir: Path | None = None) -> dict:
    root = _memory_root(memory_dir)
    try:
        if not root.is_dir():
            raise OSError(root)
    except OSError:
        return {"ok": False, "hot_lines": 0, "recent": 0, "topic": ""}

    hot_lines = 0
    paths: list[tuple[Path, float]] = []
    for p in root.glob("hot/*.jsonl"):
        try:
            hot_lines += len(p.read_text().splitlines())
            m = p.stat().st_mtime
        except OSError:
            continue
        paths.append((p, m))

    recent = 0
    now = time.time()
    for sub in ("hot", "warm", "cold"):
        d = root / sub
        if not d.is_dir():
            continue
        try:
            for f in d.iterdir():
                try:
                    if f.is_file() and f.stat().st_mtime > now - _MEMORY_RECENT_S:
                        recent += 1
                except OSError:
                    continue
        except OSError:
            continue

    topic = ""
    # Newest-first; a trailing "{}"-style line (no content field) falls
    # through to the next-newest file so topic survives fresh log files.
    for p, m in sorted(paths, key=lambda pm: pm[1], reverse=True):
        try:
            last = p.read_text().splitlines()[-1]
            content = json.loads(last).get("content", "")
        except (OSError, IndexError, ValueError, AttributeError):
            continue
        if isinstance(content, str) and content.strip():
            topic = " ".join(content.split()[:8])
            break

    return {"ok": True, "hot_lines": hot_lines, "recent": recent,
            "topic": topic}


def _parse_next(run_at: Any) -> datetime | None:
    # tz-naive stamps are treated as UTC so tz-aware and naive entries sort
    # against each other without raising.
    try:
        dt = datetime.fromisoformat(str(run_at))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _humanize_delta(run_at: Any) -> str:
    dt = _parse_next(run_at)
    if dt is None:
        return "scheduled"
    seconds = (dt - datetime.now(timezone.utc)).total_seconds()
    if seconds < 0:
        return "scheduled"
    minutes = int(seconds // 60)
    if minutes < 24 * 60:
        return f"next {minutes}m"
    return f"next {minutes // (24 * 60)}d"

def read_scheduler(state_dir: Path | None = None,
                   max_tasks: int = 3) -> list[dict]:
    # Read <state_dir>/scheduler/tasks.json directly (a FLAT dict
    # {task_id: task}). Never import lib.scheduler here: it instantiates
    # directories at import time.
    path = _state_root(state_dir) / "scheduler" / "tasks.json"
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    entries: list[tuple[datetime, dict]] = []
    for tid, task in raw.items():
        if not isinstance(task, dict):
            continue
        if task.get("state") not in ("scheduled", "running"):
            continue
        if not task.get("enabled", True):
            continue
        stamp = _parse_next(task.get("next_run_at"))
        entries.append((
            stamp or datetime.max.replace(tzinfo=timezone.utc),   # None last
            {"title": str(task.get("title") or tid),
             "next": _humanize_delta(task.get("next_run_at")),
             "done": _num(task.get("execution_count"), 0)},
        ))
    entries.sort(key=lambda e: e[0])
    return [entry for _, entry in entries[:max(0, max_tasks)]]


# ---- formatters + renderer --------------------------------------------------

def _fmt_k(n) -> str:
    """Compact count: 25100 -> '25.1k', 2300000 -> '2.3M', 999 -> '999'."""
    n = int(_num(n, 0))
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)

def _human_tokens(n) -> str:
    """Token humanizer for the panel bar ("25.1k" style; >=1e6 -> "2.3M")."""
    return _fmt_k(n)

def _fmt_tps(d: dict) -> str:
    """Rate string: 'in 40 t/s · out 88 t/s', or the single '88 t/s'."""
    it = _to_int(d.get("in_tps"))
    ot = _to_int(d.get("out_tps"))
    if it and ot:
        return f"in {it} t/s · out {ot} t/s"
    if ot:
        return f"{ot} t/s"
    if it:
        return f"in {it} t/s"
    return "0 t/s"

def _to_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0

def format_compression(d: dict) -> list[str]:
    """Two body lines for the Compression half box."""
    if not d.get("ok"):
        return ["— nothing yet", ""]
    live = " · live" if d.get("live") else ""
    return [
        f"{float(d.get('ratio_pct') or 0.0):.0f}% saved"
        f" · {_to_int(d.get('runs'))} runs{live}",
        f"{_fmt_k(d.get('tokens_in'))} in -> {_fmt_k(d.get('tokens_out'))} out",
    ]

def format_tokens(d: dict) -> list[str]:
    """Two body lines for the Tokens half box."""
    if not d.get("ok"):
        return ["lane down", ""]
    return [
        f"{_fmt_k(d.get('out_tokens'))} out · {_fmt_tps(d)}",
        f"ctx {_fmt_k(d.get('ctx_used'))}/{_fmt_k(d.get('ctx_total'))}"
        f" · {_to_int(d.get('requests'))} req",
    ]

def format_memory(d: dict) -> list[str]:
    """One body line for the Memory box."""
    hot = _to_int(d.get("hot_lines"))
    recent = _to_int(d.get("recent"))
    if not d.get("ok") or (hot == 0 and recent == 0):
        return ["— nothing yet"]
    line = f"{hot} hot lines · {recent} recent"
    topic = str(d.get("topic") or "").strip()
    if topic:
        line += f" · {topic}"
    return [line]

def format_scheduler_cells(tasks: list[dict]) -> list[str]:
    """One cell per task line for the Scheduler box."""
    if not tasks:
        return ["— no active tasks"]
    return [
        f"> {t.get('title', '')}   {t.get('next', '')}"
        f"   {_to_int(t.get('done'))} done"
        for t in tasks
    ]

def render_panels(data: dict, width: int | None = None) -> list[str] | None:
    """Render the panel bar: Compression | Tokens on row 1, then Memory,
    then Scheduler. Returns None below the minimum usable width so the
    caller can fall back to the single status line."""
    if width is None:
        width = shutil.get_terminal_size().columns
    if width < 57:
        return None
    half = (width - 1) // 2
    # The join leaves one column of slack on even widths; the second box
    # absorbs it so every row still measures exactly `width`.
    half2 = width - half - 1
    data = data or {}
    # Row-1 emoji carry the emoji-presentation selector (VS16, spelled
    # chr(0xFE0F) so no invisible character sits in the source): the width
    # engine measures the selector as zero width, and the extra codepoint
    # cancels the wide emoji's string/display deficit, keeping border and
    # body string indices the same so the half boxes line up exactly.
    vs16 = chr(0xFE0F)
    left = box("⚡" + vs16 + " Compression",
               format_compression(data.get("compression") or {}), half)
    right = box("🔢" + vs16 + " Tokens",
                format_tokens(data.get("tokens") or {}), half2)
    rows = [l + " " + r for l, r in zip(left, right, strict=True)]
    rows += box("🧠 Memory", format_memory(data.get("memory") or {}), width)
    tasks = data.get("scheduler") or []
    rows += box("📅 Scheduler", format_scheduler_cells(list(tasks)), width)
    return rows


# ---- CLI ---------------------------------------------------------------------

_render = render_panels   # direct binding: _render_for_test stays immune to a
                          # monkeypatched module-level render_panels

_TEST_COMP = {"ok": True, "ratio_pct": 42.0, "runs": 4, "tokens_in": 25100,
              "tokens_out": 14500, "live": True}
_TEST_TOK = {"ok": True, "out_tokens": 12400, "in_tps": 40, "out_tps": 88,
             "requests": 3, "ctx_used": 12300, "ctx_total": 262144}
_TEST_MEM = {"ok": True, "hot_lines": 2, "recent": 2, "topic": "lanes topic"}
_TEST_SCHED = [{"title": "dip-screen-sweep", "next": "next 22m", "done": 4},
               {"title": "t2", "next": "scheduled", "done": 0}]
_TEST_DATA = {"compression": _TEST_COMP, "tokens": _TEST_TOK,
              "memory": _TEST_MEM, "scheduler": _TEST_SCHED}

def _render_for_test(width: int | None = None) -> list[str] | None:
    """Deterministic _DATA-shaped render at a fixed width; no live state I/O."""
    return _render(_TEST_DATA, width=width)

def _gather() -> dict:
    """One live snapshot from all four readers (each self-guarding)."""
    return {
        "compression": read_compression(),
        "tokens": read_tokens(),
        "memory": read_memory(),
        "scheduler": read_scheduler(),
    }

def _summary_line(data: dict) -> str:
    """Fallback single line (lib.statusline style): same data, no boxes."""
    segs = (list(format_compression(data.get("compression") or {}))
            + list(format_tokens(data.get("tokens") or {}))
            + list(format_memory(data.get("memory") or {}))
            + list(format_scheduler_cells(list(data.get("scheduler") or []))))
    return " · ".join(s.strip() for s in segs if s and s.strip())

def _live_interval(argv: list[str]) -> float:
    # Accepts both "--live 2" and "--live=2"; a bad or missing value -> 1.0.
    for i, a in enumerate(argv):
        if a.startswith("--live="):
            try:
                return max(0.05, float(a.split("=", 1)[1]))
            except (TypeError, ValueError):
                return 1.0
        if a == "--live":
            rest = argv[i + 1:]
            if rest:
                try:
                    return max(0.05, float(rest[0]))
                except (TypeError, ValueError):
                    pass
            return 1.0
    return 1.0

def _run_once() -> int:
    data = _gather()
    rows = render_panels(data)                       # module-level indirection
    if rows is None or not sys.stdout.isatty():
        sys.stdout.write(_summary_line(data) + "\n")
        return 0
    sys.stdout.write("\n".join(rows) + "\n")
    return 0

def _run_smoke() -> int:
    data = _gather()
    rows = render_panels(data) or []
    if not rows:
        # An unassertable render is a failure, not a vacuous pass.
        sys.stderr.write("panel smoke: empty render\n")
        return 1
    total = display_width(rows[0])
    bad = sorted({display_width(r) for r in rows} - {total})
    if bad:
        sys.stderr.write("panel rows off-width: "
                         + " ".join(str(b) for b in bad) + "\n")
        return 1
    sys.stdout.write("\n".join(rows) + "\n")
    return 0

def _run_live(interval: float) -> int:
    if not sys.stdout.isatty():
        sys.stdout.write(_summary_line(_gather()) + "\n")
        return 0
    prev = 0
    while True:
        try:
            data = _gather()
            rows = render_panels(data) or []
            if not rows:
                # Below the 57-column floor: fall back to the summary line
                # instead of emitting bare newlines forever.
                rows = [_summary_line(data)]
            paint = f"\x1b[{prev}A" if prev else ""
            paint += "".join("\x1b[2K" + r + "\n" for r in rows)
            sys.stdout.write(paint)
            sys.stdout.flush()
            prev = len(rows)
        except (KeyboardInterrupt, BrokenPipeError):
            raise
        except Exception:
            return 0                 # a broken tick breaks the loop cleanly
        time.sleep(interval)

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if "--smoke" in argv:
            try:
                return _run_smoke()
            except Exception:
                # Smoke is an enforcement, so an unexpected failure inside
                # the smoke path must not launder itself into exit 0.
                sys.stderr.write("panel smoke: unrecoverable error\n")
                return 1
        if "--live" in argv or any(a.startswith("--live=") for a in argv):
            return _run_live(_live_interval(argv))
        return _run_once()
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
    except Exception:
        # Never raise out of the CLI (bin/cortexagent runs set -euo pipefail):
        # degrade to the same single summary line as the non-TTY/narrow path.
        try:
            sys.stdout.write(_summary_line({}) + "\n")
        except Exception:
            pass
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
