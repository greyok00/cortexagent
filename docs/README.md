# OPERATOR — Universal Incubator

> A sole proprietor's autonomous AI control center. Employee + portfolio manager.
> Any idea can be seeded. Every seed grows independently, spawns new seeds, and evolves.
> Guardrails-first architecture — the LLM thinks independently within hard boundaries.

---

## What is this?

OPERATOR is the operational DNA for an AI that runs autonomously as an employee and portfolio manager for a sole proprietor. It's not a UI mockup — it's the **actual system that keeps a wild LLM from destroying anything** while giving it unlimited creative capacity.

The operator handles emails, invoices, and admin. OPERATOR handles **deep web analysis, project execution, strategic operations, and portfolio management** — autonomously.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ OPERATOR                                                        │
│                                                                 │
│  ┌──────────────┐     ┌──────────────────┐                      │
│  │ GUARDRAILS   │────→│ DECISION ENGINE  │                      │
│  │ (Hard limits)│     │ (Routing + Flow) │                      │
│  └──────────────┘     └──────────────────┘                      │
│       │                       │                                 │
│       ▼                       ▼                                 │
│  ┌──────────────────────────────────┐                           │
│  │     PORTFOLIO MANAGER            │                           │
│  │  (Portfolio strategy + oversight)│                           │
│  └──────────────┬───────────────────┘                           │
│         │         │         │         │                          │
│         ▼         ▼         ▼         ▼                          │
│    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                  │
│    │ SCRAPER│ │ANALYST │ │RESEARCH│ │ DEVOPS │                  │
│    └────────┘ └────────┘ └────────┘ └────────┘                  │
│    ┌────────┐ ┌────────┐ ┌────────┐                            │
│    │WRITER │ │MONITOR │ │COORDINATOR│                           │
│    └────────┘ └────────┘ └────────┘                            │
│                                                                 │
│  ┌──────────────────────────────────────────┐                   │
│  │           PROCESS CREATION AGENT         │                   │
│  │  (Goal → Seed → Plan → Execute → Spawn)  │                   │
│  └──────────────────────────────────────────┘                   │
│                                                                 │
│  ┌──────────────┐     ┌──────────────────┐                      │
│  │ MEMORY       │     │ PORTFOLIO VIEW     │                      │
│  │ (Hot/Warm/Cold)│   │ (Seeds, metrics,   │                      │
│  └──────────────┘     │  patterns, alerts)  │                      │
│                       └──────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
├── config/operator.yaml          # Runtime config (guardrails, agents, incubator)
├── prompts/
│   ├── system.md                 # Full system prompt (injected every session)
│   ├── agents.md                 # Agent role definitions (7 agents)
│   ├── guardrail_checker.md      # Pre-action validation (before EVERY tool call)
│   └── pca_agent.md              # Process Creation Agent — creates seeds, not just plans
├── docs/
│   ├── README.md                 # This file — overview
│   ├── operational_framework.md  # Complete framework reference (sections 1-15)
│   ├── execution_flow.md         # Pipeline definitions + state management
│   ├── execution_state_machine.md # Plan/step state machines + persistence
│   ├── pca_execution_protocol.md # PCA execution loop + verification
│   ├── decomposition_algorithm.md # 9-step goal-to-plan decomposition
│   ├── lifecycle_phases.md       # Full lifecycle: research → operations → growth
│   ├── incubator_architecture.md # Universal incubator: seeds, portfolio, PM, scale
│   └── pca_integration.md        # How PCA fits above COORDINATOR
├── mockups/                      # UI mockups (visual reference only)
│   ├── main.html                 # Operations overview
│   ├── project.html              # Project detail
│   └── research.html             # Deep analysis
└── docs/README.md                # This file
```

---

## Core Concepts

### Guardrails
Hard limits checked BEFORE every action. Three tiers:
- **Forbidden** — Never do (emails, payments, deletions, legal, external comms)
- **Conditional** — Ask operator first (deploys, long tasks, new integrations)
- **Autonomous** — OK to run (research, analysis, reporting, monitoring)

### Seeds
Any idea — business, creation, project, experiment, skill, relationship — can be seeded.
Each seed follows the same lifecycle: Seed → Sprout → Plant → Tree → Forest.
Seeds can spawn new seeds, die, pivot, merge, or be archived.

### Agents
Seven specialized roles that communicate through a task board:
- **COORDINATOR** — Orchestrates everything, never executes
- **SCRAPER** — Collects data from external sources
- **ANALYST** — Cross-references, validates, scores confidence
- **RESEARCHER** — Deep multi-source investigation
- **WRITER** — Generates structured reports (always reviewed)
- **DEVOPS** — Infrastructure ops (production changes require approval)
- **MONITOR** — System health (alert-only, cannot remediate)

### Portfolio Manager
Sits above the COORDINATOR. Handles:
- Portfolio strategy and seed prioritization
- Resource allocation across seeds
- Cross-seed learning and pattern sharing
- Seed spawning decisions
- Seed pruning, pivoting, and exit decisions

### Process Creation Agent (PCA)
Sits above the COORDINATOR. Handles:
- Goal decomposition → seed creation
- Plan execution with stage advancement
- Checkpoint and manual step handling
- Seed spawning opportunities

### Execution Pipelines
Five predefined flows for common task types:
- **Research** — Scrape → Verify → Analyze → Present
- **Analysis** — Load → Analyze → Rank → Report
- **Project** — Decompose → Execute → Report milestones
- **Quick Check** — Check → Report → Offer deeper dive
- **Clarification** — Ask → Wait → Proceed

### Memory
Three-tier system with strict loading rules:
- **Hot** — Per-platform, per-session (loaded on every task)
- **Warm** — Cross-platform, medium-term (loaded on relevance match)
- **Cold** — Permanent, structured (loaded only on explicit request)

---

## How It Works — Example

```
Operator: "Research NovaTech pricing"

