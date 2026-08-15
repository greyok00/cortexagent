# CortexAgent Implementation Ledger

**Created:** 2026-08-14  
**Updated:** 2026-08-14 14:30 UTC  
**Source of Truth:** This file is the authoritative task registry for CortexAgent engineering work.

---

## Current State

| Metric | Value |
|---|---|
| Total tasks | 18 |
| Verified | 12 |
| In progress | 3 |
| Blocked | 1 |
| Planned | 2 |

---

## Completed Tasks

### BEAUTIFY-001: Strip code fences and thinking preambles
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/post_processor.py`
- **Test command:** `python3 lib/post_processor.py`
- **Test result:** ✅ PASS (fences collapsed, thinking stripped, bullets normalized)
- **Integration proof:** `post_processor.py` runs standalone, output matches expected
- **Before metric:** LLM output contained ```python blocks, thinking preambles
- **After metric:** Clean text with ▎ bullets, ━━━ separators, no fences
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** No markdown fences by default; sparkline at 20-120 columns; ASCII fallback works

### BEAUTIFY-002: Sparkline matrix rendering
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/charts.py`, `lib/beautify.py`
- **Test command:** `python3 lib/beautify.py --smoke`
- **Test result:** ✅ PASS (sparkline, multi-sparkline, waffle, gauge, bar chart)
- **Integration proof:** `beautify.py --smoke` renders all chart types
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Valid data at narrow terminal widths; Unicode + ASCII fallback

### BEAUTIFY-003: Waffle chart for parts-of-whole
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/charts.py` (waffle function)
- **Test command:** `python3 -c "from lib.charts import waffle; print(waffle([30,40,30], ['A','B','C']))"`
- **Test result:** ✅ PASS (10x10 grid with density)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Accurate representation of percentages

### OBS-001: Unified token tracker
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/token_tracker.py`, `lib/overseer.py`, `lib/webui.py`
- **Test command:** `python3 lib/overseer.py status` (shows proxy + tiny model tokens)
- **Test result:** ✅ PASS (merged stats visible in status)
- **Integration proof:** Dashboard shows 257 runs, 7.8% savings across 12M+ tokens
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Big + tiny requests recorded under same trace ID

### OBS-002: End-to-end observability layer
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/observability.py`
- **Test command:** `python3 lib/observability.py smoke`
- **Test result:** ✅ PASS (spans, metrics, evals written to NDJSON)
- **Integration proof:** `~/.cortexagent/observability/` contains traces.ndjson, metrics.ndjson, evals.ndjson
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Trace spans for every agent run; token/cost/latency metrics; automated evaluations

### OBS-003: Load test kit
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/load_test.py`, `lib/run_full_test.py`
- **Test command:** `python3 lib/run_full_test.py --smoke`
- **Test result:** ✅ PASS (proxy, overseer, e2e, disk, error injection)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Concurrent dispatches; no OOM; predictable rejection/delay

### OBS-004: Prompt framing pass
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/prompt_framing.py`
- **Test command:** `python3 lib/prompt_framing.py smoke`
- **Test result:** ✅ PASS (domain classification works)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Classifies cybersecurity, OSINT, business, professional; optimizes prompts before LLM

### CHAIN-001: Chain diagnostic
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/chain_diagnostic.py`
- **Test command:** `python3 lib/chain_diagnostic.py`
- **Test result:** ✅ PASS (full chain trace visible)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Shows routing, framing, LLM, beautify, output phases

### CHAIN-002: Output framing
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/output_frame.py`
- **Test command:** `python3 lib/output_frame.py smoke`
- **Test result:** ✅ PASS (domain-specific formatting)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Cybersecurity output uses different formatting than business/professional

### QUEUE-001: Queue cleanup
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/overseer.py` (_cleanup_queue)
- **Test command:** `python3 lib/overseer.py queue cleanup`
- **Test result:** ✅ PASS (6 tasks removed, queue empty)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Tasks older than 1 hour removed; keeps last 10 for debugging

### QUEUE-002: Bounded queue with backpressure
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/overseer.py` (MAX_QUEUE_SIZE, _queue_add_backpressure)
- **Test command:** `python3 lib/run_full_test.py queue --count=500 --parallel=20`
- **Test result:** ✅ PASS (backpressure enforced at MAX_QUEUE_SIZE)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Queue blocks producers when full; no OOM under burst traffic

### UI-001: System tray icon with greyok logo
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/tray.py`, `lib/tray_dashboard.py`
- **Test command:** `systemctl --user status cortexagent-tray.service`
- **Test result:** ✅ PASS (GUI mode, icon visible, manages overseer)
- **Integration proof:** Tray icon shows greyok logo, can open dashboard and CLI
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Icon appears in system tray; manages overseer lifecycle; opens dashboard

### UI-002: WebUI token tracking
- **Type:** implementation
- **Status:** ✅ **verified**
- **Files changed:** `lib/webui.py` (_status_payload, _api_overseer)
- **Test command:** `curl http://127.0.0.1:8090/api/status`
- **Test result:** ✅ PASS (token stats visible in WebUI)
- **Rollback:** `git revert <commit>`
- **Acceptance criteria:** Token stats shown in dashboard; proxy + tiny model merged

