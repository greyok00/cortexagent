# OPERATOR — AI Control Center

> A sole proprietor's autonomous AI control center. Employee + assistant.
> Guardrails-first architecture — the LLM thinks independently within hard boundaries.

---

## What is this?

OPERATOR is the operational DNA for an AI that runs autonomously as an employee for a sole proprietor. It's not a UI mockup — it's the **actual system that keeps a wild LLM from destroying everything**.

The operator handles emails, invoices, and admin. OPERATOR handles **deep web analysis, project execution, and strategic operations** — autonomously.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ OPERATOR                                             │
│                                                      │
│  ┌──────────────┐     ┌──────────────────┐          │
│  │ GUARDRAILS   │────→│ DECISION ENGINE  │          │
│  │ (Hard limits)│     │ (Routing + Flow) │          │
│  └──────────────┘     └──────────────────┘          │
│       │                       │                      │
│       ▼                       ▼                      │
│  ┌──────────────────────────────────┐               │
│  │         COORDINATOR              │               │
│  │  (Task decomposition + routing)  │               │
│  └──────────────┬───────────────────┘               │
│         │         │         │         │              │
│         ▼         ▼         ▼         ▼              │
│    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │
│    │SCRAPER │ │ANALYST │ │RESEARCH │ │ DEVOPS │      │
│    └────────┘ └────────┘ └────────┘ └────────┘      │
│    ┌────────┐ ┌────────┐ ┌────────┐                 │
│    │WRITER │ │MONITOR │ │(future)│                  │
│    └────────┘ └────────┘ └────────┘                 │
│                                                      │
│  ┌──────────────┐     ┌──────────────────┐          │
│  │ MEMORY       │     │ COMMAND BAR      │          │
│  │ (Hot/Warm/Cold)│   │ (⌘ prompt)       │          │
│  └──────────────┘     └──────────────────┘          │
└─────────────────────────────────────────────────────┘
```

---

## File Structure

```
├── config/operator.yaml          # Runtime configuration
├── prompts/
│   ├── system.md                 # Full system prompt (injected every session)
│   ├── agents.md                 # Agent role definitions (7 agents)
│   └── guardrail_checker.md      # Pre-action validation (before EVERY tool call)
├── docs/
│   ├── operational_framework.md  # Complete framework reference
│   └── execution_flow.md         # Pipeline definitions + state management
├── mockups/                      # UI mockups (visual reference only)
│   ├── main.html                 # Operations overview
│   ├── project.html              # Project detail
│   └── research.html             # Deep analysis
└── docs/README.md                # This file
```

---

## Core Concepts

### Guardrails
Hard limits that are checked BEFORE every action. Three tiers:
- **Forbidden** — Never do without explicit approval (emails, payments, deletions)
- **Conditional** — Ask operator first (deploys, long tasks, new integrations)
- **Autonomous** — OK to run (research, analysis, reporting, monitoring)

### Agents
Seven specialized roles that communicate through a task board:
- **COORDINATOR** — Orchestrates everything, never executes
- **SCRAPER** — Collects data from external sources
- **ANALYST** — Cross-references, validates, scores confidence
- **RESEARCHER** — Deep multi-source investigation
- **WRITER** — Generates structured reports (always reviewed)
- **DEVOPS** — Infrastructure ops (production changes require approval)
- **MONITOR** — System health (alert-only, cannot remediate)

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

---

## Status

**v1.0** — Operational framework complete. Ready for LLM integration.
