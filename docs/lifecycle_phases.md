# OPERATOR — Full Lifecycle Phases

> The PCA decomposes goals into phases spanning research through ongoing management.
> Research is the easy part — read-only, safe, reversible.
> The real system gets tested in practical execution and managerial phases where decisions cost money, require judgment, and cannot be reversed.
> This document defines every phase, what agents do, what guardrails trigger, and where the operator must take the wheel.

---

## OVERVIEW: PHASE RISK LADDER

```
Phase 1: Research & Validation    — LOW RISK   — Read-only, reversible, no money involved
Phase 2: Business Model Design    — LOW RISK   — Analysis only, operator decides
Phase 3: Validation Experiments   — LOW-MED    — Small tests, but real user-facing
Phase 4: Setup & Build            — MEDIUM     — Infrastructure, legal, branding
Phase 5: Launch                   — MEDIUM-HIGH — Live to public, real transactions
Phase 6: Operations & Management  — HIGH       — Daily decisions, financial management, team
Phase 7: Growth & Adaptation      — HIGH       — Scaling, pivots, new markets, acquisitions
```

As risk increases, the PCA increases checkpoint frequency and decreases autonomy:
- Phase 1-2: 20% checkpoint, 80% auto
- Phase 3-4: 40% checkpoint, 60% auto
- Phase 5-6: 60% checkpoint, 40% auto
- Phase 7: 70% checkpoint, 30% auto

---

## PHASE 1: RESEARCH & VALIDATION (Low Risk)

**What happens:** Market research, competitor analysis, opportunity assessment.
**Agents involved:** RESEARCHER, SCRAPER, ANALYST
**Guardrails:** Almost entirely AUTONOMOUS. Read-only actions. No data modification.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 1.1 | RESEARCHER | AUTO | Identify 3-5 promising markets | PASS — read-only research |
| 1.2 | SCRAPER | AUTO | Scrape competitor data, pricing, features | PASS — read-only scraping |
| 1.3 | ANALYST | AUTO | Cross-reference, confidence score, pattern detect | PASS — read-only analysis |
| 1.4 | COORDINATOR | AUTO | Rank markets by opportunity score | PASS — internal analysis |
| **1.5** | **YOU** | **CHECKPOINT** | **Select target market** | **Operator judgment** |

**Why this is safe:** Every action is read-only. The LLM cannot modify data, spend money, or take irreversible actions. The only "decision" is marking a market as "interesting" — which has zero cost.

**Guardrail check results:** Every single step in Phase 1 should pass all 6 guardrail checks as PROCEED. If any step is flagged, the step scope is too wide — narrow it.

---

## PHASE 2: BUSINESS MODEL DESIGN (Low Risk)

**What happens:** Design revenue models, financial projections, positioning.
**Agents involved:** RESEARCHER, ANALYST, WRITER
**Guardrails:** Still read-only analysis. The WRITER output requires review before any external use.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 2.1 | RESEARCHER | AUTO | Research revenue models for chosen market | PASS |
| 2.2 | ANALYST | AUTO | Build 3 candidate business models | PASS |
| 2.3 | ANALYST | AUTO | Model financials for each (projections, break-even) | PASS |
| 2.4 | WRITER | AUTO | Generate business plan document (unreviewed) | PASS — flagged as unreviewed |
| **2.5** | **YOU** | **CHECKPOINT** | **Review models, select business model** | **Operator judgment** |

**Why this is safe:** Still analysis-only. No money changes hands. No external communications. The WRITER output is marked "reviewed: false" and cannot be sent externally until operator confirms.

**Checkpoint at 2.5 is critical:** This is where you choose the business model. The LLM presents options with pros/cons/recommendation but does NOT decide for you.

---

## PHASE 3: VALIDATION EXPERIMENTS (Low-Medium Risk)

**What happens:** Test the business model with real signals — landing page, surveys, interviews.
**Agents involved:** COORDINATOR, SCRAPER, ANALYST, DEVOPS
**Guardrails:** First phase where real-world action is needed. Some steps require operator approval.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 3.1 | COORDINATOR | AUTO | Design validation experiment plan | PASS — internal planning |
| 3.2 | DEVOPS | CHECKPOINT | Deploy landing page test | **CONDITIONAL — must approve** |
| 3.3 | SCRAPER | AUTO | Collect survey/landing page data | PASS — read-only collection |
| 3.4 | ANALYST | AUTO | Analyze validation results | PASS |
| **3.5** | **YOU** | **CHECKPOINT** | **Go/no-go decision** | **Operator judgment** |

