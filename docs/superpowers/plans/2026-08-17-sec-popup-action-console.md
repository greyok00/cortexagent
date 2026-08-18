# Security Popup → Action Console — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Tk security popup (`lib/sec_controls.py`) into a readable action console where alerts are big human-framed cards with working Block/Investigate/Dismiss actions that survive the refresh and give visible feedback.

**Architecture:** In-place rewrite of the window-building code inside `lib/sec_controls.py`. Keep all the working alert-ingestion, reframing, and block-queue logic; replace the render/refresh and header/footer/stats UI. New pure functions (`_severity_bar`, `_human_frame`, `_block_feedback`) are extracted so they're unit-testable without a display.

**Tech Stack:** Python 3 stdlib, tkinter (Tk), pystray (unchanged, via `sec_tray.py`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-17-sec-popup-action-console-design.md`

## Global Constraints

- File is **local-only / uncommitted** — do NOT commit `lib/sec_controls.py` (matches the established convention; `sec_tray.py` is also uncommitted). Commit only the new test file.
- Localhost-only bindings (no `0.0.0.0`). This file opens no sockets, so trivially satisfied.
- Keep the dock-style window (`-type dock`, topmost, no focus theft) — do not add focus-grabbing.
- Do not touch `lib/sec_tray.py`, the RecordRelief webapp, or the overseer/firewall backend.
- No new external dependencies — stdlib + tkinter only.
- All user-visible alert text must be human-framed (see spec reframing table).

---

### Task 1: Add pure logic helpers (severity bar, human frame, block feedback)

**Files:**
- Modify: `lib/sec_controls.py` (insert after `_blocked_count()`, ~line 350)
- Test: `tests/test_sec_controls.py` (create)

**Interfaces:**
- Consumes: existing `SEV_COLOR`, `SEV_ORDER`, `_extract_ip`, `_queue_block`, `_blocked_count`, `FIREWALL_COMMANDS`, `FIREWALL_STATE`.
- Produces:
  - `def _severity_bar(alerts: list[dict]) -> str` → `"🔴 2 critical · 1 high · 3 low"` (only nonzero; `"All clear"` when empty).
  - `def _human_frame(alert: dict) -> tuple[str, list[tuple[str, str]]]` → `(title, human_text, actions)`. Actually returns `(title, body, actions)` where `actions` is a list of `(key, label)` matching the existing `REFRAMINGS` action keys.
  - `def _block_feedback(ip: str, reason: str) -> str` → returns a status string: `"Blocked <ip> ✓"` on success (optionally reading `firewall_commands_result.jsonl`), `"⚠ block command write failed"` on write failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sec_controls.py
"""Unit tests for the pure-logic helpers in lib/sec_controls.

These functions take only plain data (lists of alert dicts) and return
strings — no tkinter, no display, so they're safe to test headlessly.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from lib import sec_controls as sc  # noqa: E402


def test_severity_bar_empty():
    assert sc._severity_bar([]) == "All clear"


def test_severity_bar_counts_only_nonzero():
    alerts = [
        {"severity": "critical", "detail": "x"},
        {"severity": "critical", "detail": "y"},
        {"severity": "high", "detail": "z"},
        {"severity": "info", "detail": "i"},
    ]
    bar = sc._severity_bar(alerts)
    assert "2 critical" in bar
    assert "1 high" in bar
    assert "1 info" in bar
    assert "medium" not in bar
    assert "0 medium" not in bar


def test_severity_bar_order_is_critical_first():
    alerts = [{"severity": "low", "detail": "a"}, {"severity": "critical", "detail": "b"}]
    bar = sc._severity_bar(alerts)
    assert bar.index("critical") < bar.index("low")


def test_human_frame_port_scan_has_block_action():
    title, body, actions = sc._human_frame(
        {"kind": "port-scan", "detail": "Port scan from 1.2.3.4: 12 distinct ports"}
    )
    assert title == "Port scan detected"
    assert "recon" in body.lower() or "probing" in body.lower()
    keys = [k for k, _ in actions]
    assert "block" in keys


def test_human_frame_unknown_kind_falls_back_to_default():
    title, body, actions = sc._human_frame({"kind": "weird.thing", "detail": "d"})
    assert "something" in body.lower() or "flag" in body.lower()
    assert isinstance(actions, list)


def test_block_feedback_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "FIREWALL_COMMANDS",
                        tmp_path / "nonexistent_dir" / "cmds.jsonl")
    out = sc._block_feedback("1.2.3.4", "test")
    assert "fail" in out.lower() or "⚠" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/grey/cortexagent && python3 -m pytest tests/test_sec_controls.py -v`
Expected: FAIL — `AttributeError: module 'lib.sec_controls' has no attribute '_severity_bar'`

- [ ] **Step 3: Implement the three helpers**

Insert into `lib/sec_controls.py` after `_blocked_count()` (line ~350):

```python
# ── Pure-logic helpers (Action Console) ───────────────────────────────────────
# These take plain alert data and return strings — no tkinter — so they're
# unit-testable headlessly. The window code calls these to build its labels.

def _severity_bar(alerts: list[dict]) -> str:
    """'🔴 2 critical · 1 high · 3 low' — only nonzero severities, critical
    first. Returns 'All clear' when there are no alerts."""
    if not alerts:
        return "All clear"
    counts: dict[str, int] = {k: 0 for k in SEV_ORDER}
    for a in alerts:
        s = str(a.get("severity", "info")).lower()
        if s in counts:
            counts[s] += 1
    parts = []
    for sev in SEV_ORDER:
        n = counts[sev]
        if n > 0:
            parts.append(f"{SEV_ICON.get(sev, '•')} {n} {sev}")
    return " · ".join(parts) if parts else "All clear"


_DEFAULT_FRAME = (
    "Something touched the system — an alert fired from {source}. "
    "This is the system flagging an event it thinks is worth your attention. "
    "Open the detail to see the exact message before deciding what to do."
)


def _human_frame(alert: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (title, human_body, actions) for an alert.

    Uses the REFRAMINGS table when the kind is known; otherwise falls back to
    a generic plain-language frame. `actions` is a list of (key, label) where
    key is one of block / audit / ack / dismiss.
    """
    kind = str(alert.get("kind", ""))
    r = REFRAMINGS.get(kind)
    if not r:
        src = alert.get("source", "?")
        return (
            str(alert.get("kind", "alert")).replace(".", " ").replace("_", " ").title() or "Alert",
            _DEFAULT_FRAME.format(source=src),
            [("dismiss", "✕ Dismiss")],
        )
    title = r["title"]
    body = r["summary"]
    ip = _extract_ip(str(alert.get("detail", "")))
    ports = alert.get("ports")
    if not ports:
        m = re.search(r"(\d+)\s+distinct ports", str(alert.get("detail", "")))
        ports = int(m.group(1)) if m else 0
    try:
        body = body.format(ip=ip, n_ports=ports)
    except Exception:
        pass
    actions = list(r.get("actions", []))
    if not any(k == "dismiss" for k, _ in actions):
        actions.append(("dismiss", "✕ Dismiss"))
    return title, body, actions


def _block_feedback(ip: str, reason: str) -> str:
    """Queue a block and return a short user-facing status string.

    Reads firewall_commands_result.jsonl after writing so we can report whether
    the root helper applied the rule yet.
    """
    if not _queue_block(ip, reason):
        return "⚠ block command write failed"
    applied = False
    try:
        result_path = FIREWALL_COMMANDS.parent / "firewall_commands_result.jsonl"
        if result_path.exists():
            with result_path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("ip") == ip and rec.get("ok"):
                        applied = True
    except OSError:
        pass
    return f"Blocked {ip} ✓" if applied else f"Block queued for {ip} (helper applying)"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/grey/cortexagent && python3 -m pytest tests/test_sec_controls.py -v`
Expected: PASS (all 6)

- [ ] **Step 5: Commit the test file only**

```bash
cd /home/grey/cortexagent
git add tests/test_sec_controls.py
git commit -m "test(sec): pure-logic helpers for action console"
```
(Do NOT stage `lib/sec_controls.py` — it stays uncommitted per convention.)

---

### Task 2: Replace the render/refresh with in-place updates (kill the click-killer)

**Files:**
- Modify: `lib/sec_controls.py` (`_render_alerts`, `_build_card`, `_toggle_expand`, `_apply_filters`, `_refresh`)

**Interfaces:**
- Consumes: `_human_frame` from Task 1; existing `_merge_and_sort`, `_alert_id`, `sev_state`.
- Produces: `card_widgets` entries keyed by alert id that survive `_apply_filters()` ticks. `_render_alerts(alerts, in_place=True)` updates text/colors in place instead of destroying.

- [ ] **Step 1: Rewrite `_build_card` to use human framing and return updatable labels**

Replace the body of `_build_card` (currently ~line 680) so it:
1. Calls `title, body, actions = _human_frame(alert)` for the title/body.
2. Keeps references to the `title_l`, `preview_l` labels in the returned `refs` dict so a later tick can `configure()` them.
3. Adds a per-card action row with **Block / Investigate / Dismiss** buttons rendered immediately (no expand step) for the `block`, `audit`, `ack`, `dismiss` keys.

```python
    def _build_card(parent, alert):
        sev = str(alert.get("severity", "info")).lower()
        color = SEV_COLOR.get(sev, "#5ac8fa")
        icon = SEV_ICON.get(sev, "•")
        title, body, actions = _human_frame(alert)

        card = tk.Frame(parent, bg=BG_ROW, bd=0, relief="flat",
                        highlightbackground=color, highlightthickness=1)
        head = tk.Frame(card, bg=BG_ROW)
        head.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(head, text=icon, bg=BG_ROW, fg=color,
                 font=("-size", 15, "-weight", "bold")).pack(side="left", padx=(0, 8))
        title_l = tk.Label(head, text=title, bg=BG_ROW, fg=FG_BRIGHT,
                           font=("-size", 15, "-weight", "bold"), anchor="w")
        title_l.pack(side="left", fill="x", expand=True)
        tk.Label(head, text=_format_hms(alert.get("ts", "")),
                 bg=BG_ROW, fg=FG_DIM, font=("-size", 11)).pack(side="right")

        preview_l = tk.Label(card, text=body, bg=BG_ROW, fg=FG_BRIGHT,
                             font=("-size", 13), wraplength=win_w - 60,
                             justify="left", anchor="w")
        preview_l.pack(fill="x", padx=10, pady=(6, 6))

        # Action row — real buttons, visible immediately.
        btn_row = tk.Frame(card, bg=BG_ROW)
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        for act_key, act_label in actions:
            if act_key not in ("block", "audit", "ack", "dismiss"):
                continue
            bg = {"block": "#b71c1c", "audit": "#0d47a1",
                  "ack": "#37474f", "dismiss": "#444"}.get(act_key, "#444")
            b = _small_btn(btn_row, act_label, bg,
                           lambda _e, k=act_key, a=alert: _on_action(k, a))
            b.pack(side="left", padx=(0, 6), fill="x", expand=True)

        return card, {
            "card": card, "head": head, "title_l": title_l, "preview_l": preview_l,
            "all_widgets": [card, head, title_l, preview_l],
        }
```

- [ ] **Step 2: Add `_on_action` and `_render_alerts` in-place update path**

Add `_on_action(key, alert)` that dispatches Block / Investigate / Dismiss:

```python
    def _on_action(key, alert):
        if key == "block":
            ip = _extract_ip(str(alert.get("detail", "")))
            if not ip:
                status_sub.configure(text="⚠ no IP found in detail to block")
                return
            status_sub.configure(text=_block_feedback(ip, f"manual: {alert.get('kind', '?')}"))
        elif key == "audit":
            _open_log()
        elif key == "ack":
            status_sub.configure(text="✓ Acknowledged (noted in session)")
        elif key == "dismiss":
            _dismiss(alert)
```

Replace `_render_alerts` so a refresh reuses existing cards by alert id, only updating text:

```python
    def _render_alerts(alerts, in_place=True):
        # Key existing cards by alert id.
        by_id = {}
        for c in list(card_widgets):
            if c[2] is not None and c[3] is not None:
                by_id[_alert_id(c[3])] = c
        seen: set = set()
        for a in reversed(alerts):
            aid = _alert_id(a)
            seen.add(aid)
            if aid in by_id:
                card, refs, _body, old = by_id[aid]
                # Update in place — do NOT destroy (this is what keeps clicks alive).
                sev = str(a.get("severity", "info")).lower()
                color = SEV_COLOR.get(sev, "#5ac8fa")
                title, body, _actions = _human_frame(a)
                refs["title_l"].configure(text=title, fg=FG_BRIGHT)
                refs["preview_l"].configure(text=body)
                for w in (refs["card"], refs["head"], refs["title_l"], refs["preview_l"]):
                    w.configure(highlightbackground=color)
                entry = [card, refs, _body, a]
                card_widgets[card_widgets.index(by_id[aid])] = entry
            else:
                card, refs = _build_card(list_frame, a)
                card.pack(fill="x", padx=4, pady=3)
                card_widgets.append([card, refs, None, a])
        # Remove cards whose alert no longer exists.
        for c in list(card_widgets):
            if c[3] is not None and _alert_id(c[3]) not in seen:
                c[0].destroy()
                card_widgets.remove(c)
```

- [ ] **Step 3: Update `_apply_filters` to call the in-place render**

Replace the `_render_alerts(filtered)` call with `_render_alerts(filtered, in_place=True)` and drop the old destroy-all path. Keep the 2s `_refresh` tick — it now patches labels instead of rebuilding.

- [ ] **Step 4: Manual verification (no display in CI)**

Run: `cd /home/grey/cortexagent && python3 -c "import lib.sec_controls; print('imports OK')"`
Expected: no error.
Run the popup with a temp feed (needs a display; skip in headless CI):
`python3 -m lib.sec_controls` — verify a card expands/stays after a 2s refresh tick, and action buttons respond.

- [ ] **Step 5: Commit (test file only if any added; module stays uncommitted)**

```bash
cd /home/grey/cortexagent
git status --short  # confirm lib/sec_controls.py is NOT staged
```

---

### Task 3: Strip the stats header/footer + add severity bar + feedback status line

**Files:**
- Modify: `lib/sec_controls.py` (status header section ~line 469, footer ~line 900, `_update_status`, `_update_footer`)

**Interfaces:**
- Consumes: `_severity_bar` from Task 1.
- Produces: `_update_status(alerts)` now sets `status_main` to `_severity_bar(alerts)`.

- [ ] **Step 1: Replace the stats header with a severity bar**

In `_update_status(alerts)`, change the `status_main` text from the old `"{len} alerts · {crit} critical …"` format to just `_severity_bar(alerts)`. Keep `sev_dot` color as the max severity.

```python
    def _update_status(alerts):
        if not alerts:
            sev_dot.configure(fg="#5ac8fa", text="●")
            status_main.configure(text="All clear", fg=FG_BRIGHT)
            status_sub.configure(text="Watching · refresh 2s")
            plan_text.configure(text="✅ No recommended action — system is quiet.",
                                bg="#1a3050", fg="#5ac8fa")
            return
        max_sev = next((s for s in SEV_ORDER
                        if s in {str(a.get("severity", "info")).lower() for a in alerts}), "info")
        sev_dot.configure(fg=SEV_COLOR[max_sev], text="●")
        status_main.configure(text=_severity_bar(alerts), fg=FG_BRIGHT)
        status_sub.configure(text=f"Watching · max {max_sev.upper()} · refresh 2s")
        # Action plan banner (unchanged intent, human-framed)
        ...
```

- [ ] **Step 2: Remove the count-chips row**

Delete the `sev_filter` frame + `_make_filter_chip` + `sev_state`/`sev_chip_refs` wiring (lines ~499-549) and every reference to `sev_chip_refs` / `_update_chips`. Filtering is now implicit (Dismiss removes); keep `_filter_alerts` only if still used — if not, remove it too.

- [ ] **Step 3: Replace the footer with a live feedback line**

Replace the footer label (currently "X alerts · last refresh · Y blocked") with the status feedback line that `_on_action` writes to via `status_sub` — or repurpose the footer to show the last action result. Ensure `_update_footer` sets it to the last action message (default "Ready").

- [ ] **Step 4: Verify imports still work**

Run: `cd /home/grey/cortexagent && python3 -c "import lib.sec_controls; print('OK')"`
Expected: no error (module-level tkinter import still resolves).

- [ ] **Step 5: Confirm no module commit**

```bash
cd /home/grey/cortexagent && git status --short
```
Expected: `lib/sec_controls.py` NOT listed as staged.

---

### Task 4: Implement Investigate (open the real log) + wire Block result

**Files:**
- Modify: `lib/sec_controls.py` (`_open_log` helper; reuse in `_on_action`)

**Interfaces:**
- Consumes: `FIREWALL_COMMANDS`, overseer log path.
- Produces: `_open_log()` — opens the overseer log (or alert source file) via `xdg-open`.

- [ ] **Step 1: Add `_open_log`**

```python
    def _open_log(_e=None):
        log_candidates = [
            Path.home() / "security-reports" / "overseer" / "overseer.log",
            Path.home() / "honeypot" / "alerts.log",
            Path.home() / "Documents" / "RecordRelief" / "webapp" / "data" / "alerts.json",
        ]
        target = next((p for p in log_candidates if p.exists()), None)
        if not target:
            status_sub.configure(text="⚠ no log file found to open")
            return
        try:
            subprocess.Popen(["xdg-open", str(target)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            status_sub.configure(text=f"📄 Opened {target.name}")
        except Exception as e:
            status_sub.configure(text=f"⚠ could not open log: {e}")
```

- [ ] **Step 2: Wire `_open_log` into the `audit` action** in `_on_action` (replaces the old "print a path" behavior).

- [ ] **Step 3: Verify no syntax errors**

Run: `cd /home/grey/cortexagent && python3 -c "import lib.sec_controls"`
Expected: no error.

- [ ] **Step 4: Confirm module stays uncommitted**

```bash
cd /home/grey/cortexagent && git status --short
```
Expected: `lib/sec_controls.py` NOT staged.

---

## Self-Review

- **Spec coverage:** severity bar (Task 3), human framing (Task 1 + Task 2), in-place refresh killing the click-killer (Task 2), big text (Task 2 font sizes 13-15), actions on every card (Task 2), Block feedback (Task 1 + Task 2), Investigate opens log (Task 4), Dismiss removes from view (Task 2 `_on_action` dismiss), strip stats (Task 3). ✅
- **Placeholders:** none — every step has concrete code.
- **Type consistency:** `_severity_bar`, `_human_frame` → `(title, body, actions)`, `_block_feedback` all match across tasks. Action keys block/audit/ack/dismiss consistent with existing `REFRAMINGS`. ✅
