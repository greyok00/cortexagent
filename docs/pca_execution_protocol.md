# OPERATOR — PCA Execution Protocol

> The operational loop that runs a plan from start to finish.
> This is how the PCA orchestrates agents, tracks state, and delivers results.

---

## THE EXECUTION LOOP

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  1. LOAD STATE → is there an existing plan?             │
│         │                                               │
│         ▼                                               │
│  2. IF NO PLAN: BUILD PLAN (decomposition)              │
│         │                                               │
│         ▼                                               │
│  3. PRESENT PLAN TO OPERATOR → get confirmation         │
│         │                                               │
│         ▼                                               │
│  4. FIND NEXT READY STEP → (dependencies met)           │
│         │                                               │
│         ▼                                               │
│  5. CHECK STEP TYPE                                     │
│         │                                               │
│    ┌────┼─────────┬───────────┬────────┐               │
│    │    │         │           │        │               │
│    ▼    ▼         ▼           ▼        ▼               │
│  AUTO  CHECKPOINT  MANUAL    BLOCKED   COMPLETE         │
│    │      │         │         │        │               │
│    ▼      ▼         ▼         ▼        ▼               │
│  Assign  Present   Tell       Retry  Advance          │
│  agent   to op     operator   or     to next          │
│  to work skip      input      cancel                   │
│    │      │         │         │        │               │
│    └──────┴─────────┴─────────┴────────┘               │
│         │                                               │
│         ▼                                               │
│  6. WAIT FOR COMPLETION                                 │
│         │                                               │
│         ▼                                               │
│  7. VERIFY OUTPUT against done criteria                 │
│         │                                               │
│         ▼                                               │
│  8. UPDATE STATE → mark step complete                   │
│         │                                               │
│         ▼                                               │
│  9. SAVE STATE → persist to memory layer                │
│         │                                               │
│         ▼                                               │
│ 10. ANY STEPS LEFT? ──NO──→ DONE (present summary)     │
│        │                                                  │
│       YES ──→ LOOP BACK TO STEP 4                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## DETAILED STEP EXECUTION

### STEP 4: FIND NEXT READY STEP

Find the next step that is:
- Status is `pending` or `waiting`
- All dependencies are `complete`

If multiple steps are ready, prioritize:
1. **Current phase** — finish the current phase before moving on
2. **High priority** — within the phase, highest priority first
3. **Quick first** — if operator is engaged, do quick steps to build momentum

```
Ready steps: [list of step IDs that are ready to run]
Current: [step ID] — [agent] — [effort] — [automation type]
```

---

### STEP 5 (AUTO): Execute Autonomous Step

1. **Build task payload:**
   ```
   {
     step_id: "1.2",
     title: "Analyze market sizing",
     description: "...",
     agent: "ANALYST",
     input_data: {
       markets.json: <result from step 1.1>
     },
     done_criteria: "JSON file with market size, growth rate, competition for each market"
   }
   ```

2. **Route to COORDINATOR** who assigns to the specified agent.

3. **Wait for agent completion.**

4. **Verify output** against done criteria (see verification protocol below).

5. **If verified:** mark complete, advance.
   **If not verified:** try once with feedback. If still fails → BLOCKED.

---

### STEP 5 (CHECKPOINT): Present to Operator

1. **Agent completes the step** and produces findings.
2. **COORDINATOR formats the checkpoint:**
   ```
   ┌─ Checkpoint: [Step Title]
   ├─ What we found: [summary]
   ├─ Options:
   │   1. [Option A] — pros, cons, effort
   │   2. [Option B] — pros, cons, effort
   │   3. [Option C] — pros, cons, effort
   ├─ Recommendation: [which option and why]
   └─ What do you want? (1/2/3/custom)
   ```

3. **Wait for operator input.**

4. **Apply operator's decision** and continue or block accordingly.

---

### STEP 5 (MANUAL): Operator Must Act

1. **Tell the operator exactly what to do:**
   ```
   ┌─ Action Required: [Step Title]
   ├─ What to do: [specific, step-by-step instructions]
   ├─ Where: [URL, location, app]
   ├─ Why: [brief context]
   └─ Done: type "done" when complete
   ```

2. **Wait for operator to perform the action.**

3. **Operator types "done"** → verify it was done (if possible), advance.

---

### STEP 5 (BLOCKED): Handle Failure