**Why this is medium risk:** The landing page is live to the public. It collects real data. If the landing page has incorrect legal terms, it could create liability. The DEVOPS agent requires operator approval before deploying.

**Key guardrail trigger:** `production_deploy` is CONDITIONAL. The COORDINATOR must ask: "Deploying a test landing page at [URL] to collect validation data. This will be up for [X days]. Approve?" Operator must explicitly say yes.

---

## PHASE 4: SETUP & BUILD (Medium Risk)

**What happens:** Register business, set up legal, build MVP, create branding.
**Agents involved:** ALL agents
**Guardrails:** Significant increase in risk. Legal and financial actions are FORBIDDEN to the LLM. The operator must perform manual steps.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 4.1 | RESEARCHER | AUTO | Research business registration requirements | PASS |
| **4.2** | **YOU** | **MANUAL** | **Register business entity** | **Operator action required** |
| **4.3** | **YOU** | **MANUAL** | **Set up business bank account** | **Operator action required** |
| 4.4 | DEVOPS | CHECKPOINT | Set up development environment | **CONDITIONAL — infrastructure** |
| 4.5 | DEVOPS | AUTO | Build MVP (development, testing) | PASS — dev environment only |
| 4.6 | WRITER | AUTO | Generate brand assets, copy (unreviewed) | PASS — flagged unreviewed |
| 4.7 | MONITOR | AUTO | Set up analytics and monitoring | **CONDITIONAL — new API integrations** |
| 4.8 | COORDINATOR | AUTO | Validate setup works | PASS — verification |
| **4.9** | **YOU** | **CHECKPOINT** | **Approve MVP before launch** | **Operator judgment** |

**Why this is medium risk:**
- Legal/financial steps (4.2, 4.3) are MANUAL — operator does them
- Infrastructure setup (4.4, 4.7) is CONDITIONAL — requires approval
- The LLM never touches legal documents, bank accounts, or production systems
- Development happens in a non-production environment

**Critical guardrails enforced:**
- `sign_contracts` → FORBIDDEN — LLM never signs anything
- `change_production_configs` → FORBIDDEN — LLM never touches production
- `production_deploy` → CONDITIONAL — always ask operator
- `new_api_integration` → CONDITIONAL — always ask operator

---

## PHASE 5: LAUNCH (Medium-High Risk)

**What happens:** Go live to the public. First transactions. First real users.
**Agents involved:** DEVOPS, MONITOR, COORDINATOR
**Guardrails:** Highest risk phase in the original plan. Live system, real money, public-facing.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 5.1 | COORDINATOR | CHECKPOINT | Present launch checklist | **CONDITIONAL — operator approves go-live** |
| **5.2** | **YOU** | **MANUAL** | **Click publish / go live** | **Operator action** |
| 5.3 | MONITOR | AUTO | Monitor first 48 hours (health, errors, performance) | PASS — read-only monitoring |
| 5.4 | DEVOPS | CHECKPOINT | Apply first fixes if needed | **CONDITIONAL — production changes** |
| **5.5** | **YOU** | **CHECKPOINT** | **First-week review: go, adjust, or pause** | **Operator judgment** |

**Why this is high risk:**
- The system is now live. Bugs affect real users.
- Transactions are processing. Money is changing hands.
- Any deployment error can damage customer trust.

**Guardrail enforcement:**
- All production changes require explicit operator approval (CONDITIONAL)
- The MONITOR alerts on anomalies but NEVER attempts remediation (alert-only)
- The DEVOPS agent auto-rollback on deployment failure, then reports

**The LLM's role during launch:** Monitor, report, recommend. NOT act. The operator makes the go/adjust/pause decision.

---

## PHASE 6: OPERATIONS & MANAGEMENT (High Risk) — THE MISSING PHASE

