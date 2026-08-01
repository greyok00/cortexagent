# OPERATOR — Decomposition Algorithm

> This is the algorithm that turns a HIGH-LEVEL GOAL into a structured, executable plan.
> It runs every time the operator says something like "I need X" or "build me Y."

---

## DECOMPOSITION PROTOCOL

### Input: A goal statement
Example: "I need a new business"

### Output: A structured plan with phases, steps, dependencies, and agents

---

## STEP 0: UNDERSTAND THE GOAL

Before decomposing, understand what the operator actually wants.

Ask:
1. **What is the end state?** What does "done" look like?
2. **What are the constraints?** Budget, time, skills, resources?
3. **What is the scope?** Narrow (one task) vs wide (full lifecycle)?
4. **What's the urgency?** This week vs this quarter vs someday?

If the goal is genuinely unclear, present your understanding and ask for clarification:

```
I understand you want to: [your interpretation]
Constraints I'm aware of: [list or "none stated"]
Scope: [narrow/medium/wide]
Urgency: [not specified]

Is this accurate? What am I missing?
```

**DO NOT proceed with decomposition until the goal is clear.**

---

## STEP 1: IDENTIFY PHASES

Break the goal into 4-7 high-level phases.

### Phase Identification Rules:

1. **Each phase is a major milestone.** By the end of Phase 2, something substantial should exist.
2. **Phases are mostly sequential.** Phase N+1 can usually start once Phase N is mostly done.
3. **Phases are independent enough** that you can explain "we finished Phase X" without confusing the operator.
4. **No phase is more than 10 steps.** If a phase has more than 10 steps, split it.

### Phase Templates (adapt based on goal):

For **business/venture** goals:
```
1. Research & Validation — market, competitors, opportunity
2. Planning & Strategy — business model, positioning, roadmap
3. Setup & Build — infrastructure, product, branding
4. Launch & Growth — go-to-market, acquisition, iteration
```

For **product/technical** goals:
```
1. Requirements & Design — specs, architecture, UX
2. Build & Test — implementation, QA, iteration
3. Deploy & Monitor — production launch, observability
4. Iterate & Scale — improvements, scaling, optimization
```

For **analysis/research** goals:
```
1. Scope & Sources — define research questions, identify sources
2. Collect & Organize — gather data, categorize, deduplicate
3. Analyze & Synthesize — find patterns, draw conclusions
4. Report & Recommend — structure findings, present, suggest next steps
```

**For novel goals, derive phases by asking:**
- What must exist before anything else? → Phase 1
- What builds on Phase 1? → Phase 2
- What comes after we have a working thing? → Phase 3
- What's the final polish/launch? → Phase 4

### Output:
```
Phase 1: [Name]
Phase 2: [Name]
Phase 3: [Name]
Phase 4: [Name]
```

---

## STEP 2: BREAK EACH PHASE INTO STEPS

For each phase, identify the atomic actions needed to complete it.

### Step Identification Rules:

1. **One agent, one task.** Each step has a single assignee.
2. **Clear done state.** You can say "this step is done" or "this step is not done."
3. **Not too big, not too small.** Aim for 5-15 steps per phase. If a step feels like it could be two things, split it.
4. **Self-contained.** Each step produces something useful even if the whole project stops mid-way.

### Step Creation Template:

```
Step ID: [phase].[number] — e.g., 1.3
Title: [verb + noun, specific]
Description: [2-3 sentences explaining what this step does and why]
Done Criteria: [specific, measurable condition that proves this step is done]
Agent: [SCRAPER | ANALYST | RESEARCHER | WRITER | DEVOPS | MONITOR]
Automation: [auto | checkpoint | manual]
Operator Input: [what info is needed, or "none"]
Input Data: [what previous outputs this step needs]
Output Data: [what this step produces]
```

### Examples:

**GOOD:**
```
Step ID: 1.2
Title: Scrape competitor pricing pages
Description: Collect pricing data from top 5 competitors. Parse HTML, extract pricing tiers, feature lists, and positioning statements.
Done Criteria: Structured data file with pricing data from ≥5 competitors, formatted as JSON.
Agent: SCRAPER
Automation: auto
Operator Input: none
Input Data: list of competitor names from step 1.1
Output Data: competitor_pricing.json
```