1. PARSER → intent=research, target=NovaTech pricing
2. GUARDRAIL → read-only research = PROCEED
3. CONTEXT → Load related past research
4. DECOMPOSE → COORDINATOR creates:
   ├─ Task 1: Scrape NovaTech → assign: SCRAPER
   ├─ Task 2: Cross-reference → assign: ANALYST
   └─ Task 3: Deep dive → assign: RESEARCHER
5. EXECUTE → Agents run via TASK BOARD
6. AGGREGATE → COORDINATOR presents:

┌─ Task: NovaTech Pricing Research
├─ Sources: 5 (3 verified, 2 pending)
├─ Confidence: 87%
├─ Top findings:
│  1. [HIGH] NovaTech Pro at $49/mo — 34% below our tier (3 sources)
│  2. [HIGH] Feature gap: analytics module (2 sources verified)
│  3. [MEDIUM] Enterprise tier targeting SMB segment (1 source unverified)
├─ Gaps: 1 academic paper needs cross-reference
└─ Next: Proceed with competitive response plan? (yes/no)
```

---

## Example: Seed Creation

```
Operator: "I want to write a book about AI"

1. PARSER → intent=wide_goal, domain=creation
2. PCA ACTIVATES:
   ├─ Creates seed: "AI Book Project" (creation, seed stage)
   ├─ Decomposes into 6 phases, 24 steps
   ├─ Auto: 18 | Checkpoints: 4 | Manual: 2
   ├─ Phase 1: Research & Outline
   ├─ Phase 2: Chapter Writing
   ├─ Phase 3: Review & Edit
   ├─ Phase 4: Formatting & Design
   ├─ Phase 5: Publishing Setup
   └─ Phase 6: Launch & Distribution
3. PRESENT → Operator approves plan
4. EXECUTE → Agents work through phases
5. Checkpoints → Operator decides on direction, tone, publisher
6. Seed advances → Sprout when first chapter complete
   → Plant when book is written
   → Tree when published and selling
   → Forest when it spawns: audiobook, course, newsletter
```

---

## Emergency

If things go sideways:

```
Operator: /emergency_reset
→ Clears all agent state
→ Reloads core framework
→ Presents clean status
→ Waits for operator confirmation
```

---

## Key Design Decisions

1. **Guardrails before everything** — Every action is validated before execution
2. **Agent isolation** — Agents communicate through task board only, not directly
3. **Progressive disclosure** — Overview → details → raw data, never more than 2 clicks
4. **Transparency by default** — Show confidence, sources, gaps
5. **Speed by default** — <30s actions auto-execute; >30s get confirmation
6. **Never surprise** — The operator is always in the loop for anything that matters
7. **Domain agnostic** — Every seed is treated equally regardless of domain
8. **Unlimited scale** — Designed for infinite concurrent seeds, portfolio management
9. **Autonomy by maturity** — Seeds get more autonomy as they prove themselves
10. **Cross-pollination** — Seeds share learnings, patterns, infrastructure

---

## Status

**v1.0** — Universal incubator architecture complete. Ready for LLM integration.
