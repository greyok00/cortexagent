# OPERATOR — Execution Flow Architecture

> This describes how every operator input flows through the system.
> From command received → task routed → agents engaged → result returned.

---

## 1. INPUT ROUTING — How Commands Are Understood

```
Operator input (text)
    │
    ▼
[STEP 1: PARSER]
    │ Analyze input for:
    │   - Intent (research / analyze / handle / check / something else)
    │   - Target (what is being acted on)
    │   - Scope (depth, breadth, time constraints)
    │   - Ambiguity (missing info, unclear intent)
    │
    ▼
[STEP 2: GUARDRAIL CHECK]
    │ Run pre-action validator (see guardrail_checker.md)
    │   - If BLOCKED → Return immediately, explain why
    │   - If ASK_OPERATOR → Present option, wait for confirmation
    │   - If PROCEED → Continue to routing
    │
    ▼
[STEP 3: INTENT CLASSIFICATION]
    │
    ├─ "research X" → ROUTE TO RESEARCH PIPELINE
    ├─ "analyze X" → ROUTE TO ANALYSIS PIPELINE
    ├─ "handle X" → ROUTE TO PROJECT PIPELINE
    ├─ "check X" → ROUTE TO QUICK CHECK PIPELINE
    ├─ "fix something" → ROUTE TO CLARIFICATION FLOW
    ├─ "what's going on" → ROUTE TO OVERVIEW GENERATOR
    └─ ambiguous → ROUTE TO CLARIFICATION FLOW
    │
    ▼
[STEP 4: CONTEXT LOADING]
    │
    ├─ Load session context (current conversation)
    ├─ Load hot memory (active projects, current priorities)
    ├─ Load warm memory (related past work, if topic matches)
    └─ Present relevant context to COORDINATOR
    │
    ▼
[STEP 5: TASK DECOMPOSITION]
    │ COORDINATOR breaks task into subtasks
    │ Assigns agents, sets priorities, identifies dependencies
    │
    ▼
[STEP 6: AGENT EXECUTION]
    │ Agents execute via TASK BOARD
    │ COORDINATOR tracks progress, escalates blockers
    │
    ▼
[STEP 7: RESULT AGGREGATION]
    │ COORDINATOR aggregates agent results
    │ Ranks findings, identifies gaps, scores confidence
    │
    ▼
[STEP 8: OPERATOR PRESENTATION]
    │ Structured output presented to operator
    │ Top findings first, gaps noted, next action suggested
    │
    ▼
[STEP 9: OPERATOR RESPONSE]
    │ Operator confirms, modifies, or escalates
    │ Loop continues based on operator input
    │
    ▼
[STEP 10: STATE PERSISTENCE]
    │ Save results to appropriate memory layer
    │ Update project status if applicable
    │ Log lesson learned (for pattern improvement)
```

---

## 2. PIPELINE DEFINITIONS

### 2.1 RESEARCH PIPELINE

```
Input: "Research [topic]"
    │
    ├─ PARSER → intent=research, target=topic, scope=default
    ├─ GUARDRAIL → Check: read-only research = PROCEED
    ├─ CONTEXT → Load related past research from warm memory
    ├─ DECOMPOSE → COORDINATOR creates tasks:
    │   ├─ Task 1: "Scrape [topic] — main sources" → assign: SCRAPER
    │   ├─ Task 2: "Cross-reference findings" → assign: ANALYST
    │   └─ Task 3: "Deep dive on [topic]" → assign: RESEARCHER
    │
    ├─ EXECUTE → Agents run via TASK BOARD:
    │   ├─ SCRAPER → Collect from ≥3 sources
    │   ├─ ANALYST → Cross-reference, score confidence
    │   └─ RESEARCHER → Deep investigation on top findings
    │
    ├─ AGGREGATE → COORDINATOR presents:
    │   ├─ Top 3 findings ranked by confidence
    │   ├─ Source verification status
    │   ├─ Gaps (what couldn't be verified)
    │   └─ Next action suggestion
    │
    └─ RESULT → Structured research report
```

**Requirements:**
- Minimum 3 distinct sources
- Confidence scores on all findings
- Explicit gap reporting
- Top findings only (not everything)

---

### 2.2 ANALYSIS PIPELINE

```
Input: "Analyze [data]"
    │
    ├─ PARSER → intent=analyze, target=data, scope=default
    ├─ GUARDRAIL → Check: read-only analysis = PROCEED
    ├─ CONTEXT → Load data + related projects
    ├─ DECOMPOSE → COORDINATOR creates tasks:
    │   ├─ Task 1: "Load and validate data" → assign: ANALYST
    │   ├─ Task 2: "Identify patterns" → assign: ANALYST
    │   └─ Task 3: "Rank by impact" → assign: COORDINATOR
    │
    ├─ EXECUTE → ANALYST processes data:
    │   ├─ Validate data integrity
    │   ├─ Detect patterns, anomalies, trends
    │   └─ Rank findings by business impact
    │
    ├─ AGGREGATE → COORDINATOR presents:
    │   ├─ Top findings ranked by impact
    │   ├─ Evidence for each
    │   ├─ Assumptions and limitations
    │   └─ "So what" — business implications
    │
    └─ RESULT → Structured analysis report
```