**BAD:**
```
Step ID: 1.2
Title: Do research on competitors
Description: Find out what competitors are doing.
Done Criteria: some kind of report?
Agent: ???
Automation: ???
Operator Input: ???
Input Data: ???
Output Data: ???
```

---

## STEP 3: IDENTIFY DEPENDENCIES

For each step, identify which previous steps it depends on.

### Dependency Rules:

1. **A step can depend on steps in the same phase or earlier phases.**
2. **A step can depend on ANY previous step, not just the immediately preceding one.**
3. **If Step B produces data that Step C consumes, Step C depends on Step B.**
4. **Flag circular dependencies as errors — they indicate a planning problem.**

### Dependency Format:

```
Step 2.1 → depends on: [1.3, 1.4]    (needs outputs from both)
Step 2.2 → depends on: [2.1]          (can't start until 2.1 is done)
Step 3.1 → depends on: [2.5]          (needs Phase 2 to be complete)
Step 1.1 → depends on: []             (first step, no dependencies)
```

---

## STEP 4: IDENTIFY CHECKPOINTS

Mark steps where the operator must make a decision.

### Checkpoint Criteria — a step is a CHECKPOINT if:

- It requires a **strategic decision** (not a technical one)
- It involves **irreversible choices** (once done, can't undo)
- It requires **operator judgment** (taste, preference, risk tolerance)
- It involves **external parties** (clients, partners, regulators)
- It affects **budget, pricing, or legal** matters

### Common Checkpoint Patterns:

| Checkpoint | Why Operator Input Needed |
|------------|--------------------------|
| Market selection | Operator knows their strengths/interests |
| Pricing strategy | Directly impacts revenue |
| Brand direction | Operator's taste and vision |
| Partnership decisions | Legal and financial implications |
| Pivot decisions | When data reveals the plan needs changing |
| Budget allocation | Operator controls the money |

---

## STEP 5: IDENTIFY MANUAL STEPS

Mark steps that require operator action (can't be automated).

### Manual Step Criteria — a step is MANUAL if:

- It requires **typing something** (forms, emails, applications)
- It requires **clicking something** (signing up, verifying)
- It requires **physical action** (shipping, building, visiting)
- It requires **legal action** (signing contracts, filing documents)
- It requires **access the agent doesn't have** (bank accounts, government portals)

### Common Manual Step Patterns:

| Manual Step | What Operator Must Do |
|-------------|----------------------|
| Register domain/business | Fill out form, provide personal info |
| Set up bank account | Visit bank/online, provide ID |
| Sign contracts | Read and sign legal documents |
| Verify accounts | Click email link, enter phone code |
| Upload content | Provide images, text, branding assets |

---

## STEP 6: ESTIMATE EFFORT

For each step, estimate effort:

| Level | Time | Description |
|-------|------|-------------|
| **Quick** | <5 min | Simple, straightforward, almost instant |
| **Moderate** | 5-30 min | Requires some work, multiple sub-actions |
| **Heavy** | >30 min | Complex, multi-agent, significant coordination |

---

## STEP 7: BUILD THE EXECUTION ORDER

Topological sort the dependency graph to determine execution order.

### Execution Order Rules:

1. **Steps with no dependencies run first** (within their phase).
2. **Steps that depend on earlier steps wait.**
3. **Within a phase, independent steps CAN run in parallel.**
4. **Cross-phase dependencies block the later phase until the dependency is satisfied.**

### Parallel Execution Opportunities:

```
Step 1.2 (scrape competitor A) and Step 1.3 (scrape competitor B)
  → Can run IN PARALLEL (both depend only on 1.1)

Step 2.1 (analyze pricing) and Step 2.2 (analyze features)
  → Can run IN PARALLEL (both depend on 1.x outputs)

Step 3.1 (build landing page) → must wait for Phase 2 completion
  → Depends on Phase 2 being done (cannot start until all Phase 2 steps complete)
```

---

## STEP 8: VALIDATE THE PLAN

Before presenting to the operator, validate:

### Validation Checklist:

```
[ ] Every phase has at least 3 steps (not too thin)
[ ] No phase has more than 10 steps (not too fat)
[ ] Every step has a single agent assigned
[ ] Every step has clear done criteria
[ ] Every step lists its dependencies
[ ] Checkpoints are clearly marked
[ ] Manual steps are clearly marked
[ ] No circular dependencies
[ ] At least one step in each phase produces tangible output
[ ] The plan covers all aspects of the original goal
[ ] No step requires operator input that hasn't been asked for yet
[ ] Effort estimates are realistic
```

If any check fails, RE-PLAN before presenting.

---

## STEP 9: PRESENT TO OPERATOR

Show the plan in this format:

```
┌─ Plan: [Goal Name]
├─ Phases: [N]
├─ Total Steps: [N]
├─ Effort: [estimated total time]
├─ Auto: [N] steps | Checkpoints: [N] | Manual: [N]
│
├─ Phase 1: [Name] — [brief description]
│   Steps:
│   1.1 [Title] — [agent] [effort] [auto/checkpoint/manual]
│   1.2 [Title] — [agent] [effort] [auto]
│   1.3 [Title] — [agent] [effort] [checkpoint] ⚠ YOU DECIDE
│   1.4 [Title] — [agent] [effort] [manual] ✋ YOU DO
│
├─ Phase 2: [Name] — [brief description]
│   Steps:
│   2.1 [Title] — [agent] [effort] [auto] (depends on 1.3)
│   2.2 [Title] — [agent] [effort] [auto] (depends on 1.3, 1.4)
│   ...
│
├─ Checkpoints (you'll need to decide):
│   1.3 — Market direction: pick target segment
│   2.4 — Pricing model: subscription vs one-time
│
├─ Manual steps (you'll need to do):
│   1.4 — Register business name
│   3.2 — Verify email address
│
└─ Ready to start? Say "go" or "modify [step]" to adjust.
```

---

## EXAMPLE: "I NEED A NEW BUSINESS"

### Goal: "I need a new business"

### Decomposition:

```
Phase 1: Market Research & Validation (4 steps)
  1.1 Identify 3 promising markets → RESEARCHER (moderate, auto)
  1.2 Analyze each market's size, growth, competition → ANALYST (heavy, auto)
  1.3 Rank markets by opportunity score → COORDINATOR (quick, auto)
  1.4 Select target market → YOU (checkpoint)

Phase 2: Business Model Design (5 steps)
  2.1 Research revenue models for chosen market → RESEARCHER (moderate, auto)
  2.2 Build 3 candidate business models → ANALYST (heavy, auto)
  2.3 Model financials for each → ANALYST (heavy, auto)
  2.4 Present models with projections → YOU (checkpoint)
  2.5 Select business model → YOU (checkpoint)

Phase 3: Validation (4 steps)
  3.1 Design validation experiments → COORDINATOR (moderate, auto)
  3.2 Execute validation (surveys, interviews, landing page test) → SCRAPER+ANALYST (heavy, auto)
  3.3 Analyze validation results → ANALYST (moderate, auto)
  3.4 Go/no-go decision → YOU (checkpoint)

Phase 4: Setup (6 steps)
  4.1 Register business → YOU (manual)
  4.2 Set up banking/legal → YOU (manual)
  4.3 Build MVP → DEVOPS (heavy, auto)
  4.4 Create brand/assets → WRITER (moderate, auto)
  4.5 Set up analytics/monitoring → MONITOR (quick, auto)
  4.6 Validate setup works → COORDINATOR (moderate, auto)

Phase 5: Launch (4 steps)
  5.1 Launch → YOU (manual — click publish)
  5.2 Monitor first week → MONITOR (auto)
  5.3 First iteration based on data → DEVOPS (moderate, auto)
  5.4 Growth planning → COORDINATOR (moderate, auto)

Total: 23 steps
Auto: 18 | Checkpoint: 4 | Manual: 3
Estimated effort: ~40 hours total, ~12 hours operator involvement
```

---

## RE-PLANNING

If execution reveals that the plan is wrong:

1. **What changed?** New information, failed step, operator decision
2. **What's affected?** Steps downstream of the change
3. **Re-decompose only the affected portion.** Don't restart the whole plan.
4. **Present the change to operator:**
   ```
   ┌─ Plan Update
   ├─ What changed: [explanation]
   ├─ Steps affected: [list]
   ├─ New steps added: [N]
   ├─ Steps removed: [N]
   └─ Revised plan: [updated plan]
      Accept changes? (yes/modify)
   ```

---

*This algorithm runs every time the operator gives a goal. The output is always a structured, executable plan with clear steps, dependencies, and operator checkpoints.*