**What happens:** Day-to-day running of the business. Financial tracking, customer management, team coordination, strategic decisions, compliance, resource allocation.
**Agents involved:** ALL agents
**Guardrails:** Most restrictive. The LLM is restricted to READ-ONLY analysis and RECOMMENDATIONS. All operational decisions require operator approval.

### Phase Steps:

#### 6.1 Financial Operations
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 6.1.1 | ANALYST | AUTO | Aggregate revenue, expenses, profit data | PASS |
| 6.1.2 | ANALYST | AUTO | Generate financial report (cash flow, P&L, run rate) | PASS |
| **6.1.3** | **YOU** | **CHECKPOINT** | **Review financials, approve budget allocation** | **Operator judgment** |
| **6.1.4** | **YOU** | **MANUAL** | **Approve expenses, adjust pricing** | **Operator action** |

**Why CHECKPOINT:** Financial decisions directly impact revenue and sustainability. The LLM can analyze and recommend but cannot approve spending or change pricing.

**Guardrails:**
- `process_payments` → FORBIDDEN
- `change_pricing` → FORBIDDEN
- `sign_contracts` → FORBIDDEN

#### 6.2 Customer & Market Operations
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 6.2.1 | SCRAPER | AUTO | Monitor customer feedback, reviews, support tickets | PASS |
| 6.2.2 | ANALYST | AUTO | Analyze customer sentiment, churn risk, feature requests | PASS |
| 6.2.3 | WRITER | AUTO | Draft responses, announcements (unreviewed) | PASS — flagged unreviewed |
| **6.2.4** | **YOU** | **CHECKPOINT** | **Approve all external communications** | **Operator judgment** |

**Why CHECKPOINT:** External communications (emails, posts, announcements) are FORBIDDEN to the LLM. The WRITER can draft, but the operator must review and send.

**Guardrails:**
- `send_emails` → FORBIDDEN
- `send_messages` → FORBIDDEN
- `post_content` → FORBIDDEN

#### 6.3 Compliance & Legal
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 6.3.1 | RESEARCHER | AUTO | Check regulatory requirements, compliance status | PASS |
| 6.3.2 | ANALYST | AUTO | Audit data handling, privacy, terms of service | PASS |
| **6.3.3** | **YOU** | **CHECKPOINT** | **Approve legal/privacy changes** | **Operator judgment** |
| **6.3.4** | **YOU** | **MANUAL** | **File compliance documents, sign legal docs** | **Operator action** |

**Guardrails:**
- `modify_legal_documents` → FORBIDDEN
- `sign_contracts` → FORBIDDEN
- `agree_to_terms` → FORBIDDEN

#### 6.4 Resource & Team Management
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 6.4.1 | ANALYST | AUTO | Analyze workload, bottlenecks, resource allocation | PASS |
| 6.4.2 | COORDINATOR | AUTO | Generate resource recommendations | PASS |
| **6.4.3** | **YOU** | **CHECKPOINT** | **Approve hiring, partnerships, resource shifts** | **Operator judgment** |
| **6.4.4** | **YOU** | **MANUAL** | **Execute hires, contracts, partnerships** | **Operator action** |

**Guardrails:**
- `sign_contracts` → FORBIDDEN
- `change_production_configs` → FORBIDDEN (for infrastructure changes)

#### 6.5 Strategic Decision-Making
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 6.5.1 | RESEARCHER | AUTO | Research market shifts, competitor moves, trends | PASS |
| 6.5.2 | ANALYST | AUTO | Analyze impact on business, generate scenarios | PASS |
| **6.5.3** | **YOU** | **CHECKPOINT** | **Strategic decision: pivot, double-down, expand, hold** | **Operator judgment** |

**Why CHECKPOINT:** Strategic decisions define the business direction. The LLM can present data and scenarios but never decides for you.

---

## PHASE 7: GROWTH & ADAPTATION (High Risk)

**What happens:** Scaling, entering new markets, product lines, acquisitions, pivots.
**Agents involved:** ALL agents
**Guardrails:** Most restrictive. These are irreversible, high-stakes decisions. Maximum checkpoint coverage.

