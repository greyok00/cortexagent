# tests/test_status_panels.py
import time

_tests = [
    ("abc", 3),
    ("⚡", 2),                                   # emoji = 2 columns
    ("⚡" + chr(0xFE0F), 2),                     # variation selector = 0
    ("🔢 Tokens", 9),
    ("e" + chr(0x0301) + "b", 2),               # combining mark = 0
]

def test_display_width():
    from lib.status_panels import display_width
    for s, want in _tests:
        assert display_width(s) == want, (s, display_width(s), want)

def test_fit_cell_exact_width():
    from lib.status_panels import fit_cell, display_width
    assert fit_cell("ab", 5) == "ab   "
    for s in ("⚡x", "abcdefgh", "a·b"):
        assert display_width(fit_cell(s, 6)) == 6

def test_box_rows_equal_width():
    from lib.status_panels import box, display_width
    rows = box("⚡ Compression", ["42% saved", "25.1k in -> 14.5k out"], 30)
    assert len(rows) == 4
    assert all(display_width(r) == 30 for r in rows)
    assert rows[0].startswith("┌─ ⚡ Compression")
    assert rows[0].endswith("┐") and rows[3].startswith("└") and rows[3].endswith("┘")

def test_compression_reads_newest_source(tmp_path):
    from lib.status_panels import read_compression
    old = tmp_path / "token_tracker.json"
    new = tmp_path / "minify_stats.json"
    old.write_text('{"runs": 1, "tokens_in": 10, "tokens_out": 5, "ratio_pct": 50.0}')
    new.write_text('{"total": {"runs": 4, "tokens_in": 25100, "tokens_out": 14500, "ratio_pct": 42.2}}')
    old.touch(); time.sleep(0.02); new.touch()
    d = read_compression(tmp_path)
    assert d["ok"] and d["runs"] == 4 and d["ratio_pct"] == 42.2
    assert d["tokens_in"] == 25100 and d["tokens_out"] == 14500

def test_compression_missing_sources_ok_false(tmp_path):
    from lib.status_panels import read_compression
    assert read_compression(tmp_path)["ok"] is False

def test_compression_unwraps_proxy_nesting(tmp_path):
    from lib.status_panels import read_compression
    p = tmp_path / "token_tracker.json"
    p.write_text('{"proxy": {"runs": 7, "tokens_in": 9000, "tokens_out": 3000,'
                 ' "ratio_pct": 33.3}}')
    d = read_compression(tmp_path)
    assert d["ok"] and d["runs"] == 7 and d["ratio_pct"] == 33.3
    assert d["tokens_in"] == 9000 and d["tokens_out"] == 3000

def test_compression_live_flag_follows_mtime(tmp_path):
    from lib.status_panels import read_compression
    fresh = tmp_path / "token_tracker.json"
    fresh.write_text('{"runs": 1}')
    old = tmp_path / "minify_stats.json"
    old.write_text('{"runs": 1}')
    os.utime(old, (time.time() - 9000, time.time() - 9000))
    assert read_compression(tmp_path)["live"] is True
    os.utime(fresh, (time.time() - 9000, time.time() - 9000))
    assert read_compression(tmp_path)["live"] is False


# ---- read_tokens -----------------------------------------------------------
import tempfile
import http.server
from pathlib import Path

_CTX_REPLY = b'{"context_window": {"used": 12300, "total": 262144}}\n'
_METRICS_PATH = None        # module-level Path, set by each test

class _MetricHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = _METRICS_PATH.read_bytes()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

