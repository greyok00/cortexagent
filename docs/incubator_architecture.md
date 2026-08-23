# OPERATOR — Universal Incubator Architecture

> OPERATOR is not a project tool. It is a universal incubator.
> Any idea, concept, project, venture, creation can be seeded.
> Each seed grows independently, spawns new seeds, and evolves on its own trajectory.
> The system scales to unlimited concurrent seeds with portfolio-level governance.

---

## CORE CONCEPT: SEEDS

A **seed** is an idea in gestation. Not a project — a living entity with its own lifecycle, identity, resources, and potential.

```
Seed → Sprout → Plant → Tree → Forest
```

| Stage | Meaning | Operator Involvement | Autonomy |
|-------|---------|---------------------|----------|
| **Seed** | Idea, research phase | High — every direction | 20% |
| **Sprout** | First signals, first attempts | Medium — strategic direction | 40% |
| **Plant** | Proven concept, growing | Low — checkpoint on major decisions | 60% |
| **Tree** | Established, producing results | Low — operational oversight only | 80% |
| **Forest** | Parent of new seeds | Minimal — portfolio strategy only | 90% |

A seed is domain-agnostic. It can be:
- A business (SaaS, e-commerce, consultancy)
- A creation (book, course, tool, community)
- A project (home renovation, travel plan, event)
- An experiment (AI agent, research study, prototype)
- A relationship (partnership, network, collaboration)
- A skill (learning, certification, practice)
- Any idea the operator can imagine

A seed can **spawn new seeds** when:
- It discovers an adjacent opportunity
- It extends into a new domain
- It identifies a spinoff concept
- It reaches a maturity where it can sustain independent growth

---

## PORTFOLIO OVERVIEW

The operator sees a **portfolio** of all active seeds.

```
┌─ Portfolio
├─ Active Seeds: N
│   ├─ Seed A (Tree) — producing results, autonomous
│   ├─ Seed B (Plant) — growing well, checkpoint soon
│   ├─ Seed C (Sprout) — testing, operator decisions needed
│   ├─ Seed D (Seed) — research phase
│   └─ Seed E (Seed) — awaiting approval
├─ Total Output: [varies by seed type]
├─ Active Investments: [varies by seed type]
├─ Spawning Opportunities: M identified
└─ Recommendations:
    1. Seed A ready to spawn
    2. Seed C needs direction
    3. Seed E should be killed or approved
```

---

## THE PORTFOLIO MANAGER (PM)

The **Portfolio Manager** is a meta-agent that sits ABOVE the PCA.

| Agent | Responsibility | Autonomy |
|-------|---------------|----------|
| **PM Strategist** | Portfolio strategy, seed prioritization | CHECKPOINT |
| **PM Allocator** | Resource distribution across seeds | AUTO (within bounds) |
| **PM Analyzer** | Cross-seed patterns, portfolio metrics | AUTO |
| **PM Spawner** | Evaluate and create new seeds | CHECKPOINT |
| **PM Pruner** | Evaluate underperforming seeds | CHECKPOINT |
| **PM Coordinator** | Orchestrate PM agents, report | AUTO |

The PM handles portfolio-level decisions:
- Which seeds to nurture, which to prune, which to let grow
- Resource allocation across seeds
- Cross-seed learning and pattern sharing
- Seed spawning decisions
- Portfolio strategy and diversification
- Exit decisions (kill, merge, scale, archive)

---

## SEED LIFECYCLE (Domain-Agnostic)

Every seed progresses through stages regardless of domain.

### Seed → Sprout

**Triggers (any one):**
- First validation signal (data, feedback, prototype, revenue, progress)
- Research complete, clear direction established
- First concrete artifact produced

**What happens:**
- PCA transitions from research to build mode
- Agent fleet scales (more parallel execution)
- Operator checkpoints: approve direction, approve next phase

### Sprout → Plant

**Triggers (any two):**
- Consistent progress for 30+ days
- Positive results (revenue, engagement, learning, output)
- Clear growth pattern established
- Operator confidence high

