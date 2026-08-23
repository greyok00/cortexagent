# Analysis: Prompt Review & Implementation Plan — 2026-08-14

**Date:** 2026-08-14 14:30 UTC  
**Author:** CortexLLM  
**Purpose:** Analyze the consolidated prompt text, compare against existing implementation, identify gaps, and produce a prioritized plan.

---

## 0. What We Have Done So Far (Baseline — do not forget)

### 0.1 Completed Features

| Feature | Status | Files |
|---|---|---|
| **System Tray Icon** | ✅ Working (brand logo, GUI mode) | `lib/tray.py`, `lib/tray_dashboard.py` |
| **Minify Stats / Slimtoken** | ✅ Working (7.8% savings, 257 runs) | `lib/grammar_proxy.py` |
| **Stuck Scheduler Tasks** | ✅ Cleaned (removed smoke-test, verify-test) | Overseer scheduler |
| **Queue Cleanup** | ✅ Working (auto-prune, keeps last 10) | `lib/overseer.py` |
| **Code Blocks Disabled** | ✅ Applied to ReAct/Socratic prompts | `lib/react_loop.py` |
| **Beautification Pass** | ✅ Working (tables, CSV, key:value) | `lib/beautify.py`, `lib/react_loop.py`, `lib/overseer.py` |
| **Domain DB Access** | ✅ Working (FTS5 + sqlite-vec, rag_query, ingest_domain) | `lib/domain_db.py`, `lib/domain_ingest.py`, `lib/domain_embed.py` |
| **ReAct / Socratic Methods** | ✅ Working (react, socratic, direct modes) | `lib/react_loop.py` |
| **Token Tracking** | ✅ Working (proxy + tiny model merged) | `lib/token_tracker.py`, `lib/overseer.py` |
| **Prompt Framing** | ✅ Working (domain classification + optimization) | `lib/prompt_framing.py` |
| **Beautification v2** | ✅ Working (sparklines, waffles, gauges, charts) | `lib/charts.py`, `lib/beautify.py` |
| **Post Processor** | ✅ Working (strips fences, thinking, normalizes glyphs) | `lib/post_processor.py` |
| **Observability** | ✅ Working (traces, metrics, evals, NDJSON) | `lib/observability.py` |
| **Load Test Kit** | ✅ Working (proxy, overseer, e2e, disk, error injection) | `lib/load_test.py`, `lib/run_full_test.py` |
| **WebUI Dashboard** | ✅ Working (token stats, beautification, overseer status) | `lib/webui.py` |
| **Architecture Docs** | ✅ Created | `ARCHITECTURE.md`, `README.md`, `OBSERVABILITY_IMPLEMENTATION.md` |

### 0.2 Partial / In-Progress Features

| Feature | Status | Gap |
|---|---|---|
| **Scheduler as Authoritative Store** | ⚠️ Partial | Uses JSON files, not event-sourced. Missing: durable receipts, crash recovery, reconciliation. |
| **Queue Backpressure** | ⚠️ Partial | Has `MAX_QUEUE_SIZE` but missing: worker health checks, heartbeat, backpressure metrics in UI. |
| **Observability Integration** | ⚠️ Partial | Standalone module, not yet integrated into `react_loop.py` or `grammar_proxy.py` as auto-capture. |
| **Scheduler UI Strip** | ⚠️ Partial | Overseer shows schedule count, but Pi strip doesn't render canonical data. |

### 0.3 Architecture Overview (Current)

```
cortexagent (bin/cortexagent)
   ├─ lib/daemon.py          ← big :8080 + tiny :8082 + proxy :8081
   ├─ lib/overseer.py        ← scheduler + queue + watchdog + tiny keepalive
   ├─ lib/tray.py            ← system-tray (overseer owner)
   ├─ lib/webui.py           ← WebUI on :8090
   ├─ lib/grammar_proxy.py   ← slimtoken + grammar proxy :8081
   ├─ lib/react_loop.py      ← ReAct/Socratic orchestration
   ├─ lib/beautify.py        ← tables, sparklines, waffles, gauges
   ├─ lib/post_processor.py  ← fence/thinking/glyph normalization
   ├─ lib/token_tracker.py   ← proxy + tiny model token stats
   ├─ lib/prompt_framing.py  ← domain classification + optimization
   ├─ lib/observability.py   ← traces, metrics, evals (NDJSON)
   ├─ lib/load_test.py       ← proxy/overseer/e2e stress tests
   └─ lib/run_full_test.py   ← orchestrator for full test suite
```