class _FakeControl:
    """One-shot UNIX socket server that answers with a fixed reply."""
    def __init__(self, reply: bytes):
        import socket, threading
        self.path = str(Path(tempfile.mkdtemp()) / "control.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        srv.listen(1)
        def serve():
            conn, _ = srv.accept()
            conn.recv(1024)
            conn.sendall(reply)               # reply already ends with \n
            conn.close()
            srv.close()
        threading.Thread(target=serve, daemon=True).start()

def test_tokens_reads_lane_and_control_socket():
    import threading
    import http.server
    from lib.status_panels import read_tokens
    global _METRICS_PATH
    _METRICS_PATH = Path(tempfile.mkdtemp()) / "metrics.json"
    _METRICS_PATH.write_text('{"completion_tokens": 12400, '
                             '"current_in_tps": 40.0, "current_out_tps": 88.0, '
                             '"requests": 3}')
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MetricHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ctl = _FakeControl(_CTX_REPLY)
    try:
        d = read_tokens(control_sock=ctl.path,
                        metrics_port=srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()
    assert d["ok"] and d["out_tokens"] == 12400
    assert d["in_tps"] == 40.0 and d["out_tps"] == 88.0 and d["requests"] == 3
    assert d["ctx_used"] == 12300 and d["ctx_total"] == 262144

def test_tokens_lane_down_ok_false():
    from lib.status_panels import read_tokens
    d = read_tokens(control_sock=Path("/nonexistent.sock"),
                    metrics_port=1)   # port 1: nothing listens
    assert d["ok"] is False and d["ctx_used"] == 0

def test_tokens_malformed_port_env_degrades(monkeypatch):
    # A bad CORTEXAGENT_LANE_METRICS_PORT must not raise out of the reader.
    from lib.status_panels import read_tokens
    monkeypatch.setenv("CORTEXAGENT_LANE_METRICS_PORT", "not-a-port")
    d = read_tokens(control_sock=Path("/nonexistent.sock"))
    assert d["ok"] is False and d["ctx_used"] == 0


# ---- read_memory -----------------------------------------------------------
import os

def test_memory_counts_and_topic(tmp_path):
    from lib.status_panels import read_memory
    hot = tmp_path / "hot"; hot.mkdir()
    (hot / "cortexagent.jsonl").write_text(
        '{"role": "user", "content": "first"}\n'
        '{"role": "user", "content": "the lanes topic about greysearch"}\n')
    cold = tmp_path / "cold"; cold.mkdir()
    old = cold / "old.md"; old.write_text("x")
    os.utime(old, (time.time() - 9000, time.time() - 9000))
    (hot / "fresh.jsonl").write_text("{}\n")       # fresh: counts as recent
    d = read_memory(tmp_path)
    assert d["ok"] and d["hot_lines"] == 3
    assert d["recent"] == 2                 # the 9000s-old cold file is not recent
    # topic = first 8 words of the LAST line's content, joined with spaces
    assert d["topic"].startswith("the lanes topic")

def test_memory_recent_ignores_directories(tmp_path):
    from lib.status_panels import read_memory
    hot = tmp_path / "hot"; hot.mkdir()
    (hot / "a.jsonl").write_text('{"content": "topic line here"}\n')
    fresh_dir = hot / "subdir"; fresh_dir.mkdir()   # new mtime, but a directory
    d = read_memory(tmp_path)
    assert d["ok"] and d["recent"] == 1     # only the jsonl file counts

def test_memory_recent_excludes_old_files(tmp_path):
    from lib.status_panels import read_memory
    hot = tmp_path / "hot"; hot.mkdir()
    fresh = hot / "a.jsonl"; fresh.write_text("{}\n")
    oldm = hot / "b.jsonl"; oldm.write_text("{}\n")
    os.utime(oldm, (time.time() - 9000, time.time() - 9000))
    d = read_memory(tmp_path)
    assert d["recent"] == 1                 # dir itself does not count; only fresh file

def test_memory_missing_dir(tmp_path):
    from lib.status_panels import read_memory
    assert read_memory(tmp_path / "nope")["ok"] is False

def test_memory_whitespace_topic_falls_back_to_older_file(tmp_path):
    from lib.status_panels import read_memory
    hot = tmp_path / "hot"; hot.mkdir()
    older = hot / "older.jsonl"
    older.write_text('{"content": "real topic from the older file"}\n')
    newer = hot / "newer.jsonl"
    newer.write_text('{"content": "   \\n\\t "}\n')
    time.sleep(0.02); newer.touch()               # newer mtime, blank content
    assert read_memory(tmp_path)["topic"] == "real topic from the older file"


# ---- read_scheduler --------------------------------------------------------
import json as _json

def _iso_in_minutes(delta_min: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc)
            + timedelta(minutes=delta_min)).isoformat()

def _iso_in_seconds(delta_s: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc)
            + timedelta(seconds=delta_s)).isoformat()

def test_scheduler_active_tasks(tmp_path):
    from lib.status_panels import read_scheduler
    sched = tmp_path / "scheduler"; sched.mkdir()
    sched.joinpath("tasks.json").write_text(_json.dumps({
        "aaa": {"title": "dip-screen-sweep", "state": "cancelled", "enabled": True},
        "bbb": {"title": "swing-cycle", "state": "scheduled", "enabled": True,
                "next_run_at": _iso_in_minutes(-22), "execution_count": 4},
        "ccc": {"title": "old-schema", "state": "scheduled"},   # no next, no execs
    }))
    got = read_scheduler(tmp_path)
    assert got[0]["title"] in ("swing-cycle", "old-schema")
    assert sorted(t["done"] for t in got) == [0, 4]       # execution_count -> done, real mapping
    assert len(got) == 2                                  # cancelled excluded
    assert all(t["next"].startswith(("next", "scheduled")) for t in got)

