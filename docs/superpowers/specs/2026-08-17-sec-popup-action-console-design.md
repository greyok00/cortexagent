# Security Popup → Action Console — Design

**Date:** 2026-08-17
**Status:** Approved (approach 🅰️ fix-in-place)
**Scope:** `lib/sec_controls.py` (the Tk popup opened by `lib/sec_tray.py`)

## Problem

The security popup (`lib/sec_controls.py`) is read-only and fights the user:

- **Clicks do nothing / "little flash".** The 2-second auto-refresh
  (`_refresh` → `_render_alerts`) destroys every card and rebuilds them. A click
  that expands a card is undone ~2s later when the list is recreated, so the
  expansion never sticks.
- **Not actionable.** The Audit button only swaps a tiny status label to a file
  path. The Block button writes to `firewall_commands.jsonl` but gives no
  confirmation that the block was applied.
- **Stats the user doesn't want.** A large 18px count header, a
  "X alerts · Y blocked" footer, and five count-chips read as a metrics board,
  not an alert console.
- **Text is tiny.** Body fonts are `-size 10/11/12`.
- **Wrong escape hatch.** The Dashboard button opens the RecordRelief webapp;
  the user explicitly does not want the dashboard — they want everything in the
  popup.

## Goal

Turn the popup into a real **action console**: each alert is a big, readable
card with working actions (Block / Investigate / Dismiss) that act right there,
survive the refresh, and give visible feedback. No stats board, no browser.

## Design

### Layout (top → bottom, single scrollable column)

```
┌─ 🛡 Security Tracker ────────────────────────────✕ ┐
│  🔴 2 critical · 1 high · 3 low · no medium        │ ← one severity bar
├────────────────────────────────────────────────────┤
│  [card] 🔴 PORT SCAN DETECTED           12:43:36   │
│     IP 192.168.99.42 probed 12 ports — recon       │
│     [🛡 Block] [📄 Investigate] [✕ Dismiss]        │
│  ──────────────────────────────────────────────────│
│  [card] 🟠 ROOTKIT WARNING             13:32:07    │
│     rkhunter: /usr/bin/x modified                  │
│     [📄 Investigate] [✕ Dismiss]                   │
├────────────────────────────────────────────────────┤
│  status line: "Blocked 192.168.99.42 ✓"            │ ← live feedback
└────────────────────────────────────────────────────┘
```

### Changes to `lib/sec_controls.py`

1. **In-place refresh (kills the click-killer).**
   Replace `_render_alerts()` destroy-and-rebuild with per-card `configure()`
   updates. Cards keep their identity across the 2s tick so clicks and
   expansions survive. Track live card widgets keyed by alert id; on each tick,
   update text/colors/counts in place rather than deleting the frame.

2. **Bigger text.** Raise the base font to `-size 14/15`. Card titles 15 bold,
   body 13, action buttons 12 bold. No `-size 10`.

3. **Strip the stats.** Remove the 18px count header, the count-chips row, and
   the "X alerts · Y blocked" footer. Replace the top with a single severity
   bar: `🔴 2 critical · 1 high · 3 low` (only nonzero severities listed;
   "All clear" when none).

4. **Actions on every card.** Show **Block / Investigate / Dismiss** buttons
   directly on each card — no hidden expand step. Block only appears when the
   alert carries an IP.

5. **Block gives real feedback.** Write the block command to
   `firewall_commands.jsonl` (the existing root helper applies it), then read
   `firewall_commands_result.jsonl` to show "✓ applied" or "⚠ queued" in the
   status line.

6. **Investigate opens the actual log.** Launch the real `overseer.log` (or the
   honeypot/RecordRelief alert file) in the user's editor via `xdg-open`,
   instead of printing a file path into a status label.

7. **Dismiss removes from view.** Drop the alert from the live in-memory list so
   acted-on alerts disappear (per-session only; does not edit the source logs).

### What is kept (unchanged)

- `_read_honeypot_log` / `_read_recordrelief_feed` / `_merge_and_sort`
- `REFRAMINGS` table + `_get_reframe`
- `_extract_ip` / `_queue_block` / `_blocked_count`
- Dock-style window (`-type dock`, topmost, no focus theft)
- `lib/sec_tray.py` (the tray icon + menu) — it already opens this popup
- The severity color/icon maps

### What is out of scope

- The RecordRelief dashboard and its webapp
- The tray (`sec_tray.py`)
- The overseer / firewall backend
- The separate stats/dashboard page

## Error handling

- Unreadable/corrupt alert files → empty list → "All clear", not a crash.
- Block write failure → status line shows "⚠ block command write failed".
- Result file unreadable → show "⚠ queued (pending helper)".
- Editor launch failure → fall back to printing the path in the status line.

## Testing

Run the popup standalone with a temp alert store:

- `python3 -m lib.sec_controls` with a sample `alerts.json`
- Verify a card expands and the expansion **survives** a refresh tick
- Verify Block writes to `firewall_commands.jsonl` and shows the result
- Verify Dismiss removes the card from the live list
- Verify text is legible and the stats header/footer are gone