---

## 1. Analysis of the Consolidated Prompt Text

### 1.1 What the Prompt Says

The consolidated prompt contains several major directives:

1. **Scheduler Overhaul** — Make the overseer scheduler the *authoritative, durable, crash-safe* task system. Replace JSON state with event-sourced NDJSON + atomic snapshot.
2. **CortexLLM File Persistence** — Use plain-file, NDJSON append-first patterns (like hot/warm/cold memory) for scheduler state. No SQLite.
3. **Direct Local Python Tools** — Use typed Python tools as the default execution path. Keep MCP optional only.
4. **Observability Hooks** — Per-request latency, tokens, context usage, queue metrics.
5. **Stability Under Load** — Bounded queues, backpressure, worker pools with heartbeat, backoff/retry, shutdown drain.
6. **Task Ledger / Definition of Done** — Every engineering task must have evidence (tests, before/after metrics, diff hashes).
7. **Beautification** — Keep sparklines, waffles, gauges; add color palette.
8. **Post Processor** — Strip code fences, thinking preambles, normalize glyphs.

### 1.2 What We've Already Done vs. What's New

| Directive | Already Done | Still Needs Work |
|---|---|---|
| Scheduler durability | ⚠️ JSON files, basic CRUD | ❌ Event-sourced NDJSON, atomic snapshots, reconciliation |
| CortexLLM persistence model | ⚠️ Partial (hot/warm/cold NDJSON exists) | ❌ Scheduler uses JSON, not NDJSON + atomic rename |
| Direct local Python tools | ✅ `lib/tool_registry.py` | ⚠️ MCP still partially present, needs cleanup |
| Observability hooks | ✅ Standalone module | ❌ Not integrated into `react_loop.py` / `grammar_proxy.py` |
| Queue backpressure | ⚠️ Has `MAX_QUEUE_SIZE` | ❌ Missing: worker heartbeat, backpressure metrics, UI integration |
| Task ledger / DoD | ❌ Not implemented | ❌ Needs docs/ledger, task record schema |
| Beautification v2 | ✅ Sparklines, waffles, gauges | ⚠️ Color palette integration, post-processor integration |
| Post processor | ✅ Fence/stripping/glyph normalization | ❌ Not integrated into `react_loop.py` |

---

## 2. Implementation Priorities

### Phase 1: Scheduler Overhaul (Critical — This is the bottleneck)

**Why first:** The scheduler is the single point of failure. Without durable, crash-safe task state, nothing else matters. The prompt explicitly says: "Do not begin broad beautification, WebUI redesign, model tuning, or unrelated refactors until the scheduler truth, persistence, and restart behavior are working and verified."

#### 2.1 Scheduler Redesign (Scheduler Overhaul)

**Files to create:**
- `lib/scheduler/store.py` — NDJSON event-sourced scheduler store
- `lib/scheduler/recovery.py` — Crash recovery, reconciliation logic

**Files to modify:**
- `lib/overseer.py` — Replace schedule_add/list/remove with scheduler.store calls

**Schema (event-sourced):**
```
tasks.json              ← canonical snapshot (atomic replace)
tasks.events.jsonl      ← immutable event log
executions.jsonl        ← execution receipts
state.json              ← scheduler cursor/checkpoint
lock                    ← POSIX lock (single-writer)
```

**Events (append-only, NDJSON):**
```json
{"type": "create", "id": "uuid", "title": "...", "state": "scheduled", "next_run": "...", "version": 1}
{"type": "update", "id": "uuid", "state": "running", "version": 2}
{"type": "fire", "id": "uuid", "execution_id": "uuid", "version": 3}
{"type": "complete", "id": "uuid", "status": "success", "version": 4}
{"type": "cancel", "id": "uuid", "version": 5}
```