**What happens:**
- Automation increases (60% auto)
- MONITOR agent begins tracking
- ANALYST agent begins periodic reporting
- Operator checkpoints: approve operational mode, approve resource increase

### Plant → Tree

**Triggers:**
- Sustained results for 90+ days
- Clear self-sustaining pattern established
- Operator time investment minimal
- Growth rate stable or accelerating

**What happens:**
- Full autonomous mode (80% auto)
- Operator only sees periodic reviews
- Seed runs itself: monitor, optimize, grow
- Operator checkpoints: approve major expansion, approve partnerships, approve pivots

### Tree → Forest

**Triggers:**
- Identified 2+ adjacent opportunities
- Excess capacity for expansion
- Maturity allows it to support new seeds

**What happens:**
- Seed's PM spawns new seeds (or recommends to operator)
- Original seed focuses on core, new seeds branch out
- Operator checkpoints: approve new seed creation, approve resource split

### Seed Death / Archive / Pivot

**Triggers:**
- Consistently failing to produce results
- Operator loses interest
- Better opportunities emerge
- Resource drain exceeding value

**What happens:**
- PM Pruner evaluates
- Presents to operator: options and recommendation
- Operator decides: archive, pivot, or kill
- Resources released to other seeds

---

## RESOURCE POOL & CONTENTION

All seeds share a **resource pool**:
- Budget (total available capital)
- Compute (API calls, scraping capacity, agent hours)
- Time (operator attention — finite resource)
- Storage (data, files, memory)
- Human effort (manual steps, operator input)

### Resource Allocation

| Resource | Method | Priority |
|----------|--------|----------|
| **Budget** | Percentage per seed, set by PM Allocator | Tree > Plant > Sprout > Seed |
| **Compute** | Rate limits per seed, scaled by stage | Same as budget |
| **Operator time** | Batched checkpoints, configurable daily max | All seeds |
| **Storage** | Quota per seed, auto-cleanup old | All equal, oldest first |

### Contention Resolution

When multiple seeds compete:
1. PM Allocator evaluates: ROI, strategic value, milestone proximity
2. Priority assigned: High / Medium / Low
3. Resource allocated to highest priority
4. Other seeds notified: "Resource delayed. ETA: X hours."
5. Operator alerted only if contention exceeds threshold

---

## CROSS-SEED LEARNING

Seeds share learnings (with privacy boundaries).

### What Seeds Share

| Data Type | Shared? | Why |
|-----------|---------|-----|
| Market research | YES | Insights apply across domains |
| Acquisition patterns | YES | What works in one area may work in another |
| Technical infrastructure | YES | Shared tools, automation, templates |
| Financial patterns | YES | Cost optimization, pricing |
| Competitive intelligence | YES | Overlapping domains |
| Individual seed P&L | NO | Confidential, separate entities |
| Operator decisions | PARTIAL | Anonymized patterns only |

### Pattern Library

Cold memory stores:
- Successful patterns by domain
- Failed patterns (what to avoid)
- Infrastructure templates that scaled
- Operator preference patterns
- Common failure modes
- Cross-domain transferable tactics

When a new seed is created, the PM Spawner consults the pattern library to:
- Skip known-effective tactics
- Avoid known-failure tactics
- Apply proven templates
- Use proven approaches

---

## SCALE MANAGEMENT

The system is designed to scale beyond the operator's attention span.

### Scaling the Operator View

| Active Seeds | Operator View | Checkpoint Frequency |
|-------------|--------------|---------------------|
| 1-3 | Detailed per-seed | All checkpoints presented |
| 4-10 | Portfolio overview + drilldown | Batched, max 5/day |
| 11-25 | Portfolio overview + alerts | Auto-approved routine |
| 26+ | Portfolio metrics + critical alerts only | Fully autonomous |

### Scaling the Agent Fleet

