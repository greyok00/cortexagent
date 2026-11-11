# Cortex Supervisory Harness — Design Spec

Date: 2026-11-11
Status: approved (sections 1–3 reviewed by owner in session)
Scope owner: this tree + sibling mirror (`~/cortexagent/`)
Out of scope: QA control (separate session owns that research), model weights, GPU-side SLMs at runtime.

## 1. Why

The local backbone model works but loops, forgets, and breaks tools. A second LLM cannot reliably
supervise a first; instead the harness owns deterministic enforcement and the model owns proposals,
giving each subsystem what it does best. Owner decisions locked in session: core inside the
runtime, stats outside; full escalation authority; all three self-improvement lanes; all control
from the harness (no external CLI needed). The supervisor also extends the wave-6 self-healing
directive (heal.py ladder, steer intervals, locked-lane respawn) into one machine that TRACKS
STATE instead of firing scattered reflexes.

## 2. Research groundings

- MetaAgent (ICML 2025, arXiv:2507.22606): FSM controls agent actions and state transitions;
  validated design pattern for FSM-supervised agents.
- AgenticStateMachines (github.com/adamterlson): supervision/tool-use patterns as statically
  analyzable FSMs — transitions are unit-testable.
- Self-Healing Framework (arXiv:2605.06737): failure taxonomy F1 hallucination, F2 execution
  error, F3 reasoning inconsistency, F4 workflow propagation; runtime reliability score
  R = ω1·C + ω2·S + ω3·E (consistency/stability/execution success); exceptions converted to
  readable prose for the agent; recovery = adaptive replanning + corrective prompting.
- RRSI (arXiv:2609.24972, Google Research): recursive self-improvement of the HARNESS around a
  frozen backbone, regularized to avoid overfitting — one small edit-bundle per proposal cycle,
  critic + pruner in the selector; admitted changes must hold on out-of-distribution scenarios.
- MetaSkill-Evolve (arXiv:2607.05297): two timescales — skills/improvements evolve fast, the
  improvement procedure evolves slow.
- Owner-approved detector technologies: FSM, behavior trees, CFG validation, lightweight
  classifiers, small language models (CPU-side or cloud :11600 only — cortexagent holds VRAM).

## 3. Architecture — supervision core (inside runtime)

One module, `core/supervisor.py` (raw .py in dev mode per existing tree law), wired at the same
choke points as the current steered loop: pre-execution (tool call about to run), post-execution
(result returned), and per-model-turn (streamed output).

### 3.1 FSM (the session state)

States: `WORKING` → `DEGRADED` → `RECOVERING` → `BLOCKED` (+ `IDLE` between tasks).
Transitions are the only enforcement site. All transitions unit-testable; no hidden paths.
- WORKING −(detector fires)→ DEGRADED
- DEGRADED −(ladder node acts; recovery in flight)→ RECOVERING
- RECOVERING −(result improves / ledger updated)→ WORKING
- RECOVERING −(ladder exhausted)→ BLOCKED
- BLOCKED −(session ends / owner clears)→ IDLE

### 3.2 Detectors (cost-ordered tiers)

Failure classes adopt the F1–F4 taxonomy; heal.py's four existing classes (model_down,
lane_down, 1-token storm, refusals) fold into F2/infra and stay operational.
1. Deterministic (always on): tool-call repetition loop (same tool + similarity-hashed args +
   similar result; detector fires at 3 identical events in a task window), 1-token storms, error-burst window, exec-gate refusal repeats,
   stopReason:length repeats (already queued in the wave-6 plan; carried in here).
2. CFG validation (always on): structured outputs / tool args parsed against a grammar before
   execution; nonconforming call rejected pre-run with plain-prose reason.
3. Lightweight classifiers (opt-in): output-similarity scoring feeding the consistency metric C;
   error-rate thresholds from RRSI-style windows.
4. Small language models (opt-in, off hot path): refusal reads / F3 inconsistency hints; must be
   CPU-resident or via the cloud intern on :11600; never a VRAM competitor.
5. Reliability score (continuous): cheap local estimate per run window from consistency,
   stability, execution-success; used to drive DEGRADED→RECOVERING decisions and sidecar stats.

### 3.3 Escalation ladder (behavior tree)

Priority-ordered fallback chain, one node acting per escalation, all prose to the model:
1. Steer lesson — failure rendered in plain words the model can act on.
2. Forced alternative — includes ledger record of what failed and why; may forbid the failing
   action class for the task.
