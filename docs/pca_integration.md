# OPERATOR — PCA Integration Guide

> How the Process Creation Agent (PCA) integrates with the existing OPERATOR system.
> PCA is a specialized agent that sits ABOVE the regular agent orchestration.

---

## ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                                                       │
│  OPERATOR (You are OPERATOR...)                       │
│                                                       │
│  ┌───────────────────────────────────────┐            │
│  │                                       │            │
│  │  PCA (Process Creation Agent)         │            │
│  │  "I need a new business"              │            │
│  │         │                              │            │
│  │         ▼                              │            │
│  │  Plan: 5 phases, 23 steps             │            │
│  │         │                              │            │
│  │         ▼                              │            │
│  │  Execution loop                       │            │
│  │         │                              │            │
│  └─────────┼─────────────────────────────┘            │
│            │                                           │
│            ▼                                           │
│  ┌───────────────────────────────────────┐            │
│  │                                       │            │
│  │  COORDINATOR (Task routing)           │            │
│  │         │                              │            │
│  │    ┌────┼────────┬─────┬─────┬────┐   │            │
│  │    ▼    ▼        ▼     ▼     ▼     ▼   │            │
│  │ SCRAPER ANALYST RESEARCH WRITER DEVOPS│            │
│  └───────────────────────────────────────┘            │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## PCA VS REGULAR AGENTS

| Aspect | Regular Agents | PCA |
|--------|---------------|-----|
| **Scope** | Single task/domain | Cross-domain, multi-phase |
| **Duration** | Minutes to hours | Hours to weeks |
| **Decision level** | Tactical (how to do X) | Strategic (what is X, why, what next) |
| **Operator input** | Only on errors/escalation | On checkpoints (planned pauses) |
| **State** | Task-level | Plan-level (persistent) |
| **Autonomy** | High within task | High within plan |

---

## WHEN TO USE PCA

| Operator Input | Route To |
|---------------|----------|
| "Research X" | Regular research pipeline |
| "Analyze X" | Regular analysis pipeline |
| "Handle project X" | Regular project pipeline |
| "Check X" | Quick check pipeline |
| **"I need a new business"** | **PCA** |
| **"Build me a SaaS"** | **PCA** |
| **"Launch an e-commerce store"** | **PCA** |
| **"Enter the Japanese market"** | **PCA** |
| **"Rebrand everything"** | **PCA** |

**Rule of thumb:** If the goal has 5+ steps and spans multiple domains (research, build, launch, iterate), it's a PCA task.

---

## INTEGRATION POINTS

### 1. System Prompt Extension

When PCA mode is active, append to the base system prompt:

```
[SYSTEM: PCA MODE ACTIVE]
You are now operating as the Process Creation Agent (PCA).
You are decomposing goals into executable plans, then orchestrating their completion.
See: prompts/pca_agent.md, docs/decomposition_algorithm.md, docs/pca_execution_protocol.md
```

### 2. Agent Coordination

The PCA **uses** COORDINATOR as a sub-agent. It doesn't replace it.

```
PCA: "Break down goal and assign to agents"
  → COORDINATOR: "Creating plan with 23 steps across 5 phases"
  → PCA: "Presenting plan to operator for review"
  → Operator: "go"
  → PCA: "Starting Phase 1, Step 1"
  → COORDINATOR: "Assigning step 1.1 to RESEARCHER"
  → RESEARCHER: "Working on step 1.1"
  → RESEARCHER: "Complete — markets.json"
  → PCA: "Verified, marking complete. Advancing to step 1.2"
```

### 3. State Management

PCA plans are stored in a separate namespace from regular tasks:

```json
// Regular task
{
  "type": "task",
  "id": "task-001",
  "title": "Research NovaTech pricing",
  "status": "running",
  "agent": "SCRAPER"
}

// PCA plan
{
  "type": "plan",
  "id": "plan-001",
  "goal": "I need a new business",
  "status": "active",
  "phases": [...],
  "steps": [...]
}
```

### 4. Memory Integration

| Event | Memory Layer | Content |
|-------|-------------|---------|
| Plan created | HOT | Current plan state |
| Step completed | HOT | Step results + context |
| Plan completed | COLD | Final deliverables |
| Checkpoint decision | HOT | Decision + reasoning |
| Error/recovery | HOT | What failed + what was tried |

### 5. Guardrail Integration

PCA steps are subject to the SAME guardrails as regular agent tasks:

```
PCA creates step → COORDINATOR routes step
  → Guardrail check runs (same as any other step)
  → If forbidden: BLOCKED
  → If conditional: ASK OPERATOR
  → If autonomous: PROCEED
```

**PCA itself is not exempt from guardrails.** If a step in the plan involves sending emails, the guardrail checker blocks it.

---

## EXAMPLE FLOW

### Operator: "I need a new business"

```
1. PCA receives input
2. PCA runs decomposition algorithm (docs/decomposition_algorithm.md)
3. PCA builds plan: 5 phases, 23 steps
4. PCA presents plan to operator
5. Operator says "go"
6. PCA enters execution loop (docs/pca_execution_protocol.md)
7. PCA assigns step 1.1 to COORDINATOR
8. COORDINATOR assigns to RESEARCHER
9. RESEARCHER works on step 1.1
10. RESEARCHER returns result
11. PCA verifies result against done criteria
12. PCA advances to step 1.2
13. ... continues until step 23 is complete ...
14. PCA presents final summary with deliverables
```

### Operator: "Show me what's done" (mid-execution)

```
PCA presents current progress:
┌─ Progress: New Business
├─ Overall: 8/23 steps — 35%
├─ Phase 1: Market Research — 4/4 done ✅
├─ Phase 2: Business Model — 2/5 done 🔄
├─ Current: 2.2 Build 3 candidate models — ANALYST working
├─ Next: 2.3 Model financials — ANALYST
├─ Checkpoints: 2 of 4 completed
└─ ETA: ~6 hours remaining
```

### Operator: "Skip market analysis, go to step 2.2"

```
PCA:
┌─ Plan Update
├─ Skipping Phase 1 (4 steps)
├─ Step 2.1 requires market data from 1.3
├─ Since 1.3 is skipped, 2.1 is BLOCKED
├─ Auto-skipping 2.1
├─ Starting step 2.2 (no longer depends on 2.1)
└─ Resume? (yes)
```

---

## LIMITATIONS

### What PCA can't do:

1. **Execute manual steps remotely** — if a step requires operator to sign a document, PCA can't do it.
2. **Make strategic decisions** — PCA presents options, operator decides.
3. **Predict the future** — plans are based on available information. If new info changes the landscape, re-plan.
4. **Guarantee success** — PCA can execute perfectly and the business idea might still fail. That's not a PCA failure.

### When PCA should NOT be used:

- Simple, single-domain tasks → use regular pipelines
- Operator wants to explore, not execute → use research pipeline
- Operator is unsure what they want → use clarification flow
- Task is purely creative → use WRITER agent directly

---

*PCA extends OPERATOR from "do this task" to "help me build this thing." It's the difference between an assistant and an employee.*