**Recovery logic:**
1. Read `state.json` → get last known-good version
2. Read `tasks.json` → verify against version
3. Replay events from `tasks.events.jsonl` starting after version
4. Write new `tasks.json` + update `state.json`
5. Mark interrupted tasks as `failed` or `retryable`
6. Emit `scheduler_reconciled` event with counts

#### 2.2 Scheduler Operations

Replace the existing JSON schedule functions with these:

```python
class SchedulerOperation(Enum):
    CREATE = "schedule.create"
    GET = "schedule.get"
    LIST = "schedule.list"
    UPDATE = "schedule.update"
    PAUSE = "schedule.pause"
    RESUME = "schedule.resume"
    RUN_NOW = "schedule.run_now"
    CANCEL = "schedule.cancel"
    ARCHIVE = "schedule.archive"
    CLEAR_TEST_TASKS = "schedule.clear_test_tasks"
    RECONCILE = "schedule.reconcile"
```

Each operation must return:
- Success: `{ok: true, receipt: {task_id, version, canonical_title, next_run, read_back_hash}}`
- Failure: `{ok: false, error: "message", no_change: true}`

### Phase 2: Queue & Stability (High Priority)

#### 2.3 Queue Improvements

**Files to modify:**
- `lib/overseer.py` — Enhance queue with worker pools, heartbeat, metrics

**Changes:**
1. **Worker pool with heartbeat:**
   - Each worker is a thread with a heartbeat timestamp
   - Overseer checks heartbeat every 60s
   - If heartbeat misses, mark worker as dead, reschedule tasks
   - Replace dead workers with new ones

2. **Backpressure metrics:**
   - Track `qsize()`, `put_rate`, `get_rate`, `p95_latency`, `p99_latency`
   - Expose in overseer status and WebUI

3. **Shutdown drain:**
   - On SIGTERM, stop accepting new tasks
   - Drain queue: process remaining tasks, call `task_done()` in finally
   - Join workers before exit

4. **Retry with jitter:**
   - Wrap fragile dependencies (llama-server, diffusion) in retry
   - Use exponential backoff with jitter
   - Cap concurrent calls via semaphore

#### 2.4 Worker Pool Implementation

```python
class WorkerPool:
    def __init__(self, max_workers=5, heartbeat_interval=60):
        self.max_workers = max_workers
        self.heartbeat_interval = heartbeat_interval
        self.workers = []
        self.heartbeat_deadline = time.time() + heartbeat_interval
    
    def start(self):
        for _ in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self.workers.append({"thread": t, "last_heartbeat": time.time(), "status": "alive"})
    
    def heartbeat_check(self):
        now = time.time()
        for w in self.workers:
            if now - w["last_heartbeat"] > self.heartbeat_interval * 2:
                w["status"] = "dead"
                # Reschedule tasks to a new worker
                self._replace_worker(w)
    
    def _worker_loop(self):
        try:
            while True:
                task = queue.get(timeout=5)
                try:
                    self._execute_task(task)
                finally:
                    queue.task_done()
                    self._heartbeat()
        except Exception:
            pass
```

### Phase 3: Observability Integration (Medium Priority)

#### 2.5 Auto-Capture Spans

**Files to modify:**
- `lib/react_loop.py` — Wrap LLM calls, tool calls, beautify in spans
- `lib/grammar_proxy.py` — Wrap minify, grammar checks in spans
- `lib/overseer.py` — Wrap scheduler operations, queue dispatch in spans