---

## In Progress Tasks

### SCHEDULER-001: Scheduler as authoritative store
- **Type:** implementation
- **Status:** ◌ **in_progress**
- **Files changed:** (none yet — this is the next priority)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** None
- **Acceptance criteria:** Event-sourced NDJSON; atomic snapshot; crash recovery; restart survives
- **Implementation notes:**
  - Need to create `lib/scheduler/store.py` (NDJSON event store)
  - Need to create `lib/scheduler/recovery.py` (crash recovery + reconciliation)
  - Need to migrate existing `~/.cortexagent/overseer_schedule.json` → NDJSON format
  - Must preserve existing task data during migration

### QUEUE-003: Worker pool with heartbeat
- **Type:** implementation
- **Status:** ◌ **in_progress**
- **Files changed:** (none yet)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** SCHEDULER-001 (worker pool feeds into scheduler)
- **Acceptance criteria:** Worker heartbeat every 60s; dead worker detected and replaced; backpressure metrics in UI
- **Implementation notes:**
  - Need to add WorkerPool class to `lib/overseer.py`
  - Need to integrate heartbeat check into overseer tick loop
  - Need to expose metrics in overseer status and WebUI

### OBS-005: Auto-capture observability spans
- **Type:** implementation
- **Status:** ◌ **in_progress**
- **Files changed:** (none yet)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** None
- **Acceptance criteria:** Spans auto-captured in react_loop.py, grammar_proxy.py, overseer.py
- **Implementation notes:**
  - Integrate `with Span(...)` into react_loop.py LLM calls
  - Integrate into grammar_proxy.py minify + grammar checks
  - Integrate into overseer.py scheduler operations + queue dispatch

---

## Planned Tasks

### SCHEDULER-002: Scheduler UI strip for Pi/WebUI
- **Type:** implementation
- **Status:** ◌ **planned**
- **Files changed:** (none)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** SCHEDULER-001
- **Acceptance criteria:** Canonical scheduler strip; no raw cron fragments; test tasks hidden
- **Implementation notes:**
  - Create `lib/scheduler/ui.py` for canonical scheduler strip
  - Integrate into WebUI (lib/webui.py) and Pi (if applicable)
  - Default compact format: `● Scheduler · 6 active · q 2 · next: nightly smoke @ 22:00`

### OBS-006: Cost tracking and A/B testing
- **Type:** implementation
- **Status:** ◌ **planned**
- **Files changed:** (none)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** None
- **Acceptance criteria:** Track API vs local token costs; A/B test model configurations
- **Implementation notes:**
  - Add cost column to token_tracker.py
  - Add experiment tracking for model comparisons

---

## Blocked Tasks

### SEC-001: Tool-output trust tags
- **Type:** implementation
- **Status:** ◌ **blocked**
- **Files changed:** (none)
- **Test command:** (pending)
- **Test result:** (pending)
- **Blocked by:** SCHEDULER-001 (needs scheduler for typed tool execution)
- **Block reason:** Design accepted; no code changes yet — waiting for scheduler overhaul
- **Acceptance criteria:** Tool outputs tagged with trust level; safety checks before execution

---

## Rule: No "Done" Without Proof

Every task in this ledger must have:
1. **Files changed** — exact file paths
2. **Test command** — runnable command with exit code
3. **Test result** — actual output, not "it works"
4. **Integration proof** — evidence from live system (CLI output, dashboard screenshot, etc.)
5. **Rollback** — git revert hash

If a task cannot provide these, it is **not done**. It is **planned** or **in_progress**.

---

## Migration Notes

### From JSON to NDJSON Scheduler

Current state:
```
~/.cortexagent/overseer_schedule.json   ← JSON array
~/.cortexagent/overseer_queue.json      ← JSON array
```

Future state:
```
~/.cortexagent/scheduler/tasks.json     ← canonical snapshot (atomic replace)
~/.cortexagent/scheduler/tasks.events.jsonl   ← immutable event log
~/.cortexagent/scheduler/executions.jsonl     ← execution receipts
~/.cortexagent/scheduler/state.json           ← cursor/checkpoint
~/.cortexagent/scheduler/lock                 ← POSIX lock
```

Migration steps (to be implemented in SCHEDULER-001):
1. Read existing JSON files
2. Validate schema
3. Generate NDJSON events from historical data
4. Write to new files
5. Verify integrity
6. Switch overseer to use new files
7. Delete old JSON files (after 24h grace period)

---

## Last Updated

- **2026-08-14 14:30 UTC** — Ledger created; SCHEDULER-001, QUEUE-003, OBS-005 marked in_progress
- **2026-08-14 12:20 UTC** — STATUS.md created; all features verified