def test_scheduler_disabled_and_none_last(tmp_path):
    from lib.status_panels import read_scheduler
    sched = tmp_path / "scheduler"; sched.mkdir()
    sched.joinpath("tasks.json").write_text(_json.dumps({
        "t1": {"title": "future-task", "state": "scheduled",
               "next_run_at": _iso_in_minutes(22)},
        "t2": {"title": "disabled-task", "state": "scheduled",
               "next_run_at": _iso_in_seconds(90)},      # enabled absent = on
        "t3": {"title": "off-task", "state": "scheduled", "enabled": False,
               "next_run_at": _iso_in_seconds(90)},
        "t4": {"title": "running-nons", "state": "running"},  # None -> last
    }))
    got = read_scheduler(tmp_path)
    assert [t["title"] for t in got[:2]] == ["disabled-task", "future-task"]
    assert got[-1]["title"] == "running-nons" and got[-1]["next"] == "scheduled"
    assert got[0]["next"] == "next 1m"

def test_scheduler_max_tasks_cap(tmp_path):
    from lib.status_panels import read_scheduler
    sched = tmp_path / "scheduler"; sched.mkdir()
    sched.joinpath("tasks.json").write_text(_json.dumps({
        str(i): {"title": f"task-{i}", "state": "scheduled",
                 "next_run_at": _iso_in_minutes(i + 1)}
        for i in range(5)
    }))
    got = read_scheduler(tmp_path, max_tasks=2)
    assert [t["title"] for t in got] == ["task-0", "task-1"]

def test_scheduler_missing_and_malformed(tmp_path):
    from lib.status_panels import read_scheduler
    assert read_scheduler(tmp_path) == []                 # no file
    sched = tmp_path / "scheduler"; sched.mkdir()
    sched.joinpath("tasks.json").write_text("not json at all")
    assert read_scheduler(tmp_path) == []                 # malformed file


# ---- renderer: the alignment gate ------------------------------------------
_OK_COMP = {"ok": True, "ratio_pct": 42.0, "runs": 4, "tokens_in": 25100,
            "tokens_out": 14500, "live": True}
_OK_TOK = {"ok": True, "out_tokens": 12400, "in_tps": 40, "out_tps": 88,
           "requests": 3, "ctx_used": 12300, "ctx_total": 262144}
_OK_MEM = {"ok": True, "hot_lines": 2, "recent": 2, "topic": "lanes topic"}
_OK_SCHED = [{"title": "dip-screen-sweep", "next": "next 22m", "done": 4},
             {"title": "t2", "next": "scheduled", "done": 0}]
_DATA = {"compression": _OK_COMP, "tokens": _OK_TOK, "memory": _OK_MEM,
         "scheduler": _OK_SCHED}

def test_row1_boxes_line_up():
    from lib.status_panels import render_panels, display_width
    rows = render_panels(_DATA, width=60)
    assert rows is not None
    # row1 pair: top + 2 body + bottom = 4; memory box = 3 (1 body line);
    # scheduler box = 2 + n tasks (2 here)
    assert len(rows) == 4 + 3 + (2 + len(_OK_SCHED))    # 11
    for r in rows:
        assert display_width(r) == 60, repr(r)
    first, second = rows[0], rows[1]
    assert first.count("┌") == 2 and first.count("┐") == 2
    # box 2's left border sits exactly one column right of box 1's right border
    i = first.index("┐")
    assert first[i + 1] == " " and first[i + 2] == "┌"
    # the same columns hold │ on the body row: the borders line up
    assert second[i] == "│" and second[i + 2] == "│"

def test_row1_boxes_line_up_odd_width():
    from lib.status_panels import render_panels, display_width
    rows = render_panels(_DATA, width=61)
    assert rows is not None
    assert len(rows) == 4 + 3 + (2 + len(_OK_SCHED))    # 11
    for r in rows:
        assert display_width(r) == 61, repr(r)
    first, second = rows[0], rows[1]
    assert first.count("┌") == 2 and first.count("┐") == 2
    i = first.index("┐")
    assert first[i + 1] == " " and first[i + 2] == "┌"
    assert second[i] == "│" and second[i + 2] == "│"