**Pattern:**
```python
from lib.observability import trace, span

with trace("agent_run", user_input=prompt) as tr:
    with span(tr.id, "classify", "intent_classification") as s:
        intent = classify_intent(prompt)
        s.set_metric("intent", intent)
    
    with span(tr.id, "framing", "prompt_framing") as s:
        framed = frame_prompt(prompt, intent)
        s.set_metric("tokens_in", len(framed) // 4)
    
    with span(tr.id, "llm", "tiny_model_query") as s:
        result = tiny_llm(framed)
        s.set_metric("tokens_in", len(prompt) // 4)
        s.set_metric("tokens_out", len(result) // 4)
        s.set_metric("latency_ms", (time.time() - start) * 1000)
    
    with span(tr.id, "beautify", "output_formatting") as s:
        output = beautify(result)
    
    with span(tr.id, "postprocess", "fence_strip") as s:
        output = process_output(output)
```

### Phase 4: Beautification & Post Processor Integration (Low Priority)

#### 2.6 Post Processor Integration

**Files to modify:**
- `lib/react_loop.py` — Call `process_output()` on LLM output before returning

**Change:**
```python
# Before:
output = result.get("output", "")

# After:
output = result.get("output", "")
output = process_output(output, show_code=False, show_thinking=False)
```

#### 2.7 Color Palette Integration

**Files to create:**
- `lib/beautify_colors.py` — Semantic color mapping for terminal

**Files to modify:**
- `lib/beautify.py` — Use semantic colors instead of raw ANSI escapes
- `lib/semantic_palette.py` — Already exists, integrate into beautify

### Phase 5: Task Ledger / Definition of Done (Medium Priority)

#### 2.8 Ledger Implementation

**Files to create:**
- `docs/implementation-ledger.md` — Markdown ledger of all tasks
- `lib/ledger.py` — JSON-based task record storage

**Schema:**
```json
{
  "id": "BEAUTIFY-001",
  "type": "implementation",
  "status": "verified",
  "files_changed": ["lib/beautify.py"],
  "git_diff_hash": "abc123",
  "test_command": "python3 lib/beautify.py smoke",
  "test_result": "14 passed",
  "integration_proof": "CLI output captured",
  "before_metric": "p95 render: 8.4 ms",
  "after_metric": "p95 render: 1.7 ms",
  "rollback": "git revert abc123",
  "acceptance_criteria": "No markdown fences; sparkline at 20-120 columns"
}
```

---

## 3. Immediate Action Plan

### 3.1 First: Freeze New Planning

As the prompt says: "Freeze new architectural planning until there is an implementation ledger and a completion-receipt schema."

**Action:** Create `docs/implementation-ledger.md` with current status of all tasks.

### 3.2 Second: Select Three Vertical Slices

As the prompt says: "Select only three vertical slices: BEAUTIFY-001, OBS-001, QUEUE-001"

But we've already done BEAUTIFY-001 (post processor) and OBS-001 (observability). So the remaining vertical slice is:

**QUEUE-001: Bounded overseer queue with backpressure, timeout, retry classification, and shutdown drain.**

This is the highest-value remaining work because:
1. It directly addresses the stability concerns
2. It feeds into the scheduler overhaul (Phase 1)
3. It's testable in isolation

### 3.3 Third: Scheduler Overhaul (Phase 1)

This is the critical path. Without durable scheduler state, nothing else works reliably.

**Implementation order:**
1. Create `lib/scheduler/store.py` (NDJSON event-sourced store)
2. Create `lib/scheduler/recovery.py` (crash recovery + reconciliation)
3. Create `lib/scheduler/ui.py` (canonical scheduler strip for Pi/WebUI)
4. Modify `lib/overseer.py` to use the new scheduler
5. Create migration script to convert existing JSON schedule → NDJSON
6. Write tests and smoke test

---

## 4. Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| Scheduler migration corrupts existing tasks | High | Backup before migration; rollback plan |
| NDJSON event replay is slow | Medium | Start from snapshot + replay only recent events |
| Worker heartbeat misses on slow systems | Low | Make heartbeat threshold configurable |
| Observability spans add overhead | Low | Only sample 10% of spans in production |
| Post processor strips too much | Medium | Make `show_code`/`show_thinking` configurable |

---

## 5. Files to Change (Summary)