1. **Diagnose the failure:**
   ```
   ┌─ Blocked: [Step Title]
   ├─ What failed: [description]
   ├─ Why: [root cause]
   ├─ What we tried: [attempts made]
   ├─ Recommendation: [best path forward]
   ├─ Options:
   │   1. Retry (what's different)
   │   2. Skip this step, continue
   │   3. Modify the step, retry
   │   4. Stop and reassess
   └─ What do you want? (1/2/3/4)
   ```

2. **Wait for operator decision.**

3. **Apply decision:** retry, skip, or stop.

---

## VERIFICATION PROTOCOL

After each step completes, verify against done criteria:

```
Step: [title]
Done Criteria: [what was supposed to be produced]
Actual Output: [what was actually produced]

Verification:
[ ] Matches done criteria? YES/NO
[ ] Quality acceptable? YES/NO
[ ] Any gaps or issues? YES/NO
```

**If verification fails:**
- Show the operator what's missing
- Suggest a fix
- Retry once with the fix
- If still fails → BLOCKED

**If verification passes:**
- Mark step complete
- Save results
- Advance to next step

---

## STATE PERSISTENCE

After every state change, save to the appropriate layer:

```
On step complete → Save to COLD memory (project history)
On step blocked → Save to HOT memory (active plan)
On plan update → Save to HOT memory (current state)
On plan complete → Save to COLD memory (final deliverables)
```

**Never overwrite.** Always append with timestamp.

---

## CONTEXT INHERITANCE

Each step inherits relevant context from previous steps:

```
Step 1.2 gets:
  - All output from Step 1.1
  - Current plan state
  - Operator preferences observed so far
  - Any notes from previous steps

Step 2.1 gets:
  - All output from Phase 1
  - Phase 2-specific context
  - Operator decisions from checkpoints 1.x
```

**Rule:** Only pass data that is ACTUALLY needed. Don't dump everything.

---

## OPERATOR OVERVIEW

While the loop is running, the operator should always be able to ask:

### "What's happening?"
```
┌─ Status: [plan name]
├─ Progress: [N/M steps] [X%]
├─ Current: [step title] — [agent] — [what's happening]
├─ Next: [next step] — [agent]
├─ Last checkpoint: [last decision made]
└─ ETA: [estimated time to completion]
```

### "Show me what's done"
```
┌─ Completed Steps
├─ 1.1 [x] Identify 3 markets — RESEARCHER — complete
├─ 1.2 [x] Analyze market sizing — ANALYST — complete
├─ 1.3 [x] Rank markets — COORDINATOR — complete
└─ 1.4 [ ] Select target market — WAITING FOR YOU
```

### "Skip step 1.4"
- Skip the step, mark as CANCELLED
- Update all downstream steps that depended on it
- Re-plan if needed
- Present updated plan

### "Go deeper on step 2.1"
- Expand step details
- Show done criteria, dependencies, input/output
- Present for modification

---

## EMERGENCY PROTOCOLS

### Operator says "/stop"
```
┌─ Plan Paused
├─ Progress: [N/M steps] [X%]
├─ Last completed: [step]
├─ Next: [step that would run next]
└─ What now?
   1. Resume where we left off
   2. Modify the plan
   3. Cancel and archive
   What do you want?
```

### Operator says "/abort"
```
┌─ Plan Cancelled
├─ Archived: [plan ID]
├─ Progress at cancellation: [N/M steps] [X%]
├─ Deliverables produced: [list]
└─ Archived to: [memory location]
```

### Operator says "/emergency reset"
```
→ Clears all agent state (standard emergency protocol)
→ Plan state is preserved (not deleted)
→ Presents clean status
→ Waits for operator confirmation
```

---

## PERFORMANCE METRICS

Track these for every plan:

| Metric | Definition | Purpose |
|--------|-----------|---------|
| **Step completion rate** | % of steps that complete without blocking | Measures plan quality |
| **Average step time** | Time from assigned to complete | Estimates future plans |
| **Checkpoint frequency** | % of steps that are checkpoints | Measures how autonomous the plan is |
| **Block rate** | % of steps that hit BLOCKED state | Measures reliability |
| **Operator involvement** | Time/operator actions vs total time | Measures automation quality |

Log these for pattern learning — help PCA make better plans in the future.

---

*This is the operational loop. It runs continuously until the plan is done, cancelled, or blocked. Every state change is persisted. Every decision is logged.*
