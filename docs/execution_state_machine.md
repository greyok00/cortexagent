# OPERATOR — Execution State Machine

> Tracks the state of every plan and every step.
> Persistent across sessions. Survives compaction, restarts, and interruptions.

---

## PLAN STATE MACHINE

```
┌─────────────────────────────────────┐
│                                       │
│  CREATED → PLANNED → ACTIVE → DONE  │
│     ↑         │        │              │
│     │         ↓        │              │
│     └─── REVISION ←── BLOCKED ────────┘
│                       │
│                       ↓
│                  RESUMED
```

### Plan States:

| State | Meaning | Operator Can |
|-------|---------|-------------|
| **CREATED** | Goal received, plan not yet built | Clarify goal |
| **PLANNED** | Plan built, presented, awaiting "go" | Approve, modify, cancel |
| **ACTIVE** | Steps are executing | Continue, pause, modify, cancel |
| **BLOCKED** | Something failed, can't proceed | Fix blocker, skip, abort |
| **REVISION** | Plan needs updating mid-execution | Accept changes, revert |
| **RESUMED** | Was blocked, now unblocked | Continue |
| **DONE** | All steps complete | Review deliverables |
| **CANCELLED** | Operator chose to stop | N/A |

---

## STEP STATE MACHINE

```
┌──────────────────────────────────────────┐
│                                           │
│  PENDING → ASSIGNED → RUNNING → COMPLETE  │
│    ↑          │         │                 │
│    │          ↓         ↓                 │
│    └─── WAITING ← BLOCKED ──┘             │
│              │                            │
│              ↓                           │
│           NEEDS_INPUT ←── CHECKPOINT ─────┘
```

### Step States:

| State | Meaning | Next Action |
|-------|---------|-------------|
| **PENDING** | Step exists, not yet started | Wait for dependencies |
| **ASSIGNED** | Agent has received the task | Agent starts working |
| **RUNNING** | Agent is actively working | Wait for completion |
| **NEEDS_INPUT** | Step needs operator decision | Operator provides input |
| **BLOCKED** | Step can't proceed | Fix blocker or skip |
| **WAITING** | Dependencies not yet satisfied | Wait for dependency |
| **COMPLETE** | Step finished successfully | Advance to next step |
| **CANCELLED** | Step removed from plan | Skip to next |

### State Transitions:

```
PENDING → ASSIGNED       (COORDINATOR assigns agent)
PENDING → WAITING        (dependencies not met)
PENDING → CANCELLED      (step no longer needed)

ASSIGNED → RUNNING       (agent starts work)
ASSIGNED → BLOCKED       (agent can't proceed)

RUNNING → NEEDS_INPUT    (checkpoint reached)
RUNNING → BLOCKED        (agent fails)
RUNNING → COMPLETE       (agent succeeds)

NEEDS_INPUT → ASSIGNED   (operator provides input, agent retries)
NEEDS_INPUT → CANCELLED  (operator skips this step)

BLOCKED → ASSIGNED       (blocker resolved, retry)
BLOCKED → WAITING        (waiting on dependency)
BLOCKED → CANCELLED      (operator skips)

WAITING → ASSIGNED       (dependencies now satisfied)
```

---

## STATE PERSISTENCE FORMAT

All plan state is stored in structured JSON. This survives session boundaries.