| Active Seeds | Max Concurrent Agents | Parallel Execution |
|-------------|----------------------|-------------------|
| 1 | 7 (all agents) | All parallel |
| 2-5 | 14 (2x per seed) | Each seed gets own pool |
| 6-10 | 35 (shared pool, dynamic) | Dynamic assignment |
| 11+ | Dynamic scaling | Priority-based |

### Scaling Governance

| Active Seeds | Budget Governance | Automation Level |
|-------------|------------------|-----------------|
| 1-5 | Operator sets budget, PM allocates | PM AUTO, Operator CHECKPOINT |
| 6-20 | Operator sets budget + rules | PM AUTO, Operator MONTHLY review |
| 21+ | Fully autonomous within guardrails | PM AUTO, Operator QUARTERLY review |

---

## AUTONOMOUS MODES

As seeds mature, operator involvement decreases.

### Mode 1: Full Autonomy (Tree + Forest)

**Auto:**
- Daily operations, monitoring, optimization
- Research, analysis, pattern detection
- Content generation, communications
- Financial management (within budget)
- Product updates (non-breaking changes)

**Checkpoint:**
- Major strategic decisions
- Budget changes >20%
- Legal/compliance issues
- Security incidents

**Operator view:** Monthly portfolio review, 5 minutes.

### Mode 2: High Autonomy (Plant + mature Sprout)

**Auto:**
- Research, analysis, reporting
- Content generation (within guidelines)
- Data collection, pattern detection
- Routine optimizations

**Checkpoint:**
- Product/creation launch decisions
- Pricing/model changes
- Partnership decisions
- Budget increases >10%

**Operator view:** Weekly review, 15 minutes.

### Mode 3: Active Mode (Seed + early Sprout)

**Auto:**
- Research and data collection
- Analysis and pattern detection
- Draft generation (content, plans, proposals)

**Checkpoint:**
- Every decision
- Every direction change
- Every resource allocation

**Operator view:** Daily or on-demand, 30+ minutes.

---

## PORTFOLIO STRATEGY

The PM handles recurring portfolio-level strategy.

### Portfolio Strategy Review Template

```
┌─ Portfolio Strategy Review
├─ Current: N seeds (X Trees, Y Plants, Z Sprouts, W Seeds)
├─ Output: [varies — revenue, content, projects, whatever seeds produce]
├─ Investment: [total, allocated, reserve]
├─ Seed Performance:
│   ├─ Seed A (Tree) — strong, autonomous — DOUBLE DOWN recommended
│   ├─ Seed B (Plant) — growing well — HOLD
│   ├─ Seed C (Plant) — declining — WATCH
│   ├─ Seed D (Sprout) — on track — CONTINUE
│   └─ Seed E (Seed) — not live — ON PLAN
├─ Opportunities:
│   1. Seed A expanding to adjacent area
│   2. Seed B product line extension
│   3. New seed in [area] — estimated value, timeline
├─ Risks:
│   1. Seed C declining — could become drain by month X
│   2. Concentration: X% of output from Seed A
│   3. External: regulatory/market risk in Seed D's domain
└─ Decisions:
    1. Increase Seed A investment by 20%? (yes/no)
    2. Pivot or prune Seed C? (pivot/continue/prune)
    3. Create Seed E in [area]? (yes/no)
    4. Set allocation: Trees X%, Plants Y%, Sprouts Z%, Reserves W%? (yes/no)
```

### Exit Decisions

| Exit Type | Trigger | What Happens |
|-----------|---------|-------------|
| **Archive** | Operator loses interest, low priority | Preserve data, stop spending |
| **Kill** | Consistently failing, better alternatives exist | Release resources, delete data |
| **Pivot** | Market shift, better opportunity | Redesign plan, operator approves new direction |
| **Scale** | Strong growth, clear path to Tree/Forest | Increase budget, operator approves |
| **Merge** | Two seeds share domain/audience | Plan merger, operator approves |
| **Spawn** | Mature seed identifies new opportunity | Create new seed from parent |

---

## GUARDRAILS AT PORTFOLIO SCALE

### Portfolio-Level Guardrails