def test_memory_scheduler_rows_full_width():
    from lib.status_panels import render_panels, display_width
    rows = render_panels(_DATA, width=80)
    assert all(display_width(r) == 80 for r in rows[4:])
    assert rows[4].startswith("┌─ 🧠 Memory")           # memory top border
    assert rows[6].startswith("└")                      # memory bottom border
    assert rows[7].startswith("┌─ 📅 Scheduler")        # scheduler top border
    assert rows[-1].endswith("┘")

def test_narrow_falls_back_and_degraded():
    from lib.status_panels import render_panels
    assert render_panels(_DATA, width=40) is None
    empty = {"compression": {"ok": False}, "tokens": {"ok": False},
             "memory": {"ok": False}, "scheduler": []}
    rows = render_panels(empty, width=60)
    assert any("— nothing yet" in r for r in rows[:4])
    assert any("lane down" in r for r in rows[:4])
    assert any("— no active tasks" in r for r in rows[6:])

def test_format_helpers():
    from lib.status_panels import _fmt_k, _human_tokens, _fmt_tps
    assert _human_tokens(25100) == "25.1k" and _human_tokens(999) == "999"
    assert _human_tokens(2300000) == "2.3M"
    assert _fmt_k(12400) == "12.4k" and _fmt_k(0) == "0"
    assert _fmt_tps({"in_tps": 40, "out_tps": 88}) == "in 40 t/s · out 88 t/s"
    assert _fmt_tps({"out_tps": 88}) == "88 t/s"
    assert _fmt_tps({}) == "0 t/s"


def test_smoke_all_lines_equal_width(capsys, monkeypatch):
    from lib.status_panels import main, display_width
    import lib.status_panels as sp
    # force known data so the smoke render is deterministic
    monkeypatch.setattr(sp, "render_panels",
                        lambda data, width=None: sp._render_for_test(width=60))
    rc = main(["--smoke"])
    out = capsys.readouterr().out
    assert rc == 0
    widths = {display_width(ln) for ln in out.strip().splitlines()}
    assert len(widths) == 1

def test_once_non_tty_single_line(capsys, monkeypatch):
    from lib.status_panels import main
    import lib.status_panels as sp
    monkeypatch.setattr(sp, "render_panels",
                        lambda data, width=None: None)    # forced fallback
    assert main(["--once"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_compression_string_values_fail_soft(tmp_path):
    from lib.status_panels import read_compression
    (tmp_path / "token_tracker.json").write_text(
        '{"ratio_pct": "x", "runs": "y", "tokens_in": "z"}')
    d = read_compression(tmp_path)
    assert d["ok"] is True
    assert d["ratio_pct"] == 0.0 and d["runs"] == 0 and d["tokens_in"] == 0

def test_smoke_empty_render_fails(capsys, monkeypatch):
    from lib.status_panels import main
    import lib.status_panels as sp
    monkeypatch.setattr(sp, "render_panels", lambda data, width=None: None)
    assert main(["--smoke"]) == 1
    capsys.readouterr()

def test_main_poison_data_never_raises(capsys, monkeypatch):
    from lib.status_panels import main
    import lib.status_panels as sp
    monkeypatch.setattr(sp, "read_compression",
                        lambda state_root=None: {"ok": True, "ratio_pct": "x"})
    monkeypatch.setattr(sp, "render_panels", lambda data, width=None: None)
    assert main(["--once"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1

def test_smoke_crash_exits_1(capsys, monkeypatch):
    from lib.status_panels import main
    import lib.status_panels as sp
    def boom(data, width=None):
        raise RuntimeError("render exploded")
    monkeypatch.setattr(sp, "render_panels", boom)
    assert main(["--smoke"]) == 1        # smoke is enforcement: no exit-0 laundering

def test_live_interval_accepts_equals_form():
    from lib.status_panels import _live_interval
    assert _live_interval(["--live", "2"]) == 2.0
    assert _live_interval(["--live=0.5"]) == 0.5
    assert _live_interval(["--live"]) == 1.0
    assert _live_interval(["--live=junk"]) == 1.0
    assert _live_interval(["--once"]) == 1.0

def test_num_decimal_string_coerces():
    from lib.status_panels import _num
    assert _num("42.7", 0) == 42            # decimal string truncates, not zeroed
    assert _num("42.7", 0.0) == 42.7        # float default keeps the fraction
    assert _num("junk", 0) == 0
    assert _num(None, 0) == 0
    assert _num([1, 2], 5) == 5             # non-castable type falls to default