```json
{
  "plan": {
    "id": "plan-001",
    "goal": "I need a new business",
    "status": "active",
    "created_at": "2026-08-01T10:00:00Z",
    "updated_at": "2026-08-01T14:32:00Z",
    "phases": [
      {
        "id": "phase-1",
        "name": "Market Research & Validation",
        "order": 1,
        "status": "active",
        "steps": [
          {
            "id": "1.1",
            "title": "Identify 3 promising markets",
            "description": "...",
            "status": "complete",
            "agent": "RESEARCHER",
            "automation": "auto",
            "dependencies": [],
            "done_criteria": "Market report with ≥3 options",
            "input_data": [],
            "output_data": "markets.json",
            "effort": "moderate",
            "started_at": "2026-08-01T10:05:00Z",
            "completed_at": "2026-08-01T10:22:00Z",
            "result": "market_analysis.json",
            "error": null,
            "retry_count": 0,
            "notes": []
          },
          {
            "id": "1.2",
            "title": "Analyze each market's size, growth, competition",
            "description": "...",
            "status": "running",
            "agent": "ANALYST",
            "automation": "auto",
            "dependencies": ["1.1"],
            "done_criteria": "Competitive analysis with market sizing",
            "input_data": ["markets.json"],
            "output_data": "market_analysis.json",
            "effort": "heavy",
            "started_at": "2026-08-01T10:23:00Z",
            "completed_at": null,
            "result": null,
            "error": null,
            "retry_count": 0,
            "notes": []
          },
          {
            "id": "1.3",
            "title": "Rank markets by opportunity score",
            "description": "...",
            "status": "pending",
            "agent": "COORDINATOR",
            "automation": "auto",
            "dependencies": ["1.2"],
            "done_criteria": "Ranked list of markets with scores",
            "input_data": ["market_analysis.json"],
            "output_data": "ranked_markets.json",
            "effort": "quick",
            "started_at": null,
            "completed_at": null,
            "result": null,
            "error": null,
            "retry_count": 0,
            "notes": []
          },
          {
            "id": "1.4",
            "title": "Select target market",
            "description": "...",
            "status": "pending",
            "agent": "OPERATOR",
            "automation": "checkpoint",
            "dependencies": ["1.3"],
            "done_criteria": "Operator selects 1 market",
            "input_data": ["ranked_markets.json"],
            "output_data": "selected_market.txt",
            "effort": "quick",
            "started_at": null,
            "completed_at": null,
            "result": null,
            "error": null,
            "retry_count": 0,
            "notes": []
          }
        ]
      }
    ]
  }
}
```

---

## STATE RECOVERY

When a session is resumed (after compaction, restart, or interruption):

1. **Load plan state from persistence layer.**
2. **Check each step's status:**
   - `complete` → confirmed done
   - `running` → likely stale (session ended), mark as `pending`
   - `assigned` → mark as `pending`
   - `blocked` → re-diagnose blocker
   - `needs_input` → re-present to operator
3. **Present recovery state:**
   ```
   ┌─ Recovery: [plan name]
   ├─ Completed: [N/N steps]
   ├─ Active: [step ID] — was running, now paused
   ├─ Pending: [step ID] — ready to start
   └─ What to do:
      1. Resume step [ID]
      2. Skip step [ID] and continue
      3. Restart plan
      4. Cancel plan
      What do you want? (1/2/3/4)
   ```

---

## PROGRESS REPORTING

Every N steps completed, or on operator request, present progress:

```
┌─ Progress: [plan name]
├─ Overall: [N/M steps] — [X%]
├─ Phase 1: [name] — [N/M] [X%]
│   └─ [status icons]
├─ Phase 2: [name] — [N/M] [X%]
│   └─ [status icons]
├─ Active: [current step] — [agent working]
├─ Next: [next step] — [agent]
└─ ETA: [estimated time remaining]
```

### Progress Icons:
- ✅ = complete
- 🔄 = running
- ⏳ = waiting on dependencies
- ⚠ = blocked
- ❓ = needs input
- ⬚ = pending
- ✕ = cancelled

---

## ERROR HANDLING IN STATE MACHINE

### When a step fails (RUNNING → BLOCKED):

1. **Record error** in step state
2. **Try alternative approach** once (increment retry_count)
3. **If still fails:**
   - Present to operator with: what happened, what we tried, what we recommend
   - Operator chooses: retry, skip, or abort

### When a checkpoint is hit (RUNNING → NEEDS_INPUT):

1. **Present the checkpoint** with options and recommendation
2. **Wait for operator input**
3. **When operator responds:**
   - Apply operator's decision
   - Continue step with new parameters
   - If step can't proceed with new parameters → BLOCKED

### When a dependency fails (PENDING → WAITING):

1. **Check if dependency will recover**
2. **If dependency is blocked permanently:**
   - Mark this step as BLOCKED too
   - Cascade BLOCKED to all downstream steps
   - Present to operator

---

*This state machine is the backbone of the execution pipeline. Every plan, every step, every state change is tracked here.*