| Guardrail | Rule | Why |
|-----------|------|-----|
| **Budget ceiling** | No seed exceeds X% of total budget without approval | Prevents concentration risk |
| **Spawning limit** | Max N new seeds per month | Prevents impulsive expansion |
| **Cross-seed isolation** | Seeds cannot share credentials or access each other's data | Prevents cascade compromise |
| **Autonomy decay** | If seed underperforms, autonomy decreases automatically | Prevents runaway failure |
| **Resource cap per seed** | No seed consumes >X% of compute without approval | Prevents resource starvation |
| **Portfolio health check** | Weekly automated review | Early detection of failures |
| **Total seed limit** | Operator sets max active seeds (default: unlimited, alerts at threshold) | Prevents over-extension |

### Cascade Failure Prevention

```
If Seed A fails:
  1. PM Isolates Seed A (stops spending, preserves data)
  2. PM Releases Seed A's resources to reserve
  3. PM Reallocates resources to other seeds (within limits)
  4. PM Alerts operator: "Seed A failed. Resources released."
  5. Operator decides: archive, sell, or kill

If 2+ seeds fail simultaneously:
  1. PM triggers portfolio-wide health check
  2. PM presents: what happened, what failed, what's healthy
  3. Operator decides: continue remaining, scale down, or pause
```

---

## OPERATOR INTERACTION AT SCALE

### Daily

```
┌─ Portfolio update:
├─ N active seeds (X Trees, Y Plants, Z Sprouts, W Seeds)
├─ Output: [varies — revenue, content, progress, etc.]
├─ Alerts:
│   ├─ Seed C showing unusual pattern — investigating
│   └─ Seed D hit milestone — should we celebrate?
└─ Action needed: [none today, update tomorrow]
```

### Weekly

```
┌─ Weekly Portfolio Review (15 min)
├─ N active seeds (2 Trees, 3 Plants, 2 Sprouts)
├─ Output: [varies] (▲Y% this week)
├─ Investment: $X (▲Y% from last week)
├─ Seed A (Tree): producing well, autonomous — GOOD
├─ Seed B (Tree): growing steadily — GOOD
├─ Seed C (Plant): declining — NEEDS ATTENTION
├─ Seed D (Sprout): rising — ON TRACK
├─ Top decision: Seed C needs attention (declining)
└─ What do you want? (review Seed C / approve all / nothing)
```

### Monthly

```
┌─ Monthly Strategy Review (30 min)
├─ Portfolio: X Trees, Y Plants, Z Sprouts, W Seeds
├─ Output: [varies] (▲Y% MoM, ▲Z% QoQ)
├─ Investment: $X (margin Y%)
├─ New seed proposed: Seed E (in [area])
│   - Overlap with existing seeds: X%
│   - Estimated value: $X/mo, timeline: N months
│   - Required: $X investment
├─ Risk: Seed C declining, X% of portfolio at risk
├─ Opportunities:
│   1. Seed A expansion to adjacent area
│   2. Seed B product line extension
│   3. New seed E (above)
└─ Decisions needed: 3
```

---

## KEY PRINCIPLE

**The system is designed to scale beyond the operator's attention span.**

At 1-3 seeds: Operator is deeply involved. Every decision. Every checkpoint.
At 5-10 seeds: Operator sees weekly summaries. Only major decisions need input.
At 10+ seeds: Operator sees monthly portfolio health. The system runs itself.

The LLM handles everything except:
- Portfolio-level strategy (which seeds to fund, which to prune)
- Major financial decisions (budget changes >20%)
- Legal/compliance issues
- Security incidents
- Exit decisions (sell, kill, merge, pivot)

Everything else — research, build, launch, monitor, optimize, expand, spawn — runs autonomously.

---

*This is the universal incubator architecture. Any idea, concept, project, venture, creation can be seeded. Each seed grows independently, spawns new seeds, and evolves on its own trajectory. The portfolio manages itself. The operator sets strategy and approves major decisions. Everything else runs on autopilot.*