### Phase Steps:
| Step | Agent | Auto/CP | What Happens | Guardrail Result |
|------|-------|---------|--------------|-----------------|
| 7.1 | RESEARCHER | AUTO | Research growth opportunities, new markets | PASS |
| 7.2 | ANALYST | AUTO | Model growth scenarios, resource needs, risks | PASS |
| 7.3 | DEVOPS | CHECKPOINT | Scale infrastructure | **CONDITIONAL — architecture change** |
| **7.4** | **YOU** | **CHECKPOINT** | **Approve growth strategy: which markets, which products** | **Operator judgment** |
| 7.5 | DEVOPS | CHECKPOINT | Implement scaling changes | **CONDITIONAL — production changes** |
| 7.6 | MONITOR | AUTO | Monitor scale-up health | PASS |
| **7.7** | **YOU** | **CHECKPOINT** | **Post-scale review: did scaling work?** | **Operator judgment** |

**Why maximum checkpoints:** Growth decisions are irreversible (mostly), involve significant capital, and define the business trajectory. The LLM provides data and analysis — you make the decisions.

**Critical guardrails:**
- `architecture_change` → CONDITIONAL
- `production_deploy` → CONDITIONAL
- `new_api_integration` → CONDITIONAL
- All `sign_contracts` → FORBIDDEN

---

## COMPLETE LIFECYCLE PLAN EXAMPLE

When the operator says "I need a new business," the PCA generates:

```
┌─ Plan: New Business
├─ Total Steps: 65
├─ Auto: 38 | Checkpoints: 18 | Manual: 9
├─ Estimated: ~120 hours total, ~40 hours operator involvement
├─ Duration: ~8-12 weeks (depending on speed)
│
├─ Phase 1: Research & Validation (4 steps)
│   1.1 Identify promising markets → RESEARCHER (auto)
│   1.2 Scrape competitor data → SCRAPER (auto)
│   1.3 Analyze and rank → ANALYST (auto)
│   1.4 Select market → YOU (checkpoint)
│
├─ Phase 2: Business Model Design (5 steps)
│   2.1 Research revenue models → RESEARCHER (auto)
│   2.2 Build 3 models → ANALYST (auto)
│   2.3 Financial projections → ANALYST (auto)
│   2.4 Generate plan doc → WRITER (auto, unreviewed)
│   2.5 Select model → YOU (checkpoint)
│
├─ Phase 3: Validation Experiments (5 steps)
│   3.1 Design experiments → COORDINATOR (auto)
│   3.2 Deploy landing page → DEVOPS (checkpoint)
│   3.3 Collect data → SCRAPER (auto)
│   3.4 Analyze results → ANALYST (auto)
│   3.5 Go/no-go → YOU (checkpoint)
│
├─ Phase 4: Setup & Build (9 steps)
│   4.1 Research registration → RESEARCHER (auto)
│   4.2 Register business → YOU (manual)
│   4.3 Set up banking → YOU (manual)
│   4.4 Dev environment → DEVOPS (checkpoint)
│   4.5 Build MVP → DEVOPS (auto)
│   4.6 Brand assets → WRITER (auto, unreviewed)
│   4.7 Analytics → MONITOR (checkpoint)
│   4.8 Validate setup → COORDINATOR (auto)
│   4.9 Approve MVP → YOU (checkpoint)
│
├─ Phase 5: Launch (5 steps)
│   5.1 Launch checklist → COORDINATOR (checkpoint)
│   5.2 Go live → YOU (manual)
│   5.3 Monitor 48h → MONITOR (auto)
│   5.4 First fixes → DEVOPS (checkpoint)
│   5.5 First-week review → YOU (checkpoint)
│
├─ Phase 6: Operations & Management (18 steps)
│   6.1.1 Financial aggregation → ANALYST (auto)
│   6.1.2 Financial report → ANALYST (auto)
│   6.1.3 Review financials → YOU (checkpoint)
│   6.1.4 Approve expenses → YOU (manual)
│   6.2.1 Monitor feedback → SCRAPER (auto)
│   6.2.2 Analyze sentiment → ANALYST (auto)
│   6.2.3 Draft responses → WRITER (auto, unreviewed)
│   6.2.4 Approve comms → YOU (checkpoint)
│   6.3.1 Compliance research → RESEARCHER (auto)
│   6.3.2 Privacy audit → ANALYST (auto)
│   6.3.3 Approve legal changes → YOU (checkpoint)
│   6.3.4 File compliance docs → YOU (manual)
│   6.4.1 Workload analysis → ANALYST (auto)
│   6.4.2 Resource recs → COORDINATOR (auto)
│   6.4.3 Approve hiring → YOU (checkpoint)
│   6.4.4 Execute hires → YOU (manual)
│   6.5.1 Market shift research → RESEARCHER (auto)
│   6.5.2 Scenario analysis → ANALYST (auto)
│   6.5.3 Strategic decision → YOU (checkpoint)
│
├─ Phase 7: Growth & Adaptation (19 steps)
│   7.1 Research opportunities → RESEARCHER (auto)
│   7.2 Model scenarios → ANALYST (auto)
│   7.3 Scale infrastructure → DEVOPS (checkpoint)
│   7.4 Approve growth strategy → YOU (checkpoint)
│   7.5 Implement scaling → DEVOPS (checkpoint)
│   7.6 Monitor scale-up → MONITOR (auto)
│   7.7 Post-scale review → YOU (checkpoint)
│   ... (continues with expansion, new products, markets)
│
└─ Guardrails: All phases enforce FORBIDDEN actions.
   Checkpoints increase from 20% (Phase 1) to 70% (Phase 7).
   Manual steps集中在 Phase 4+ (legal, financial, signing).
```