| File | Change | Phase |
|---|---|---|
| `lib/scheduler/store.py` | **CREATE** — NDJSON event-sourced scheduler | Phase 1 |
| `lib/scheduler/recovery.py` | **CREATE** — Crash recovery + reconciliation | Phase 1 |
| `lib/scheduler/ui.py` | **CREATE** — Canonical scheduler strip | Phase 1 |
| `lib/overseer.py` | **MODIFY** — Replace schedule functions, add worker pool, heartbeat, metrics | Phase 1 + 2 |
| `lib/react_loop.py` | **MODIFY** — Integrate post processor + observability spans | Phase 3 + 4 |
| `lib/grammar_proxy.py` | **MODIFY** — Add observability spans | Phase 3 |
| `lib/beautify.py` | **MODIFY** — Integrate semantic palette | Phase 4 |
| `lib/semantic_palette.py` | **MODIFY** — Export color functions | Phase 4 |
| `docs/implementation-ledger.md` | **CREATE** — Task ledger | Phase 5 |
| `lib/ledger.py` | **CREATE** — Task record storage | Phase 5 |

---

## 6. Testing Strategy

### 6.1 Scheduler Tests

```bash
# Smoke test
python3 lib/scheduler/store.py smoke

# Recovery test
python3 lib/scheduler/recovery.py test --corrupt

# Full test
python3 lib/run_full_test.py scheduler
```

### 6.2 Queue Tests

```bash
# Backpressure test
python3 lib/run_full_test.py queue --count=500 --parallel=20

# Shutdown drain test
python3 lib/run_full_test.py shutdown

# Worker heartbeat test
python3 lib/run_full_test.py worker-heartbeat --fail=5
```

### 6.3 Integration Tests

```bash
# Full chain test
python3 lib/run_full_test.py all

# Error injection test
python3 lib/run_full_test.py inject --model-down --network-timeout
```

---

## 7. What NOT to Do

Per the prompt's explicit instructions:

1. **Don't change MCP yet** — Keep it optional, don't break existing integrations
2. **Don't redesign WebUI** — Focus on scheduler first
3. **Don't tune models** — Keep current configs
4. **Don't add new features** — Only implement what's in this plan
5. **Don't claim completion without proof** — Every task needs test results, diff hashes, before/after metrics

---

## 8. Acceptance Criteria for Completion

### Scheduler Overhaul (Phase 1)
- [ ] `tasks.json` is atomic-replaced after each mutation
- [ ] `tasks.events.jsonl` captures every mutation (immutable)
- [ ] Crash recovery works: interrupt write, recover valid state
- [ ] Restart: tasks survive, next_run recalculated correctly
- [ ] One-shot task follows missed-run policy after downtime
- [ ] Recurring task computes next_run correctly after downtime

### Queue & Stability (Phase 2)
- [ ] Bounded queue with backpressure (no OOM)
- [ ] Worker pool with heartbeat (60s interval)
- [ ] Dead worker detected and replaced
- [ ] Backpressure metrics exposed in overseer status
- [ ] Shutdown drain: all tasks processed before exit
- [ ] Retry with jitter for fragile dependencies

### Post Processor Integration (Phase 4)
- [ ] `process_output()` called on all LLM output
- [ ] Code fences stripped by default
- [ ] Thinking preambles stripped by default
- [ ] Glyphs normalized (▎ bullets, ━━━ separators)

### Task Ledger (Phase 5)
- [ ] `docs/implementation-ledger.md` created
- [ ] All existing tasks have status, evidence, test results
- [ ] No task claims "done" without proof

---

## 9. Next Immediate Steps

1. **Create `docs/implementation-ledger.md`** — Document all current tasks with status
2. **Create `lib/scheduler/store.py`** — Start with the NDJSON event store
3. **Write scheduler tests** — Before implementation, write the tests
4. **Run smoke tests** — Verify nothing breaks during migration
5. **Migrate existing scheduler** — Convert JSON → NDJSON + atomic snapshot
6. **Integrate into overseer** — Replace schedule_add/list/remove
7. **Test restart recovery** — Kill overseer mid-mutation, verify recovery

---

*End of analysis. Proceed to implementation after approval.*