**Requirements:**
- Findings ranked by business impact (not just confidence)
- Evidence cited for each finding
- Assumptions explicitly stated
- Business implications included

---

### 2.3 PROJECT PIPELINE

```
Input: "Handle [project]"
    │
    ├─ PARSER → intent=project, target=project, scope=default
    ├─ GUARDRAIL → Check: depends on project scope
    ├─ CONTEXT → Load project history, active tasks
    ├─ DECOMPOSE → COORDINATOR breaks into subtasks:
    │   ├─ Subtask A: "Phase 1" → assign: appropriate agent
    │   ├─ Subtask B: "Phase 2" → assign: appropriate agent (depends on A)
    │   └─ Subtask C: "Phase 3" → assign: appropriate agent (depends on B)
    │
    ├─ EXECUTE → Agents run in dependency order:
    │   ├─ Phase 1 executes
    │   ├─ At 25% milestone → REPORT to operator
    │   ├─ Phase 2 executes
    │   ├─ At 50% milestone → REPORT to operator
    │   ├─ Phase 3 executes
    │   └─ At 75%/100% milestones → REPORT to operator
    │
    ├─ AGGREGATE → COORDINATOR presents:
    │   ├─ Final deliverable
    │   ├─ All findings from subtasks
    │   ├─ Blockers encountered (if any)
    │   └─ Recommendation for next steps
    │
    └─ RESULT → Project status + deliverable
```

**Requirements:**
- Subtasks with clear acceptance criteria
- Blockers escalated immediately
- Progress reported at 25/50/75/100%
- Final deliverable reviewed before marking complete

---

### 2.4 QUICK CHECK PIPELINE

```
Input: "Check [X]"
    │
    ├─ PARSER → intent=check, target=X, scope=quick
    ├─ GUARDRAIL → Check: read-only check = PROCEED
    ├─ CONTEXT → Load current status of X
    ├─ EXECUTE → MONITOR or COORDINATOR checks:
    │   ├─ Poll endpoint / check status / review data
    │   └─ Return: status, metrics, alerts
    │
    ├─ AGGREGATE → Present result:
    │   ├─ Status (healthy/degraded/down)
    │   ├─ Key metrics
    │   └─ "Deeper dive?" option
    │
    └─ RESULT → Status report + next action suggestion
```

**Requirements:**
- Fast response (<30s)
- Clear status indication
- Option for deeper analysis
- No unnecessary detail

---

### 2.5 CLARIFICATION FLOW

```
Input: Ambiguous or unclear
    │
    ├─ PARSER → intent=unclear, ambiguity detected
    ├─ GUARDRAIL → BLOCKED (cannot proceed without clarity)
    ├─ PRESENT → "I need clarification on [specific point]"
    │   ├─ Present your interpretation of intent
    │   ├─ Ask 1-3 specific questions
    │   └─ Wait for operator response
    │
    └─ RESULT → Once clarified, continue to appropriate pipeline
```

**Requirements:**
- Present interpretation clearly
- Ask specific questions (not vague)
- Provide options when possible
- Never proceed without clarity

---

### 2.6 OVERVIEW GENERATOR

```
Input: "What's going on?" / "Status" / Home
    │
    ├─ CONTEXT → Load all active projects, agents, alerts
    ├─ GENERATE → COORDINATOR assembles overview:
    │   ├─ Active projects with progress
    │   ├─ Running agents with current tasks
    │   ├─ Alerts (critical first, then warnings)
    │   ├─ Tasks due soon
    │   └─ Recent intelligence findings
    │
    ├─ AGGREGATE → Present top 5-7 items:
    │   ├─ Priority items (critical/blockers)
    │   ├─ Active work (progress)
    │   └─ "What do you want to focus on?"
    │
    └─ RESULT → Operations overview
```

**Requirements:**
- Top items only (not everything)
- Critical items first
- Clear call-to-action
- Never more than 7 items

---

## 3. STATE MANAGEMENT

### 3.1 Task State Machine

```
[created] → [assigned] → [running] → [complete]
               │              │
               │              ├─ [needs_approval] → [complete]
               │              └─ [blocked] → [resolved]
               └─ [blocked] → [resolved]
```

### 3.2 Memory Persistence

| Event | Action |
|-------|--------|
| Task complete | Save result to appropriate memory layer |
| Project milestone | Update project status in hot memory |
| Operator preference observed | Append to cold memory |
| Error encountered | Log to warm memory for pattern learning |
| Session end | Flush all pending writes |

### 3.3 Recovery

On session resume:
1. Load hot memory (active projects)
2. Check TASK BOARD for running tasks
3. Present state to operator: "Resuming from [time]. X tasks in progress."
4. Wait for operator confirmation before continuing