---

## GUARDRAIL EVOLUTION ACROSS PHASES

| Guardrail Check | Phase 1-2 | Phase 3-4 | Phase 5-6 | Phase 7 |
|----------------|-----------|-----------|-----------|---------|
| Check 1: Forbidden | All PASS | All PASS | Some trigger (payments, comms) | Some trigger (contracts, legal) |
| Check 2: Conditional | All PASS | Some trigger (deploy, infra) | Many trigger (prod changes) | Many trigger (arch, scale) |
| Check 3: Outcome Verifiable | Always verifiable | Mostly verifiable | Some not (live traffic) | Rarely guaranteed |
| Check 4: Data Affected | No data modified | Some data created | Real user data affected | Production data changed |
| Check 5: Reversible | Always reversible | Mostly reversible | Some irreversible | Mostly irreversible |
| Check 6: Interpretation | Clear intent | Clear intent | Some ambiguity | High ambiguity |

---

## OPERATOR DECISION FRAMEWORK DURING OPERATIONS

During Phases 6-7, the operator faces recurring decision patterns:

### Daily/Weekly Check-in Template:
```
┌─ Operations Review
├─ Revenue: $X (▲/▼ Y% from last week)
├─ Customers: N active (▲/▼ Y%)
├─ Expenses: $X
├─ Cash Runway: N months
├─ Top Customer Request: [summary]
├─ Top Bug/Issue: [summary]
├─ Compliance Status: [green/yellow/red]
├─ Recommendations:
│   1. [Action] — impact: $X, effort: low/med/high
│   2. [Action] — impact: $X, effort: low/med/high
├─ Checkpoints Requiring Decision:
│   1. [Decision] — Option A vs B vs C, recommendation
└─ What do you want? (decide / ask more / approve all / pause)
```

### Escalation Tiers During Operations:
| Tier | What Triggers | What Happens | LLM Role |
|------|--------------|--------------|----------|
| **T1: Auto-resolve** | Routine anomalies (disk space warning, slow response) | LLM reports, suggests fix, waits for approval | Monitor + recommend |
| **T2: Operator decision** | Revenue anomaly, customer churn risk, compliance gap | Present data + options + recommendation, wait | Analyst + presenter |
| **T3: Immediate halt** | Security breach, data loss, legal violation | Stop all agents, alert operator, preserve evidence | Coordinator + reporter |

---

## KEY PRINCIPLE: THE LLM IS AN ADVISOR, NOT A DECISION-MAKER

Across all phases:
- **The LLM can research, analyze, and recommend.**
- **The LLM can build, deploy, and monitor (with guardrails).**
- **The LLM can NEVER decide strategy, spend money, sign contracts, or communicate externally without operator approval.**

This is not a weakness. This is the entire system.

---

*This document is the bridge between "let's research this" and "we're running a business." It defines where the LLM operates autonomously, where it asks for permission, and where it must defer to the operator. Read it before Phase 3 and keep it open during Phases 6-7.*