3. Cancel task — state → BLOCKED path starts.
4. Respawn locked lane — existing mechanism reused.
5. Stop and surface — full violation history to owner banner; session halts for the owner.
Steer-effectiveness tracking (same lesson key refiring → escalate to a different lesson) carries
in from the wave-6 plan.

### 3.4 Working-memory ledger

Per task: actions tried, failures, why, forced alternatives. Stored OUTSIDE the model context so
it survives compaction. Feeds ladder node 2, the playbook distiller, and the sidecar.

### 3.5 Prose enforcement rule

Every block, cancel, or steering action arrives in the model's context as a one-sentence plain
prose reason (self-healing paper pattern: exceptions become text the agent can reason about).
Never a bare error code.

## 4. Architecture — external sidecar (no authority)

Small Python service, separate lane, can-fail-cleanly. Consumes: detector firings, escalations,
ledger entries, steer attempts, per-window reliability scores. Produces: failure-class counts,
per-detector precision, steer-effectiveness stats, playbook proposals. Cannot inject or cancel.
A dead sidecar degrades the runtime to nothing — the hot path must never depend on it.

## 5. Architecture — self-improvement loop (RRSI-shaped)

Runs offline between sessions, inside the sidecar. RULEBOOK-ONLY by hard constraint: thresholds,
lesson texts, playbook entries. The FSM code and enforcement logic are frozen from the loop.

1. PROPOSE: rank failure classes fired most; draft at most ONE small edit-bundle (annealed
   budget rule: never bulk edits).
2. SELECT: eval replay — recorded failure scenarios re-run against the candidate rulebook; a
   change passes only if supervisor transitions PASS on replay AND on held-out scenarios
   (critic + pruner rule: rejects too-small, too-expensive, benchmark-specific, no-longer-useful).
3. ADOPT or REJECT: admitted change lands in the declarative rulebook with provenance (incident,
   date, replay score); rejected proposals kept for audit.

Eval replay harness: recordings come from session jsonl + supervisor event logs; scenarios are
nameable, versioned, and rerunnable in CI against the supervisor (deterministic, no model needed
for transition tests; model-in-loop replays optional and idle-box only).

## 6. Architecture — cross-session playbook

File in agent-home (both-trees synced): for each recurring failure class, one short prose rule
read at session start and injected when the matching detector warms up mid-session. Entries carry
learned-from provenance and age out after 5 sessions without a firing. Success metric for the
live loop: a scripted repetition-loop task must trip the ladder within 3 wasted model turns
(spec-level target; exact thresholds land in the rulebook and may tuned from logs). Playbook edits only via
the improvement loop or owner.

## 7. Data flow

Session events → supervisor (FSM + detectors + ladder) → ledger + sidecar stream. Sidecar →
stats + proposals → eval replay (CI + idle box) → rulebook/playbook → loaded by supervisor next
session. The model sees only: prose steers, ledger summaries, playbook entries.

## 8. Error handling and resilience

- Supervisor itself cannot-fail: any internal exception logs and degrades to observe-only;
  enforcement never wedges the main loop (wave-6 hang class is the standing lesson).
- Sidecar death: runtime unaffected; stats gap noted on next sidecar start.
- Prose rule, always; no exception object ever reaches the model raw.
- All thresholds in the declarative rulebook, versioned, with defaults committed in-tree.

## 9. Testing

- FSM transition table: exhaustive unit tests (statically analyzable by design).
- Detectors: golden scenario fixtures (repetition loop, storm, burst, refusal repeat, malformed
  call) run against the supervisor with NO model.
- Ladder: sequence tests asserting one-node-acts ordering and prose output.
- Eval replay: scenario suite doubles as the acceptance gate for rulebook changes.
- Both trees updated and green per the sibling law.

## 10. Implementation order (later expanded by writing-plans)

1. Supervisor module + FSM + ledger, wired into the existing steered-loop choke points
   (heal.py folds in, stays backward compatible).
2. Tier-1 detectors + ladder nodes 1–2 + prose rule.
3. Ladder nodes 3–5 (cancel, respawn reuse, stop/surface).
4. Sidecar + event stream + stats.
5. Eval replay + proposal/adoption flow.
6. Playbook distiller + retention.

## 11. Success criteria

- Live session survives a scripted repetition-loop task with ≤N model turns wasted (fixture
  replay proves the ladder fires before the model would naturally exhaust context).
- Ledger survives compaction within a session; playbook entries replay-prove they prevent the
  incident that created them.
- A rulebook change rejected by held-out replay never lands (proven by fixture).
- No VRAM competitor for the backbone; supervisor hot path adds no model calls by default.
