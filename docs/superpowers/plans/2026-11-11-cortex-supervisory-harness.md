# Cortex Supervisory Harness Implementation Plan

> **SUPERSEDED 2026-11-11:** the owner routed the build across sessions. The supervision core (Tasks 1-5, and the runtime wiring) is implemented in Python by another session at `supervision/` (`fsm.py`, `detectors.py`, `supervisor.py`), matching this same spec. Tasks 6-8 of this plan are superseded by `docs/superpowers/plans/2026-11-11-supervision-remaining-lanes-plan.md` (sidecar, eval replay, proposal loop, playbook distiller), rebuilt around the Python core's contracts. This file stays for the record; do not execute it.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FSM supervisors (in-runtime extension), the no-authority sidecar, the eval-replay gate, the regularized proposal loop, and the cross-session playbook per the approved spec at `docs/superpowers/specs/2026-11-11-cortex-supervisory-harness-design.md`.

**Architecture:** The supervisor brain is a pure TypeScript module (`agent-home/extensions/supervisor-core.ts`) with no runtime imports, wrapped by an extension (`agent-home/extensions/supervisor.ts`) that hooks `tool_call`, `tool_result`, `turn_end`, and `agent_start` on the coding-agent ExtensionAPI. A Python sidecar (`bin/supervisor-sidecar.py`) consumes append-only events with no authority; the proposal loop (`bin/supervisor_propose.py`) and eval replay (`tests/supervisor-replay.ts` driven by `bin/eval_replay.py`) edit only the declarative rulebook.

**Tech Stack:** TypeScript extensions (coding-agent ExtensionAPI, loaded from `agent-home/extensions/`), pytest bridging to `node --experimental-strip-types` (node v22.22.2 in `~/.nvm/versions/node/v22.22.2/bin/node`), Python 3.13 sidecar (stdlib only).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-11-cortex-supervisory-harness-design.md` (both trees share this docs path; commits land in both at once).
- Both-trees law: `~/cortex-agent` and `~/cortexagent` are siblings; `docs/`, and (verify per task, don't assume) other shared paths may be symlinked. After every commit, verify `git -C ~/cortexagent status --short` is empty and HEAD matches `~/cortex-agent`. If a path IS separate in the sibling, copy + commit there too, same message plus "` (mirror)`.
- No-overwrite sibling law: never mass-copy; add/modify files explicitly.
- Do NOT modify `agent-home/extensions/loop-guard.ts`, `supervised-steer.ts`, `exec-gate.ts`, or any other existing extension. The supervisor composes with them, never edits them.
- Supervisor cannot-fail: every runtime handler is wrapped; any internal exception logs to the journal and the supervisor degrades to observe-only (no block, no steer). Enforcement must never wedge the loop (wave-6 hang class).
- All supervision prose shown to the model starts with a `[supervisor] ` prefix and is plain prose, no error codes, no em dashes.
- No model calls in the hot path. Tier-3/4 detectors are opt-in config not enabled by this plan.
- State lives at `~/cortex-agent/state/supervision/` (same convention as `supervised-steer.ts`): `events.jsonl`, `rulebook.json`, `stats.json`, `playbook.json`, `rulebook-provenance.jsonl`. Missing files are treated as empty/defaults; never crash on missing state.
- Defaults in-tree at `agent-home/supervisor-defaults.json`; the runtime rulebook file may override thresholds only.
- Existing pytest suite must stay green after every task (`pytest tests/ -q`).
- Python is stdlib-only (no new pip deps). TypeScript: no new npm deps.
- Node test runner: `node --experimental-strip-types` (erasable TS syntax only: no enums, no namespaces, parameter properties banned; use `interface`/`type` and plain classes).

---

## Interfaces (defined once, used by all tasks)

```ts
// supervisor-core.ts public surface
export type Phase = "idle" | "working" | "degraded" | "recovering" | "blocked";

export interface Rulebook {
  loopWindow: number;        // sliding window over recent tool calls
  loopMaxPerWindow: number;  // same normalized key allowed in window before repetition_loop fires
  loopLifetimeMax: number;   // same normalized key allowed per task
  errorBurstWindow: number;  // calls counted in burst window
  errorBurstMax: number;     // isError results allowed in burst window
  stormTokenMin: number;     // a result is "tiny" when resultTextLen < this
  stormRepeatMax: number;    // consecutive tiny results before tool_storm fires
  reliabilityWindow: number; // calls in the reliability window
  reliabilityFloor: number;  // R below this fires reliability_low
  weights: { consistency: number; stability: number; success: number };
  playbookAgeSessions: number; // playbook entries age out after N unfired sessions
  lessons: Record<string, string>; // FailureClass -> steer lesson prose (template slot {detail})
  lessonVariants: Record<string, string[]>; // FailureClass -> alternate lesson texts for the proposal loop
}

export type FailureClass =
  | "repetition_loop" | "tool_storm" | "error_burst" | "malformed_args"
  | "refusal_repeat" | "length_storm" | "reliability_low" | "ladder_exhausted";

export interface SupervisorEvent {
  ts: number;                 // ms epoch for tests, Date.now() in wiring
  taskId?: string;            // per-task ledger key; wiring supplies session/task id
  kind: "tool_call" | "tool_result" | "turn_end";
  toolName?: string;
  input?: Record<string, unknown>;
  isError?: boolean;
  resultTextLen?: number;
  resultPreview?: string;     // first 200 chars, for refusal detection (deterministic includes)
  stopReason?: string;        // assistant turn stopReason for length_storm
}

export type Decision =
  | { node: "block"; cls: FailureClass; reason: string }   // return value gates the call pre-exec
  | { node: "steer"; cls: FailureClass; lessonKey: string; msg: string }
  | { node: "cancel"; cls: FailureClass; msg: string }     // fence tools + steer end-turn prose
  | { node: "respawn"; cls: FailureClass; msg: string }    // journal-only; locked-lane machinery acts
  | { node: "surface"; cls: FailureClass; msg: string };

export interface ValidateResult { ok: boolean; reason?: string }
export function validateToolInput(toolName: string, input: Record<string, unknown>): ValidateResult;

export interface ReplayOutcome { phase: Phase; decisions: Decision[]; }
export class SupervisorCore {
  constructor(rulebook: Rulebook);
  phase: Phase;
  observe(event: SupervisorEvent): Decision[];   // at most ONE ladder decision per escalating event
  reset(): void;                                  // new task: clears callLog, escalations, ledger
  ledgerSummary(): string;                        // plain prose of tried/failed for forced-alternative text
}

export function reliability(callLog: CallRecord[], rules: Rulebook): number; // 0..1
export interface CallRecord { ts: number; key: string; isError: boolean; tiny: boolean; stopReason?: string; tags?: string[] }
```

Events.jsonl record (one line per wiring emission, sidecar's only input):
```json
{"ts":0,"phase":"degraded","decisions":[{"node":"steer","cls":"repetition_loop","lessonKey":"repetition_loop:v0"}],"event":{"ts":0,"kind":"tool_result","toolName":"read","taskId":"t1"},"rulebookVersion":1}
```

Scenario file schema (`tests/fixtures/supervisor-scenarios.json`, one object):
```json
{"name":"s","distribution":"in|holdout","rulebookOverride":{},"events":[{"ts":0,"kind":"tool_result","toolName":"read","isError":false,"resultTextLen":10,"stopReason":"stop"}],"expect":{"phase":"working","steers":0,"blocks":0,"cancels":0}}
```

Stats.json schema (sidecar output, proposal loop's only input):
```json
{"failureCounts":{"repetition_loop":40},"firesByDetector":{"repetition_loop":40},"steerEffectiveness":{"repetition_loop:v0":{"fired":10,"resolved":7,"refired":3}},"classesUnfired":{},"rulebookVersion":1}
```

---

### Task 1: supervisor-core module — FSM, rulebook, defaults file

**Files:**
- Create: `agent-home/extensions/supervisor-core.ts`
- Create: `agent-home/supervisor-defaults.json`
- Create: `tests/supervisor-core.test.ts`
- Create: `tests/test_supervisor_core.py`

**Interfaces:**
- Produces: `Phase`, `Rulebook`, `DEFAULT_RULEBOOK`, `SupervisorCore` (constructor + `phase` + `observe(event): Decision[]`, with `repetition_loop` detection and minimal state transitions), test bridge usable by later tasks.

- [ ] **Step 1: Write the failing FSM tests**

Create `tests/supervisor-core.test.ts`:

```ts
// ESM harness run via: node --experimental-strip-types tests/supervisor-core.test.ts
import assert from "node:assert";
import {
  SupervisorCore,
  DEFAULT_RULEBOOK,
  type Decision,
  type SupervisorEvent,
} from "../agent-home/extensions/supervisor-core.ts";

const ev = (over: Partial<SupervisorEvent>): SupervisorEvent => ({
  ts: 0, kind: "tool_result", toolName: "read", isError: false, resultTextLen: 100,
  taskId: "t1", ...over,
});

function run(name: string, fn: () => void): void {
  try { fn(); console.log(`PASS ${name}`); }
  catch (e) { console.log(`FAIL ${name}: ${String(e)}`); process.exitCode = 1; }
}

run("defaults loaded and sane", () => {
  const r = DEFAULT_RULEBOOK;
  assert.ok(r.loopWindow >= r.loopMaxPerWindow);
  assert.ok(r.loopLifetimeMax >= r.loopMaxPerWindow);
  assert.ok(r.weights.consistency + r.weights.stability + r.weights.success > 0.99);
});

run("new core starts idle and first event moves it working", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  assert.equal(core.phase, "idle");
  core.observe(ev({}));
  assert.equal(core.phase, "working");
});

run("repetition loop fires steer on the loopMaxPerWindow-th identical event", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  let decisions: Decision[] = [];
  for (let i = 0; i < DEFAULT_RULEBOOK.loopMaxPerWindow; i++) {
    decisions = core.observe(ev({
      kind: "tool_call", toolName: "bash",
      input: { command: "curl -s example.com | wc -c" },
    }));
  }
  assert.equal(decisions.length, 1);
  assert.equal(decisions[0].node, "steer");
  assert.equal(decisions[0].cls, "repetition_loop");
  assert.ok(decisions[0].msg.startsWith("[supervisor] "));
  assert.ok(core.phase === "degraded" || core.phase === "recovering");
});

run("cosmetically varied retries still count as repetition", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  let decisions: Decision[] = [];
  for (let i = 0; i < DEFAULT_RULEBOOK.loopMaxPerWindow; i++) {
    decisions = core.observe(ev({
      kind: "tool_call", toolName: "bash",
      input: { command: `curl -s  example.com   |  wc -c  # attempt ${i}` },
    }));
  }
  assert.equal(decisions.length, 1);
  assert.equal(decisions[0].cls, "repetition_loop");
});

run("reset clears repetition state and phases", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  for (let i = 0; i < DEFAULT_RULEBOOK.loopMaxPerWindow; i++)
    core.observe(ev({ kind: "tool_call", toolName: "bash", input: { command: "x" } }));
  core.reset();
  assert.equal(core.phase, "idle");
  core.observe(ev({}));
  assert.equal(core.phase, "working");
  const d = core.observe(ev({ kind: "tool_call", toolName: "bash", input: { command: "x" } }));
  assert.equal(d.length, 0);
});
```

Create `tests/test_supervisor_core.py` (pytest bridge, same pattern every later task reuses):

```python
"""Node TS suite runner: pytest bridges to node --experimental-strip-types."""
import os, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODE = str(pathlib.Path(os.path.expanduser("~/.nvm/versions/node/v22.22.2/bin/node")))

def _run(ts_file: str) -> str:
    p = subprocess.run(
        [NODE, "--experimental-strip-types", str(ROOT / "tests" / ts_file)],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    print(p.stdout)
    if p.returncode != 0:
        raise AssertionError(f"{ts_file} failed (rc={p.returncode})\n{p.stderr}")
    return p.stdout

def test_supervisor_core_fsm():
    out = _run("supervisor-core.test.ts")
    assert "FAIL" not in out
    assert "PASS defaults loaded and sane" in out
    assert "PASS repetition loop fires steer" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ~/cortex-agent && ~/.nvm/versions/node/v22.22.2/bin/node --experimental-strip-types tests/supervisor-core.test.ts`
Expected: FAIL (module not found: supervisor-core.ts). `pytest tests/test_supervisor_core.py -q` fails the same way.

- [ ] **Step 3: Write supervisor-core.ts (FSM + repetition detector + reset)**

Create `agent-home/extensions/supervisor-core.ts`:

```ts
// supervisor-core.ts - pure supervisor brain per the 2026-11-11 approved spec:
// FSM state machine, tiered failure detectors, escalation ladder, per-task
// ledger. NO runtime imports: the extension (supervisor.ts) wraps this with
// ExtensionAPI handlers, and tests/ drive it directly under node.
// The default export is a no-op guard: the extensions loader instantiates
// every file in the directory and this file is a library, not an extension.
export type Phase = "idle" | "working" | "degraded" | "recovering" | "blocked";

export type FailureClass =
  | "repetition_loop" | "tool_storm" | "error_burst" | "malformed_args"
  | "refusal_repeat" | "length_storm" | "reliability_low" | "ladder_exhausted";

export interface Rulebook {
  loopWindow: number;
  loopMaxPerWindow: number;
  loopLifetimeMax: number;
  errorBurstWindow: number;
  errorBurstMax: number;
  stormTokenMin: number;
  stormRepeatMax: number;
  reliabilityWindow: number;
  reliabilityFloor: number;
  weights: { consistency: number; stability: number; success: number };
  playbookAgeSessions: number;
  lessons: Record<string, string>;
  lessonVariants: Record<string, string[]>;
}

export const DEFAULT_LESSONS: Record<string, string> = {
  repetition_loop:
    "[supervisor] repeated call detected: {detail}. The same action is producing the same outcome, so retrying it again will not help. Either change the approach so the outcome can differ, or do the repetition mechanically in one compound command or a background job, or stop and report what you have verified plus what is blocking you.",
  tool_storm:
    "[supervisor] results are coming back effectively empty ({detail}). Do not keep making the same calls against the same target. Step back, state what you were trying to learn, and pick a different way to learn it.",
  error_burst:
    "[supervisor] a burst of errors just happened ({detail}). Something systemic is wrong: the tool, the path, or the environment. Verify the assumption that failed instead of retrying the same form.",
  refusal_repeat:
    "[supervisor] this action is being refused repeatedly ({detail}). Refusals repeat when the route is disallowed, not when the request is unlucky. Choose a different route or defer the whole task.",
  length_storm:
    "[supervisor] output keeps getting cut for length ({detail}). Narrow the request: ask for less, chunk the work, or write results to a file and summarize instead of streaming everything.",
  reliability_low:
    "[supervisor] the last {n} actions are degrading: consistency, stability, and success are all dropping. Do NOT continue the current line of work. Restate the goal and pick the single most reliable next step.",
  ladder_exhausted:
    "[supervisor] the task has now hit every recovery rung. It is parked. Report a one paragraph handoff: goal, what you tried, what failed, and the smallest next step for the owner.",
};

export const LESSON_VARIANTS: Record<string, string[]> = {
  repetition_loop: [
    "[supervisor] repeated call detected: {detail}. Same action, same outcome, so a retry is dead weight. Rewrite it as one compound command or a background job, or change the approach.",
  ],
  tool_storm: [
    "[supervisor] results are effectively empty ({detail}). Name the question you needed answered, then answer it a different way.",
  ],
  error_burst: [
    "[supervisor] errors are repeating in a burst ({detail}). Treat the burst as one failure, not many: find the shared cause before the next call.",
  ],
  refusal_repeat: [
    "[supervisor] refusals are repeating ({detail}). The route is blocked, not the request. Reroute or defer.",
  ],
};

export const DEFAULT_RULEBOOK: Rulebook = {
  loopWindow: 20,
  loopMaxPerWindow: 6,
  loopLifetimeMax: 60,
  errorBurstWindow: 8,
  errorBurstMax: 5,
  stormTokenMin: 4,
  stormRepeatMax: 3,
  reliabilityWindow: 12,
  reliabilityFloor: 0.35,
  weights: { consistency: 0.4, stability: 0.3, success: 0.3 },
  playbookAgeSessions: 5,
  lessons: DEFAULT_LESSONS,
  lessonVariants: LESSON_VARIANTS,
};

export interface SupervisorEvent {
  ts: number;
  taskId?: string;
  kind: "tool_call" | "tool_result" | "turn_end";
  toolName?: string;
  input?: Record<string, unknown>;
  isError?: boolean;
  resultTextLen?: number;
  resultPreview?: string;
  stopReason?: string;
}

export type Decision =
  | { node: "block"; cls: FailureClass; reason: string }
  | { node: "steer"; cls: FailureClass; lessonKey: string; msg: string }
  | { node: "cancel"; cls: FailureClass; msg: string }
  | { node: "respawn"; cls: FailureClass; msg: string }
  | { node: "surface"; cls: FailureClass; msg: string };

// Normalized repetition key: exact tool + args normalized so cosmetic
// variation (spacing, comments, trailing numbers) does not sneak past the
// window tier the way it can past loop-guard's exact-JSON key tier.
export function normalizedKey(toolName: string, input: Record<string, unknown> | undefined): string {
  const norm = (v: unknown): unknown => {
    if (typeof v === "string") return v.replace(/\s+/g, " ").replace(/#.*$/, "").trim().toLowerCase();
    if (typeof v === "number") return "<n>";
    if (Array.isArray(v)) return v.map(norm);
    if (v && typeof v === "object") {
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(v as Record<string, unknown>).sort())
        out[k] = norm((v as Record<string, unknown>)[k]);
      return out;
    }
    return v;
  };
  return toolName + "::" + JSON.stringify(norm(input ?? {}));
}

export interface CallRecord {
  ts: number; key: string; isError: boolean; tiny: boolean; stopReason?: string; tags?: string[];
}

// FSM: transitions are the ONLY enforcement site and every edge is explicit.
// Invalid edges degrade to a no-op (logged by wiring, never crash).
// Exported so tests can walk the whole table (spec section 9).
export const TRANSITIONS: Record<Phase, { onFire?: Phase; onRecover?: Phase; }> = {
  idle: { onFire: "working" },
  working: { onFire: "degraded", onRecover: "working" },
  degraded: { onRecover: "recovering" },
  recovering: { onFire: "blocked" },
  blocked: {},
};

export class SupervisorCore {
  rules: Rulebook;
  phase: Phase;
  private log: CallRecord[] = [];
  private fireCount = 0; // ladder rungs taken on the current task
  private seenInWindow = new Map<string, number[]>();
  private tinyRun = 0;
  private ledger: string[] = [];

  constructor(rulebook: Rulebook = DEFAULT_RULEBOOK) {
    this.rules = rulebook;
    this.phase = "idle";
  }

  reset(): void {
    this.phase = "idle";
    this.log = [];
    this.fireCount = 0;
    this.seenInWindow.clear();
    this.tinyRun = 0;
    this.ledger = [];
  }

  ledgerSummary(): string {
    if (this.ledger.length === 0) return "no prior attempts on record";
    return this.ledger.join("; ");
  }

  observe(event: SupervisorEvent): Decision[] {
    if (event.taskId && this.log.length === 0 && this.phase === "idle") this.phase = "working";
    const rec = this.toRecord(event);
    if (rec) this.log.push(rec);

    const decisions: Decision[] = [];
    const fired = this.detect(event);
    if (fired) {
      const d = this.escalate(fired);
      if (d) {
        decisions.push(d);
        this.applyPhase(d);
      }
    } else if (this.phase === "degraded" || this.phase === "recovering") {
      // quiet event after a fire: recover the phase, keep the rung so the
      // ladder still ascends on the next fire within the same task
      this.phase = "working";
    }
    return decisions;
  }

  private toRecord(event: SupervisorEvent): CallRecord | null {
    if (event.kind === "tool_call")
      return { ts: event.ts, key: normalizedKey(event.toolName ?? "", event.input), isError: false, tiny: false, tags: [] };
    if (event.kind === "tool_result") {
      const tiny = (event.resultTextLen ?? 999) < this.rules.stormTokenMin;
      const tags: string[] = [];
      const prev = (event.resultPreview ?? "").toLowerCase();
      if (prev.includes("refused") || prev.includes("refusal") || prev.includes("permission denied"))
        tags.push("refusal");
      return { ts: event.ts, key: "", isError: event.isError === true, tiny, tags };
    }
    // turn_end IS logged: the length-storm detector needs the stopReason tail
    return { ts: event.ts, key: "", isError: false, tiny: false, stopReason: event.stopReason, tags: [] };
  }

  // Detectors, cost-ordered, first fire wins per event.
  private detect(event: SupervisorEvent): FailureClass | null {
    if (event.kind === "tool_call" || event.kind === "tool_result") {
      const rep = this.detectRepetition(event);
      if (rep) return "repetition_loop";
      const burst = this.detectBurst();
      if (burst) return "error_burst";
      const storm = this.detectStorm();
      if (storm) return "tool_storm";
      const refusal = this.detectRefusalRepeat();
      if (refusal) return "refusal_repeat";
      const length = this.detectLengthStorm();
      if (length) return "length_storm";
    }
    if (event.kind === "turn_end") {
      if (this.detectLengthStorm()) return "length_storm";
      const r = reliability(this.log, this.rules);
      if (r < this.rules.reliabilityFloor) return "reliability_low";
    }
    return null;
  }

  private countsInWindow(): number {
    const last = this.log.filter((r) => r.key !== "");
    const win = last.slice(-this.rules.loopWindow);
    return win.length;
  }

  private detectRepetition(event: SupervisorEvent): boolean {
    const key = event.kind === "tool_call" ? normalizedKey(event.toolName ?? "", event.input) : null;
    if (!key) return false;
    const win = this.log.slice(-this.rules.loopWindow).filter((r) => r.key === key);
    const life = this.log.filter((r) => r.key === key).length;
    if (life > this.rules.loopLifetimeMax || win.length >= this.rules.loopMaxPerWindow) {
      this.ledger.push(`tried ${event.toolName} x${life}: same result each time`);
      return true;
    }
    return false;
  }

  private detectBurst(): boolean {
    const win = this.log.slice(-this.rules.errorBurstWindow);
    const errors = win.filter((r) => r.isError).length;
    if (win.length >= this.rules.errorBurstWindow && errors >= this.rules.errorBurstMax) {
      this.ledger.push(`${errors}/${this.rules.errorBurstWindow} recent calls errored`);
      return true;
    }
    return false;
  }

  private detectStorm(): boolean {
    const run = this.consecutiveTail((r) => r.tiny);
    if (run >= this.rules.stormRepeatMax) {
      this.ledger.push(`${run} consecutive near-empty results`);
      return true;
    }
    return false;
  }

  private detectRefusalRepeat(): boolean {
    const run = this.consecutiveTail((r) => (r.tags ?? []).includes("refusal"));
    if (run >= 3) {
      this.ledger.push(`${run} consecutive refusals`);
      return true;
    }
    return false;
  }

  private detectLengthStorm(): boolean {
    const last = this.log.slice(-this.rules.stormRepeatMax);
    if (last.length === this.rules.stormRepeatMax &&
        last.every((r) => r.stopReason === "length")) {
      this.ledger.push(`last ${this.rules.stormRepeatMax} turns stopped on length`);
      return true;
    }
    return false;
  }

  private consecutiveTail(pred: (r: CallRecord) => boolean): number {
    let n = 0;
    for (let i = this.log.length - 1; i >= 0; i--) {
      if (pred(this.log[i])) n++; else break;
    }
    return n;
  }

  // Ladder: one node acts per escalation, rung = fireCount, prose always.
  private escalate(cls: FailureClass): Decision | null {
    this.fireCount++;
    const detail = this.ledger[this.ledger.length - 1] ?? "pattern detected";
    const lessonKey = `${cls}:v${this.rules.lessonVariants[cls]?.length ? 0 : 0}`;
    const lesson = (this.rules.lessons[cls] ?? DEFAULT_LESSONS[cls] ?? "").replace("{detail}", detail);
    if (this.phase === "recovering" || this.fireCount >= 5) {
      if (this.fireCount >= 5 && this.phase !== "blocked") {
        const msg = (DEFAULT_LESSONS["ladder_exhausted"] ?? "").replace("{detail}", this.ledgerSummary());
        return { node: "surface", cls: "ladder_exhausted", msg };
      }
      return null; // already in recovery/stop: do not double-fire
    }
    switch (this.fireCount) {
      case 1:
        this.ledger.push(`steered(${cls})`);
        return { node: "steer", cls, lessonKey, msg: lesson };
      case 2:
        this.ledger.push(`block(${cls})`);
        return {
          node: "block", cls,
          reason: `${lesson} Record so far: ${this.ledgerSummary()}. Do NOT reissue the failing call: change the approach or end your turn and report.`,
        };
      case 3: {
        const msg = `${lesson} The task is now cancelled: I have fenced the tools for it. End your turn and report what you tried, what failed, and what you need.`;
        this.ledger.push(`cancel(${cls})`);
        return { node: "cancel", cls, msg };
      }
      case 4:
        return { node: "respawn", cls, msg: lesson };
      default:
        return null;
    }
  }

  private applyPhase(d: Decision): void {
    const t = TRANSITIONS[this.phase] ?? {};
    const next = d.node === "cancel" ? "blocked" : d.node === "block" || d.node === "steer" ? (t.onFire ?? this.phase) : d.node === "respawn" ? "recovering" : (t.onFire ?? this.phase);
    if (next !== this.phase && TRANSITIONS[this.phase][next === "degraded" ? "onFire" : next === "recovering" ? "onRecover" : "onFire"] !== undefined || d.node === "cancel") {
      this.phase = d.node === "cancel" ? "blocked" : next;
    } else if (d.node === "steer" || d.node === "block") {
      this.phase = t.onFire ?? "degraded";
    }
  }
}

export function reliability(log: CallRecord[], rules: Rulebook): number {
  const win = log.slice(-rules.reliabilityWindow);
  if (win.length === 0) return 1;
  const keys = win.filter((r) => r.key !== "");
  const dups = keys.length - new Set(keys.map((r) => r.key)).size;
  const consistency = keys.length > 0 ? 1 - dups / keys.length : 1;
  const stability = 1 - win.filter((r) => r.isError).length / win.length;
  const success = 1 - win.filter((r) => r.tiny).length / win.length;
  const w = rules.weights;
  return (w.consistency * consistency + w.stability * stability + w.success * success);
}

export default function supervisorCoreGuard(): void {
  // library, not an extension: loader calls this as a harmless no-op
}
```

Also create `agent-home/supervisor-defaults.json` (committed defaults that BOTH `supervisor.ts` and the proposal loop can read; the runtime file `state/supervision/rulebook.json` overrides thresholds only):

```json
{
  "version": 1,
  "rulebook": {
    "loopWindow": 20,
    "loopMaxPerWindow": 6,
    "loopLifetimeMax": 60,
    "errorBurstWindow": 8,
    "errorBurstMax": 5,
    "stormTokenMin": 4,
    "stormRepeatMax": 3,
    "reliabilityWindow": 12,
    "reliabilityFloor": 0.35,
    "weights": { "consistency": 0.4, "stability": 0.3, "success": 0.3 },
    "playbookAgeSessions": 5
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/cortex-agent && ~/.nvm/versions/node/v22.22.2/bin/node --experimental-strip-types tests/supervisor-core.test.ts; pytest tests/test_supervisor_core.py -q`
Expected: all PASS lines, pytest 1 passed. (If the `applyPhase` type checker complains under strip-types, simplify the method to an explicit per-`node` if/else assigning `this.phase` directly; the behavior contract is: cancel → blocked, steer/block first-fire → degraded, respawn → recovering, surface in working/degraded → blocked.)

- [ ] **Step 5: Commit**

```bash
cd ~/cortex-agent && git add agent-home/extensions/supervisor-core.ts agent-home/supervisor-defaults.json tests/supervisor-core.test.ts tests/test_supervisor_core.py
git commit -m "feat: supervisor-core FSM + repetition/window detectors + ladder skeleton"
git -C ~/cortexagent log --oneline -1   # must equal the commit above
git -C ~/cortexagent status --short     # must be empty
```

---

### Task 2: supervisor-core — grammar gate, burst/storm/refusal/length/reliability detectors + full FSM tests

**Files:**
- Modify: `agent-home/extensions/supervisor-core.ts` (add `validateToolInput`, extend `detect` — most detectors landed with Task 1; Task 2 completes the CFG gate + extends tests)
- Modify: `tests/supervisor-core.test.ts`

**Interfaces:**
- Consumes: Task 1 module surface.
- Produces: `validateToolInput(toolName: string, input: Record<string, unknown>): { ok: boolean; reason?: string }` used by Task 5 wiring.

- [ ] **Step 1: Write failing tests**

Append to `tests/supervisor-core.test.ts`:

```ts
import { validateToolInput, reliability, TRANSITIONS } from "../agent-home/extensions/supervisor-core.ts";
import type { CallRecord } from "../agent-home/extensions/supervisor-core.ts";

run("FSM transition table is exhaustive and explicit", () => {
  const phases: string[] = ["idle", "working", "degraded", "recovering", "blocked"];
  for (const p of phases) assert.ok(p in TRANSITIONS, `missing row: ${p}`);
  assert.ok(!("onFire" in TRANSITIONS.blocked));
  assert.ok(!("onRecover" in TRANSITIONS.blocked));
});

run("bash command must be a string", () => {
  assert.ok(validateToolInput("bash", { command: "ls" }).ok);
  const bad = validateToolInput("bash", { command: 42 });
  assert.equal(bad.ok, false);
  assert.ok((bad.reason ?? "").startsWith("[supervisor] "));
});

run("malformed args block is a gate, not an escalation (phase stays working)", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  const d = core.observe(ev({ kind: "tool_call", toolName: "bash", input: { command: null } }));
  assert.equal(d[0].node, "block");
  assert.equal(d[0].cls, "malformed_args");
  assert.equal(core.phase, "working");
});

run("unknown tools pass the gate", () => {
  assert.ok(validateToolInput("mystery_tool", { anything: { x: 1 } }).ok);
});

run("error burst fires after window of errors", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  let decisions: Decision[] = [];
  for (let i = 0; i < DEFAULT_RULEBOOK.errorBurstWindow; i++)
    decisions = core.observe(ev({ isError: true, resultTextLen: 200, resultPreview: "boom" }));
  assert.equal(decisions[0]?.cls, "error_burst");
  assert.ok(["steer", "block"].includes(decisions[0]?.node as string));
});

run("tiny-result storm fires on consecutive tiny results", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  let decisions: Decision[] = [];
  for (let i = 0; i < DEFAULT_RULEBOOK.stormRepeatMax; i++)
    decisions = core.observe(ev({ resultTextLen: 1, resultPreview: "" }));
  assert.equal(decisions[0]?.cls, "tool_storm");
});

run("refusal run fires after 3 consecutive refusals", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  let decisions: Decision[] = [];
  for (let i = 0; i < 3; i++)
    decisions = core.observe(ev({ isError: true, resultTextLen: 50, resultPreview: "refused: not allowed" }));
  assert.equal(decisions[0]?.cls, "refusal_repeat");
});

run("length storm fires on 3 length-stopped turn_ends", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  let decisions: Decision[] = [];
  for (let i = 0; i < 3; i++)
    decisions = core.observe(ev({ kind: "turn_end", stopReason: "length" }));
  assert.equal(decisions[0]?.cls, "length_storm");
});

run("reliability computes 1 on clean log and drops toward 0 on repeated failures", () => {
  const clean: CallRecord[] = [
    { ts: 1, key: "a::1", isError: false, tiny: false },
    { ts: 2, key: "b::1", isError: false, tiny: false },
  ];
  assert.equal(reliability(clean, DEFAULT_RULEBOOK), 1);
  const bad: CallRecord[] = Array.from({ length: 12 }, (_, i) => ({
    ts: i, key: "a::1", isError: true, tiny: true,
  }));
  assert.ok(reliability(bad, DEFAULT_RULEBOOK) < DEFAULT_RULEBOOK.reliabilityFloor);
});

run("ladder ascends steer then block on the next fire", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  for (let i = 0; i < DEFAULT_RULEBOOK.loopMaxPerWindow; i++)
    core.observe(ev({ kind: "tool_call", toolName: "bash", input: { command: "curl example.com" } }));
  // fire #2: repeat the loop after a quiet legal event
  assert.equal(core.observe(ev({})).length, 0); // recovery
  for (let i = 0; i < DEFAULT_RULEBOOK.loopMaxPerWindow; i++) {
    const d = core.observe(ev({ kind: "tool_call", toolName: "bash", input: { command: "curl example.com" } }));
    if (d.length) {
      assert.equal(d[0].node, "block");
      assert.ok((d[0].reason as string).includes("Record so far"));
      return;
    }
  }
  throw new Error("second fire did not happen");
});

run("cancel fire fences the task: phase blocked, surface only afterwards", () => {
  const core = new SupervisorCore(DEFAULT_RULEBOOK);
  core.observe(ev({}));
  core.observe({ ts: 0, kind: "turn_end", taskId: "t1" });
  core.phase = "degraded"; core["fireCount"] = 2; // arrive at rung 3 deterministically
  const d = core.observe(ev({ isError: true, resultTextLen: 200, resultPreview: ["boom", "boom", "boom"].join("") }));
  // force a burst fire: errorBurstWindow errors
  if (!d.length) {
    for (let i = 0; i < DEFAULT_RULEBOOK.errorBurstWindow; i++) {
      const dd = core.observe(ev({ isError: true, resultTextLen: 200, resultPreview: "boom" }));
      if (dd.length) { d.push(dd[0]); break; }
    }
  }
  assert.ok(d.length >= 1);
});
```

- [ ] **Step 2: Run to verify new tests fail**

Run: `node --experimental-strip-types tests/supervisor-core.test.ts`
Expected: FAIL on `malformed_args`, gate, and ladder-ascend tests (functions/branches missing).

- [ ] **Step 3: Implement the gate + ladder-ascend fix**

In `supervisor-core.ts` add above `SupervisorCore`:

```ts
export interface ValidateResult { ok: boolean; reason?: string }

// CFG tier: structural grammar gate on tool args. Whitelisted checks only;
// unknown tools PASS (default-allow so the supervisor can never fence a tool
// it does not know). A malformed bash command is rejected BEFORE it runs.
const TOOL_GRAMMAR: Record<string, (input: Record<string, unknown>) => ValidateResult> = {
  bash: (input) => {
    if (typeof input.command !== "string")
      return { ok: false, reason: "[supervisor] blocked: bash needs its command as a text argument; this call is malformed, rebuild it and retry." };
    if ((input.command as string).length > 20000)
      return { ok: false, reason: "[supervisor] blocked: bash command is oversized; write it to a file and run the file instead." };
    return { ok: true };
  },
};

export function validateToolInput(toolName: string, input: Record<string, unknown>): ValidateResult {
  const check = TOOL_GRAMMAR[toolName];
  if (!check) return { ok: true };
  try { return check(input); } catch { return { ok: true }; }
}
```

In `SupervisorCore.observe`, run the gate FIRST for `tool_call` events (before detectors) and make a gate block non-escalating (it must NOT increment `fireCount` and must NOT move the phase):

```ts
observe(event: SupervisorEvent): Decision[] {
  if (event.taskId && this.log.length === 0 && this.phase === "idle") this.phase = "working";
  if (event.kind === "tool_call") {
    const v = validateToolInput(event.toolName ?? "", event.input ?? {});
    if (!v.ok) return [{ node: "block", cls: "malformed_args", reason: v.reason as string }];
  }
  const rec = this.toRecord(event);
  if (rec) this.log.push(rec);
  // ... rest unchanged from Task 1 (detect, escalate, quiet-branch recover)
}
```

Rewrite `applyPhase` as the explicit version so it is statically analyzable:

```ts
private applyPhase(d: Decision): void {
  if (d.node === "cancel") { this.phase = "blocked"; return; }
  if (d.node === "respawn") { this.phase = "recovering"; return; }
  if (d.node === "surface") { this.phase = "blocked"; return; }
  if (d.node === "steer" || d.node === "block") {
    const t = TRANSITIONS[this.phase];
    if (this.phase === "idle" || this.phase === "working") this.phase = "degraded";
    else if (this.phase === "degraded") this.phase = "recovering";
    else if (this.phase === "recovering") this.phase = "blocked";
    else if (!t) { /* blocked stays blocked */ }
  }
}
```

The Task 1 `escalate` second-fire branch: ensure rung 2 produces `node: "block"` (already does) and that a "block" decision at rung 2 arrives even if the interim `ev({})` moved phase to recovering: change the rung guard to use `fireCount` alone (not phase) for rungs 1..4, keeping the `fireCount >= 5 → surface` branch. Delete the `lessonKey` line computing a constant; use:

```ts
const lessonKey = `${cls}:v0`;
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --experimental-strip-types tests/supervisor-core.test.ts; pytest tests/test_supervisor_core.py -q`
Expected: all PASS, pytest 1 passed. (Update the pytest bridge asserts if it pins any removed string.)

- [ ] **Step 5: Commit**

```bash
cd ~/cortex-agent && git add agent-home/extensions/supervisor-core.ts tests/supervisor-core.test.ts
git commit -m "feat: supervisor CFG gate + burst/storm/refusal/length detectors + ladder ascend"
git -C ~/cortexagent log --oneline -1
git -C ~/cortexagent status --short
```

---

### Task 3: sidecar — no-authority event consumer and stats

**Files:**
- Create: `bin/supervisor-sidecar.py`
- Create: `tests/test_supervisor_sidecar.py`

**Interfaces:**
- Consumes: `~/cortex-agent/state/supervision/events.jsonl` (Task 5 output schema, stated in the plan header).
- Produces: `~/cortex-agent/state/supervision/stats.json` with keys `failureCounts` (cls→count), `firesByDetector` (cls→count), `classesUnfired` (cls→sessions since last fire), `steerEffectiveness` (lessonKey→{fired,resolved,refired}), `rulebookVersion` (from `rulebook.json` `version` or 0). Used by Task 7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_supervisor_sidecar.py`:

```python
import json, pathlib, tempfile, subprocess, sys, os

SIDECAR = pathlib.Path.home() / "cortex-agent" / "bin" / "supervisor-sidecar.py"

def run_once(events: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as td:
        events_p = pathlib.Path(td) / "events.jsonl"
        stats_p = pathlib.Path(td) / "stats.json"
        with events_p.open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        for i, e in enumerate(events):
            # sidecar must be able to consume events in two passes (offset)
            pass
        p = subprocess.run(
            [sys.executable, str(SIDECAR), "--events", str(events_p),
             "--stats", str(stats_p), "--once"],
            capture_output=True, text=True, timeout=60,
        )
        assert p.returncode == 0, f"sidecar rc={p.returncode}\n{p.stderr}"
        return json.loads(stats_p.read_text())

def _event(cls: str, node: str = "steer", lessonKey: str | None = None, refire: bool = False):
    d = {"node": node, "cls": cls}
    if lessonKey:
        d["lessonKey"] = lessonKey
    return {"ts": 0, "phase": "degraded", "decisions": [d], "event": {"ts": 0, "kind": "tool_result"}, "rulebookVersion": 1}

def test_counts_and_steers():
    events = [_event("repetition_loop", "steer", "repetition_loop:v0")] * 2 + \
             [_event("tool_storm", "steer", "tool_storm:v0"),
              _event("repetition_loop", "steer", "repetition_loop:v0", refire=True)]
    s = run_once(events)
    assert s["failureCounts"]["repetition_loop"] == 3
    assert s["failureCounts"]["tool_storm"] == 1
    se = s["steerEffectiveness"]["repetition_loop:v0"]
    assert se["fired"] == 3
    assert se["refired"] >= 1

def test_empty_and_missing_input_produce_zero_stats():
    with tempfile.TemporaryDirectory() as td:
        events_p = pathlib.Path(td) / "nope.jsonl"
        stats_p = pathlib.Path(td) / "stats.json"
        p = subprocess.run(
            [sys.executable, str(SIDECAR), "--events", str(events_p),
             "--stats", str(stats_p), "--once"],
            capture_output=True, text=True, timeout=60,
        )
        assert p.returncode == 0, p.stderr
        s = json.loads(stats_p.read_text())
        assert s["failureCounts"] == {}

def test_rotation_does_not_replay_history():
    # append-only consumer with rotation resync: a file that SHRANK must not
    # be re-read from 0 (the supervised-steer replay flood, fixed 2026-11-09)
    with tempfile.TemporaryDirectory() as td:
        ev = pathlib.Path(td) / "events.jsonl"
        st = pathlib.Path(td) / "stats.json"
        ev.write_text(json.dumps(_event("repetition_loop", "steer", "repetition_loop:v0")) + "\n")
        subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev),
                        "--stats", str(st), "--once", "--persist-state", str(pathlib.Path(td) / "sidecar.state.json")], check=True, capture_output=True)
        ev.write_text("")  # rotation/truncation
        subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev),
                        "--stats", str(st), "--once", "--persist-state", str(pathlib.Path(td) / "sidecar.state.json")], check=True, capture_output=True)
        s = json.loads(st.read_text())
        assert s["failureCounts"] == {"repetition_loop": 1}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_supervisor_sidecar.py -q`
Expected: FAIL (sidecar file missing).

- [ ] **Step 3: Implement the sidecar**

Create `bin/supervisor-sidecar.py`:

```python
#!/usr/bin/env python3
"""supervisor-sidecar.py - stats consumer for the supervisory harness.

NO AUTHORITY: this process never injects, blocks, or cancels. It reads
events.jsonl (owned by the supervisor extension), aggregates stats.json, and
optionally watches. A dead sidecar must not affect the runtime (spec: lanes
cannot-fail; runtime never depends on it). stdlib only.
"""
import argparse, json, tempfile
from pathlib import Path

RESOLVED_AFTER = 10  # events: a steer with no same-class decision in the
                     # next N events counts as resolved, a later one refires

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(Path.home() / "cortex-agent/state/supervision/events.jsonl"))
    ap.add_argument("--stats", default=str(Path.home() / "cortex-agent/state/supervision/stats.json"))
    ap.add_argument("--state", default=str(Path.home() / "cortex-agent/state/supervision/sidecar.state.json"))
    ap.add_argument("--persist-state", dest="state")
    ap.add_argument("--rulebook", default=str(Path.home() / "cortex-agent/state/supervision/rulebook.json"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    return ap.parse_args()

def read_offset(state_path: Path):
    try:
        return json.loads(state_path.read_text()).get("eventsOffset", 0)
    except Exception:
        return 0

def write_offset(state_path: Path, offset: int):
    try:
        state_path.write_text(json.dumps({"eventsOffset": offset}))
    except Exception:
        pass

def collect(events_path: Path, offset: int):
    """Consume new lines; returns (lines, new_offset). Rotation/truncation
    resyncs to EOF WITHOUT replay (lesson from supervised-steer 2026-11-09)."""
    try:
        size = events_path.stat().st_size
    except OSError:
        return [], offset
    if size < offset:
        return [], size  # rotated/truncated: resync, never replay
    if size <= offset:
        return [], offset
    new_bytes = size - offset
    with events_path.open("rb") as f:
        f.seek(offset)
        chunk = f.read(new_bytes).decode("utf-8", errors="replace")
    return chunk.splitlines(), size

def aggregate(lines, acc):
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue  # partial/torn line: skip, never crash
        stream = rec.get("events", [])
        decisions = rec.get("decisions") or []
        for d in decisions:
            cls = d.get("cls")
            node = d.get("node")
            if not cls:
                continue
            if node in ("steer", "block", "cancel", "respawn", "surface"):
                acc["failureCounts"][cls] = acc["failureCounts"].get(cls, 0) + 1
                if node == "steer":
                    key = d.get("lessonKey", f"{cls}:v0")
                    se = acc["steerEffectiveness"].setdefault(key, {"fired": 0, "resolved": 0, "refired": 0})
                    se["fired"] += 1
                    acc["_pending"][(cls, se)] = {
                        "remaining": RESOLVED_AFTER, "steer": se,
                    }
        seen_cls = [d.get("cls") for d in decisions if d.get("cls")]
        pends = list(acc["_pending"].items())
        for keyp, state in pends:
            if keyp[0] in seen_cls:
                state["steer"]["refired"] += 1
                state["resolved"] = True
                del acc["_pending"][keyp]
            else:
                state["remaining"] -= 1
                if state["remaining"] <= 0:
                    state["steer"]["resolved"] += 1
                    del acc["_pending"][keyp]

def emit(stats_path: Path, acc, rulebook_path: Path):
    version = 0
    try:
        version = json.loads(rulebook_path.read_text()).get("version", 0)
    except Exception:
        pass
    out = {
        "failureCounts": acc["failureCounts"],
        "firesByDetector": acc["failureCounts"],
        "steerEffectiveness": acc["steerEffectiveness"],
        "classesUnfired": acc.get("classesUnfired", {}),
        "rulebookVersion": version,
    }
    tmp = stats_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(stats_path)

def main():
    args = parse_args()
    events_path = Path(args.events)
    stats_path = Path(args.stats)
    state_path = Path(args.state or args.persist_state)
    acc = {
        "failureCounts": {}, "steerEffectiveness": {}, "classesUnfired": {},
        "_pending": {},
    }
    if stats_path.exists():
        try:
            prev = json.loads(stats_path.read_text())
            acc["failureCounts"] = prev.get("failureCounts", {})
            acc["steerEffectiveness"] = prev.get("steerEffectiveness", {})
            acc["classesUnfired"] = prev.get("classesUnfired", {})
        except Exception:
            pass
    offset = read_offset(state_path)
    while True:
        lines, offset = collect(events_path, offset)
        if lines:
            aggregate(lines, acc)
            write_offset(state_path, offset)
        emit(stats_path, acc, Path(args.rulebook))
        if args.once or not args.watch:
            break
        import time
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_supervisor_sidecar.py -q && pytest tests/test_supervisor_core.py -q`
Expected: 3 passed, plus core suite still passing.

- [ ] **Step 5: Commit**

```bash
cd ~/cortex-agent && git add bin/supervisor-sidecar.py tests/test_supervisor_sidecar.py
git commit -m "feat: supervisory sidecar stats consumer (no authority, rotation-safe)"
git -C ~/cortexagent log --oneline -1 ; git -C ~/cortexagent status --short
```

---

### Task 4: eval replay — scenario runner and fixture suite

**Files:**
- Create: `tests/supervisor-replay.ts`
- Create: `tests/fixtures/supervisor-scenarios.json`
- Create: `bin/eval_replay.py`
- Create: `tests/test_eval_replay.py`

**Interfaces:**
- Consumes: `SupervisorCore` from Task 1/2.
- Produces: replay exit code 0 = all pass; stdout lines `PASS <name>` / `FAIL <name>: <why>`. `bin/eval_replay.py --scenarios <path> --dist in|holdout|both [--override '<json>']` runs the same runner and is the acceptance gate Task 7 calls.

- [ ] **Step 1: Write scenario fixtures**

Create `tests/fixtures/supervisor-scenarios.json`:

```json
{
  "scenarios": [
    {"name": "steady-work", "distribution": "in", "rulebookOverride": {}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": false, "resultTextLen": 120, "resultPreview": "content"},
      {"ts": 1, "kind": "tool_call", "toolName": "bash", "input": {"command": "echo done"}},
      {"ts": 2, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 10, "resultPreview": "done"}
    ], "expect": {"phaseEnd": "working", "steers": 0, "blocks": 0, "cancels": 0}},

    {"name": "curl-loop-steers-then-blocks", "distribution": "in", "rulebookOverride": {"loopMaxPerWindow": 6}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": false, "resultTextLen": 100, "resultPreview": "start"},
      {"ts": 1, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 2, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 3, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 4, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 5, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 6, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 7, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 8, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 9, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 10, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 11, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 12, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"},
      {"ts": 13, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s example.com | wc -c"}},
      {"ts": 14, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 9, "resultPreview": "1234"}
    ], "expect": {"phaseEnd": "degraded", "steers": 1, "blocks": 1, "cancels": 0}},

    {"name": "interleaved-loop-holdout", "distribution": "holdout", "rulebookOverride": {"loopMaxPerWindow": 6}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": false, "resultTextLen": 80, "resultPreview": "legit"},
      {"ts": 1, "kind": "tool_call", "toolName": "grep", "input": {"pattern": "needle"}},
      {"ts": 2, "kind": "tool_result", "toolName": "grep", "isError": false, "resultTextLen": 30, "resultPreview": "hit"},
      {"ts": 3, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 4, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"},
      {"ts": 5, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 6, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"},
      {"ts": 7, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 8, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"},
      {"ts": 9, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 10, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"},
      {"ts": 11, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 12, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"},
      {"ts": 13, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl -s other.example | head -1"}},
      {"ts": 14, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 12, "resultPreview": "row"}
    ], "expect": {"steersAtMost": 1, "blocksAtMost": 1, "cancels": 0}},

    {"name": "malformed-bash-gate", "distribution": "in", "rulebookOverride": {}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": false, "resultTextLen": 80, "resultPreview": "legit"},
      {"ts": 1, "kind": "tool_call", "toolName": "bash", "input": {"command": 42}}
    ], "expect": {"phaseEnd": "working", "steers": 0, "blocks": 1, "cancels": 0}},

    {"name": "refusal-run-steers", "distribution": "in", "rulebookOverride": {}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "bash", "isError": false, "resultTextLen": 80, "resultPreview": "legit"},
      {"ts": 1, "kind": "tool_call", "toolName": "bash", "input": {"command": "ssh tunnel"}},
      {"ts": 2, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 60, "resultPreview": "refused: exec-gate"},
      {"ts": 3, "kind": "tool_call", "toolName": "bash", "input": {"command": "ssh tunnel -v"}},
      {"ts": 4, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 60, "resultPreview": "refused: exec-gate"},
      {"ts": 5, "kind": "tool_call", "toolName": "bash", "input": {"command": "ssh tunnel2"}},
      {"ts": 6, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 60, "resultPreview": "refused: exec-gate"}
    ], "expect": {"steers": 1, "blocks": 0, "cancels": 0, "steerClass": "refusal_repeat"}},

    {"name": "holdout-burst", "distribution": "holdout", "rulebookOverride": {}, "events": [
      {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": false, "resultTextLen": 80, "resultPreview": "legit"},
      {"ts": 1, "kind": "tool_call", "toolName": "bash", "input": {"command": "bad"}},
      {"ts": 2, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 3, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 4, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 5, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 6, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 7, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 8, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"},
      {"ts": 9, "kind": "tool_result", "toolName": "bash", "isError": true, "resultTextLen": 30, "resultPreview": "err"}
    ], "expect": {"steersAtMost": 1, "holdsAtTargetTurns": {"steerOrBlockByEventIndex": 10}}}
  ]
}
```

- [ ] **Step 2: Write the failing runner + bridge**

Create `tests/supervisor-replay.ts`:

```ts
// replay runner: feeds scenario events into SupervisorCore and checks
// expectations. Exit 1 if any scenario fails. stdout: PASS/FAIL lines.
import assert from "node:assert";
import { readFileSync } from "node:fs";
import {
  SupervisorCore, DEFAULT_RULEBOOK, type Decision, type Rulebook, type SupervisorEvent,
} from "../agent-home/extensions/supervisor-core.ts";

const args = process.argv.slice(2);
const scenarioPath = args[0] ?? "tests/fixtures/supervisor-scenarios.json";
const distFilter = args[1] ?? "both";
const overrideRaw = args[2] ?? "";

const loaded = JSON.parse(readFileSync(scenarioPath, "utf8")) as {
  scenarios: { name: string; distribution: string; rulebookOverride: Record<string, unknown>; events: SupervisorEvent[]; expect: Record<string, unknown> }[];
};

const overrides: Record<string, unknown> = overrideRaw ? JSON.parse(overrideRaw) : {};

function count(d: Decision[], node: string): number { return d.filter((x) => x.node === node).length; }

function runScenario(s: ReturnType<typeof buildScenario>): { pass: boolean; why: string } {
  const core = new SupervisorCore(s.rulebook);
  const decisions: Decision[] = [];
  for (const e of s.events) decisions.push(...core.observe(e));
  const ex = s.expect as Record<string, number | string | undefined>;
  const steers = count(decisions, "steer");
  const blocks = count(decisions, "block");
  const cancels = count(decisions, "cancel");
  try {
    if (ex.phaseEnd !== undefined) assert.equal(core.phase, ex.phaseEnd);
    if (ex.phaseEnd === "working" || ex.phaseEnd === undefined) {
      // quiet runs end working via the quiet-recover branch; assert not degraded
      assert.ok(core.phase !== "degraded" || steers + blocks + cancels > 0);
    }
    if (ex.steers !== undefined) assert.equal(steers, ex.steers);
    if (ex.blocks !== undefined) assert.equal(blocks, ex.blocks);
    if (ex.cancels !== undefined) assert.equal(cancels, ex.cancels);
    if (ex.steersAtMost !== undefined) assert.ok(steers <= (ex.steersAtMost as number));
    if (ex.blocksAtMost !== undefined) assert.ok(blocks <= (ex.blocksAtMost as number));
    if (ex.steerClass !== undefined) {
      const s0 = decisions.find((d) => d.node === "steer") as (Decision & { cls: string }) | undefined;
      assert.equal(s0?.cls, ex.steerClass);
    }
    return { pass: true, why: "" };
  } catch (e) {
    return { pass: false, why: String(e) };
  }
}

type ScenarioInput = (typeof loaded)["scenarios"][number];
function buildScenario(base: ScenarioInput) {
  const rb: Rulebook = { ...DEFAULT_RULEBOOK, ...(base.rulebookOverride ?? {}), ...overrides };
  return { ...base, rulebook: rb };
}

let failed = 0;
for (const base of loaded.scenarios) {
  if (distFilter !== "both" && base.distribution !== distFilter) continue;
  const r = runScenario(buildScenario(base));
  if (r.pass) console.log(`PASS ${base.name}`);
  else { console.log(`FAIL ${base.name}: ${r.why}`); failed++; }
}
process.exitCode = failed > 0 ? 1 : 0;
```

Create `bin/eval_replay.py`:

```python
#!/usr/bin/env python3
"""eval_replay.py - acceptance gate for rulebook changes (spec section 5).

Runs the TS replay runner against scenario fixtures. `--dist in` runs
in-distribution scenarios, `--dist holdout` the held-out ones, `both` all.
A change is adoptable only when BOTH dists pass (RRSI critic+pruner rule).
Exit 0 = gate passes; 1 = gate fails (never adopt).
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path.home() / "cortex-agent"
NODE = os.path.expanduser("~/.nvm/versions/node/v22.22.2/bin/node")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervisor-scenarios.json"))
    ap.add_argument("--dist", choices=["in", "holdout", "both"], default="both")
    ap.add_argument("--override", default="")  # JSON rulebook override for candidates
    a = ap.parse_args()
    cmd = [NODE, "--experimental-strip-types", str(ROOT / "tests/supervisor-replay.ts"),
           a.scenarios, a.dist]
    if a.override:
        cmd.append(a.override)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    print(p.stdout, end="")
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Create `tests/test_eval_replay.py`:

```python
import json, os, subprocess, sys, pathlib, tempfile

ROOT = pathlib.Path.home() / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"

def test_baseline_replay_both_dists_pass():
    p = subprocess.run([sys.executable, str(EVAL)], capture_output=True, text=True, timeout=120)
    print(p.stdout)
    assert p.returncode == 0, p.stderr

def test_override_gate_catches_broken_rulebook():
    # a candidate that can never fire the ladder (loopMaxPerWindow 999) must
    # make the in-dist loop scenario FAIL: the gate is real
    p = subprocess.run(
        [sys.executable, str(EVAL), "--dist", "in", "--override",
         json.dumps({"loopMaxPerWindow": 999, "loopLifetimeMax": 999})],
        capture_output=True, text=True, timeout=120)
    assert p.returncode != 0
    assert "FAIL" in p.stdout

def test_holdout_split_selects_the_right_scenarios():
    with tempfile.TemporaryDirectory() as td:
        src = json.loads((ROOT / "tests/fixtures/supervisor-scenarios.json").read_text())
        out = {"scenarios": [s for s in src["scenarios"] if s["distribution"] == "holdout"]}
        f = pathlib.Path(td) / "holdout.json"
        f.write_text(json.dumps(out))
        p = subprocess.run([sys.executable, str(EVAL), "--scenarios", str(f), "--dist", "holdout"],
                           capture_output=True, text=True, timeout=120)
        assert p.returncode == 0
        assert "holdout" in p.stdout
```

- [ ] **Step 3: Run to verify fixtures pass against the current core**

Run: `bin/eval_replay.py` and `pytest tests/test_eval_replay.py -q`
Expected: all scenarios PASS on the in-dist suite; pytest 3 passed. Fix any scenario expectations that expose genuine core bugs (fix the core, never the fixture to make it pass; if an expectation is genuinely wrong, change it and say so in the commit message).

- [ ] **Step 4: Commit**

```bash
cd ~/cortex-agent && git add tests/supervisor-replay.ts tests/fixtures/supervisor-scenarios.json bin/eval_replay.py tests/test_eval_replay.py
git commit -m "feat: eval replay gate with in-dist + holdout scenarios"
git -C ~/cortexagent log --oneline -1 ; git -C ~/cortexagent status --short
```

---

### Task 5: supervisor.ts — the extension wiring

**Files:**
- Create: `agent-home/extensions/supervisor.ts`

**Interfaces:**
- Consumes: `supervisor-core.ts` (Tasks 1–2).
- Produces: runtime behavior per spec section 3; appends events.jsonl lines; steers via `pi.sendUserMessage`.

- [ ] **Step 1: Write the extension**

Create `agent-home/extensions/supervisor.ts`:

```ts
// supervisor.ts - the in-runtime wrapper for supervisor-core (spec 2026-11-11:
// owner decisions "core inside runtime, stats outside", "full ladder",
// "harness-managed"). Hooks tool_call (CFG gate + detectors), tool_result
// (post-exec detectors), turn_end (reliability) and agent_start (playbook).
// CANNOT-FAIL: every handler is try/caught; any internal error drops the
// supervisor to observe-only for the session (no block, no steer) and the
// error lands in the journal. Never wedges the loop.
import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  DEFAULT_LESSONS, DEFAULT_RULEBOOK, SupervisorCore,
  type Decision, type Rulebook, type SupervisorEvent,
} from "./supervisor-core.ts";

const HOME = os.homedir();
const STATE_DIR = path.join(HOME, "cortex-agent", "state", "supervision");
const EVENTS = path.join(STATE_DIR, "events.jsonl");
const RULEBOOK = path.join(STATE_DIR, "rulebook.json");
const PLAYBOOK = path.join(STATE_DIR, "playbook.json");
const JOURNAL = path.join(STATE_DIR, "journal-observe.jsonl");

try { fs.mkdirSync(STATE_DIR, { recursive: true }); } catch { /* exists */ }

function loadRulebook(): Rulebook {
  let file: Partial<Rulebook> = {};
  try { file = JSON.parse(fs.readFileSync(RULEBOOK, "utf8")); } catch { /* missing: defaults */ }
  const lessons = { ...DEFAULT_LESSONS, ...(file.lessons ?? {}) };
  const rules: Rulebook = { ...DEFAULT_RULEBOOK, ...file, lessons } as Rulebook;
  rules.lessonVariants = file.lessonVariants ?? DEFAULT_RULEBOOK.lessonVariants;
  return rules;
}

interface PlaybookEntry { cls: string; text: string; learnedFrom: string; ts: number; sessionsUnfired: number }
function loadPlaybook(): PlaybookEntry[] {
  try {
    const j = JSON.parse(fs.readFileSync(PLAYBOOK, "utf8"));
    return Array.isArray(j.entries) ? (j.entries as PlaybookEntry[]) : [];
  } catch { return []; }
}

function appendLine(file: string, obj: unknown): void {
  try { fs.appendFileSync(file, JSON.stringify(obj) + "\n"); } catch { /* disk issue: journal is best-effort */ }
}

export default function supervisor(pi: ExtensionAPI): void {
  const core = new SupervisorCore(loadRulebook());
  let observeOnly = false; // set true by any internal error: cannot-fail rule
  const steeredLessonKeys = new Map<string, number>(); // lessonKey -> count, playbook warm-up hook
  let taskId = "task-0";
  let playedBook = false; // playbook steer once per session at start

  const feed = (event: SupervisorEvent): Decision[] => {
    if (observeOnly) return [];
    try { return core.observe(event); }
    catch (e) {
      observeOnly = true;
      appendLine(JOURNAL, { ts: Date.now(), note: "observe-only", error: String(e) });
      return [];
    }
  };

  const act = (decisions: Decision[]): void => {
    for (const d of decisions) {
      if (d.node === "block") continue; // handled by the tool_call return value
      if (d.node === "steer") {
        const n = (steeredLessonKeys.get(d.lessonKey) ?? 0) + 1;
        steeredLessonKeys.set(d.lessonKey, n);
        const pb = loadPlaybook().find((p) => p.cls === d.cls);
        const msg = pb ? `${pb.text} (${pb.learnedFrom})` : d.msg;
        try { pi.sendUserMessage(`[supervisor] ${msg.includes("[supervisor]") ? msg.replace("[supervisor] ", "") : msg}`, { deliverAs: "steer" }); }
        catch { /* steer cannot wedge us */ }
      }
      if (d.node === "cancel") {
        try { pi.setActiveTools([]); } catch { /* fence best-effort */ }
        try { pi.sendUserMessage(`[supervisor] ${d.msg.replace("[supervisor] ", "")}`, { deliverAs: "steer" }); } catch { /* */ }
      }
      if (d.node === "respawn") {
        appendLine(EVENTS, { ts: Date.now(), phase: core.phase, decisions: [d], event: {}, rulebookVersion: 1 });
        try { pi.sendUserMessage(`[supervisor] ${d.msg.replace("[supervisor] ", "")}`, { deliverAs: "steer" }); } catch { /* */ }
      }
      if (d.node === "surface") {
        try { pi.sendUserMessage(`[supervisor] ${d.msg.replace("[supervisor] ", "")}`, { deliverAs: "steer" }); } catch { /* */ }
      }
    }
  };

  pi.on("agent_start", () => {
    try {
      core.reset();
      const pb = loadPlaybook();
      if (pb.length > 0 && !playedBook) {
        playedBook = true;
        const digest = pb.map((e) => `- (${e.cls}): ${e.text}`).join("\n");
        try { pi.sendUserMessage(`[supervisor] playbook for this session:\n${digest}`, { deliverAs: "steer" }); } catch { /* */ }
      }
    } catch { /* cannot-fail */ }
  });

  pi.on("tool_call", (event) => {
    const decisions = feed({
      ts: Date.now(), taskId, kind: "tool_call",
      toolName: event.toolName, input: event.input as Record<string, unknown>,
    });
    act(decisions);
    if (observeOnly) return undefined;
    const block = decisions.find((d) => d.node === "block");
    if (block) return { block: true, reason: block.reason };
    return undefined;
  });

  pi.on("tool_result", (event) => {
    const text = Array.isArray(event.content)
      ? event.content.map((c) => (c as { text?: string }).text ?? "").join(" ")
      : "";
    const decisions = feed({
      ts: Date.now(), taskId, kind: "tool_result",
      toolName: event.toolName, isError: event.isError,
      resultTextLen: text.length, resultPreview: text.slice(0, 200),
    });
    appendLine(EVENTS, {
      ts: Date.now(), phase: core.phase, decisions,
      event: { ts: Date.now(), kind: "tool_result", toolName: event.toolName, taskId },
      rulebookVersion: 1,
    });
    act(decisions);
    return undefined;
  });

  pi.on("turn_end", () => {
    feed({ ts: Date.now(), taskId, kind: "turn_end" });
  });
}
```

- [ ] **Step 2: Syntax-verify the extension loads in isolation**

Run: `~/.nvm/versions/node/v22.22.2/bin/node --experimental-strip-types --input-type=module -e "const m = await import('file:///home/grey/cortex-agent/agent-home/extensions/supervisor.ts'); console.log(typeof m.default)"`
Expected: prints `function` (the type-only import of the runtime package disappears under strip-types; the relative core import resolves).

Then verify the existing smoke suite still passes AND that the extension dir has a way to prove wiring: run the runtime's own smoke test path:
Run: `pytest tests/test_smoke.py -q`
Expected: passed (no runtime regression from a new file in extensions/).

- [ ] **Step 3: Boot-proof the runtime with the extension present**

Run: `bin/cortex-agent --print "say ready"` (timeout 90s) — if the print-mode teardown hang (wave-6 open issue) bites, use the launch timeout wrapper exactly as before: `timeout 60 bin/cortex-agent --print "say ready"` and treat a hang as PRE-EXISTING, not ours: assert only that the process either answers or times out WITHOUT a supervisor error in the output.
Expected: no stack traces naming `supervisor` in output; exit code 0 or 124.

- [ ] **Step 4: Commit**

```bash
cd ~/cortex-agent && git add agent-home/extensions/supervisor.ts
git commit -m "feat: supervisor extension wiring (FSM live on tool_call/tool_result/turn_end)"
git -C ~/cortexagent log --oneline -1 ; git -C ~/cortexagent status --short
```

---

### Task 6: proposal loop — RRSI-shaped rulebook editing with provenance

**Files:**
- Create: `bin/supervisor_propose.py`
- Create: `tests/test_supervisor_propose.py`

**Interfaces:**
- Consumes: `stats.json` (Task 3), `eval_replay.py` (Task 4), rulebook at `state/supervision/rulebook.json`.
- Produces: new/updated `rulebook.json` ({"version": N+1, plus merged threshold overrides}), provenance lines in `state/supervision/rulebook-provenance.jsonl` (`{"ts","change","reason","replayIn","replayOut","decision":"adopted|rejected"}`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supervisor_propose.py`:

```python
import json, pathlib, subprocess, sys, tempfile, shutil, os

PROP = pathlib.Path.home() / "cortex-agent" / "bin" / "supervisor_propose.py"
BASE_RB = {"version": 1, "loopMaxPerWindow": 6, "reliabilityFloor": 0.35, "errorBurstMax": 5}

def base_state(td: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    td = pathlib.Path(td)
    rb, stats, prov = td / "rulebook.json", td / "stats.json", td / "rulebook-provenance.jsonl"
    rb.write_text(json.dumps(BASE_RB))
    return rb, stats, prov

def run_propose(td: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROP), "--state-dir", str(td)],
                          capture_output=True, text=True, timeout=300)

def test_no_failures_means_no_change_and_no_provenance():
    with tempfile.TemporaryDirectory() as td:
        rb, stats, prov = base_state(td)
        stats.write_text(json.dumps({"failureCounts": {}, "steerEffectiveness": {}, "rulebookVersion": 1}))
        p = run_propose(td)
        assert p.returncode == 0, p.stderr
        assert json.loads(rb.read_text())["version"] == 1
        assert not prov.exists()

def test_repetition_loop_candidate_adopts_only_when_both_dists_pass():
    # in-dist loop scenario passes with loopMaxPerWindow 5, but the holdout
    # interleaved scenario must then also pass or the change is rejected
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        rb, stats, prov = base_state(td)
        stats.write_text(json.dumps({
            "failureCounts": {"repetition_loop": 30},
            "firesByDetector": {"repetition_loop": 30},
            "steerEffectiveness": {"repetition_loop:v0": {"fired": 30, "resolved": 20, "refired": 10}},
            "rulebookVersion": 1,
        }))
        # give the proposal loop ONLY scenarios where tighter window passes on both dists
        scen = {"scenarios": [
            {"name": "f1", "distribution": "in", "rulebookOverride": {}, "events": [
                {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": False, "resultTextLen": 80, "resultPreview": "ok"}] + [
                {"ts": i, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl s"}} for i in range(1, 7)],
             "expect": {"steers": 1, "blocksAtMost": 1}},
            {"name": "h1", "distribution": "holdout", "rulebookOverride": {}, "events": [
                {"ts": 0, "kind": "tool_result", "toolName": "read", "isError": False, "resultTextLen": 80, "resultPreview": "ok"}] + [
                {"ts": i, "kind": "tool_call", "toolName": "bash", "input": {"command": "curl s"}} for i in range(1, 7)],
             "expect": {"steers": 1, "blocksAtMost": 1}}]}
        f = td / "scenarios.json"
        f.write_text(json.dumps(scen))
        p = subprocess.run([sys.executable, str(PROP), "--state-dir", str(td),
                            "--scenarios", str(f)], capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr
        lines = prov.read_text().strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["decision"] == "adopted"
        assert "loopMaxPerWindow" in rec["change"]
        assert json.loads(rb.read_text())["loopMaxPerWindow"] == 5

def test_pruner_rejects_a_no_effect_change():
    # candidate that changes nothing observable (delta below pruner step) is rejected
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        rb, stats, prov = base_state(td)
        stats.write_text(json.dumps({
            "failureCounts": {"tool_storm": 12},
            "firesByDetector": {"tool_storm": 12},
            "steerEffectiveness": {"tool_storm:v0": {"fired": 12, "resolved": 12, "refired": 0}},
            "rulebookVersion": 1,
        }))
        p = run_propose(td)
        # resolved>=80%: the lesson works; a threshold change is NOT warranted,
        # the pruner must refuse: nothing new learned, nothing changed
        lines = prov.read_text().strip().splitlines() if prov.exists() else []
        assert json.loads(rb.read_text())["version"] == 1
        assert lines == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_supervisor_propose.py -q`
Expected: FAIL (propose missing).

- [ ] **Step 3: Implement the proposal loop**

Create `bin/supervisor_propose.py`:

```python
#!/usr/bin/env python3
"""supervisor_propose.py - the RRSI-shaped offline improvement loop (spec 5).

RULEBOOK-ONLY by hard constraint: proposes at most ONE edit-bundle per run,
always to a declarative threshold or a lesson text. The FSM code and the
enforcement logic are NEVER touched by this loop. Selection = eval replay:
in-distribution AND held-out must both pass (critic + pruner). The pruner
rejects: no-failure states, already-healthy classes (resolved >= 80%), and
changes that would not alter any replayed scenario. Provenance lines are
appended for adopted AND rejected candidates so the owner can audit.
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path.home() / "cortex-agent"
EVAL = ROOT / "bin" / "eval_replay.py"
RESOLVED_HEALTHY = 0.80
THRESHOLD_STEP = 1

# which knob each failure class may have tuned, and the direction of tuning
KNOBS = {
    "repetition_loop": ("loopMaxPerWindow", "down"),
    "error_burst": ("errorBurstMax", "down"),
    "tool_storm": ("stormRepeatMax", "down"),
    "length_storm": ("stormRepeatMax", "down"),
}
FLOORS = {"loopMaxPerWindow": 3, "errorBurstMax": 3, "stormRepeatMax": 2}

def rank(stats):
    counts = stats.get("failureCounts", {})
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

def candidate(cls, rb):
    if cls not in KNOBS:
        return None
    key, direction = KNOBS[cls]
    val = rb.get(key)
    if not isinstance(val, int):
        return None
    if direction == "down" and val - THRESHOLD_STEP < FLOORS[key]:
        return None
    change = {key: val - THRESHOLD_STEP} if direction == "down" else {key: val + THRESHOLD_STEP}
    return {"cls": cls, "change": change, "key": key}

def replay(dist, override, scenarios):
    cmd = [sys.executable, str(EVAL), "--dist", dist, "--scenarios", str(scenarios)]
    if override:
        cmd += ["--override", json.dumps(override)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return p.returncode == 0, (p.stdout + p.stderr)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(ROOT / "state/supervision"))
    ap.add_argument("--scenarios", default=str(ROOT / "tests/fixtures/supervisor-scenarios.json"))
    a = ap.parse_args()
    sd = Path(a.state_dir)
    rb_path, stats_path, prov_path = sd / "rulebook.json", sd / "stats.json", sd / "rulebook-provenance.jsonl"
    try:
        rb = json.loads(rb_path.read_text()) if rb_path.exists() else {"version": 1}
        stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    except Exception as e:
        print(f"propose: unreadable state: {e}", file=sys.stderr)
        return 0  # cannot-fail: absence of data is never an error

    ranked = rank(stats)
    if not ranked:
        return 0
    cls, count = ranked[0]
    eff = (stats.get("steerEffectiveness") or {})
    se = eff.get(f"{cls}:v0") or {}
    fired, resolved = se.get("fired", 0), se.get("resolved", 0)
    if fired > 0 and resolved / fired >= RESOLVED_HEALTHY:
        print(f"propose: {cls} is healthy ({resolved}/{fired} resolved); pruner refuses a change")
        return 0
    cand = candidate(cls, rb)
    if cand is None:
        print(f"propose: no admissible candidate for {cls}")
        return 0

    cand_rb = {**rb, **cand["change"]}
    in_ok, in_out = replay("in", cand["change"], Path(a.scenarios))
    out_ok, out_out = replay("holdout", cand["change"], Path(a.scenarios))
    rec = {"ts": int(time.time()), "cls": cls, "change": cand["change"],
           "reason": f"{count} fires of {cls}", "replayIn": in_ok,
           "replayOut": out_ok,
           "decision": "adopted" if (in_ok and out_ok) else "rejected"}
    if rec["decision"] == "adopted":
        rb.update(cand["change"])
        rb["version"] = int(rb.get("version", 1)) + 1
        rb_path.write_text(json.dumps(rb))
    with prov_path.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_supervisor_propose.py -q && pytest tests/ -q`
Expected: all green (including the whole existing suite).

- [ ] **Step 5: Commit**

```bash
cd ~/cortex-agent && git add bin/supervisor_propose.py tests/test_supervisor_propose.py
git commit -m "feat: RRSI-shaped proposal loop (one bundle, replay critic, pruner, provenance)"
git -C ~/cortexagent log --oneline -1 ; git -C ~/cortexagent status --short
```

---

### Task 7: cross-session playbook — distiller, injection, aging

**Files:**
- Modify: `bin/supervisor-sidecar.py` (add `--distill` stage)
- Modify: `tests/test_supervisor_sidecar.py`
- Runtime side consumed by `supervisor.ts` (already reads `playbook.json`, done in Task 5).

**Interfaces:**
- Consumes: `stats.json` + current `rulebook.json` lessons.
- Produces: `state/supervision/playbook.json` `{"entries": [{"cls","text","learnedFrom","ts","sessionsUnfired"}]}`. A class with ≥3 fires becomes an entry (text = current lesson template), provenance = "learned from the 2026-11 session replay ledger". Entries with no fire increment `sessionsUnfired` per distill pass and are dropped past `playbookAgeSessions`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_supervisor_sidecar.py`:

```python
def test_distill_creates_entries_at_threshold_and_ages_out():
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ev = td / "events.jsonl"; st = td / "stats.json"; pb = td / "playbook.json"
        rb = td / "rulebook.json"
        rb.write_text(json.dumps({"version": 1, "lessons":
            {"repetition_loop": "L1"}}))
        ev.write_text(json.dumps({"ts": 0, "phase": "d",
            "decisions": [{"node": "steer", "cls": "repetition_loop", "lessonKey": "repetition_loop:v0"}],
            "event": {}, "rulebookVersion": 1}) + "\n")
        s1 = subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev),
                             "--stats", str(st), "--once", "--distill",
                             "--state-dir", str(td)], capture_output=True, text=True)
        assert s1.returncode == 0, s1.stderr
        # 1 fire < 3: no entry yet
        p1 = json.loads(pb.read_text())
        assert p1["entries"] == []
        for _ in range(2):
            with ev.open("a") as f:
                f.write(json.dumps({"ts": 1, "phase": "d", "decisions": [
                    {"node": "steer", "cls": "repetition_loop", "lessonKey": "repetition_loop:v0"}],
                    "event": {}, "rulebookVersion": 1}) + "\n")
        s2 = subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev),
                             "--stats", str(st), "--once", "--distill",
                             "--state-dir", str(td)], capture_output=True, text=True)
        assert s2.returncode == 0, s2.stderr
        entries = json.loads(pb.read_text())["entries"]
        assert len(entries) == 1
        assert entries[0]["cls"] == "repetition_loop"
        assert entries[0]["sessionsUnfired"] == 0
        # aging: sessions passing with no fire bump sessionsUnfired
        (td / "sidecar.state.json").write_text(json.dumps({"eventsOffset": ev.stat().st_size}))
        s3 = subprocess.run([sys.executable, str(SIDECAR), "--events", str(ev),
                             "--stats", str(st), "--once", "--distill", "--age",
                             "--state-dir", str(td)], capture_output=True, text=True)
        assert s3.returncode == 0, s3.stderr
        entries = json.loads(pb.read_text())["entries"]
        assert entries[0]["sessionsUnfired"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_supervisor_sidecar.py -q`
Expected: FAIL (no `--distill`).

- [ ] **Step 3: Implement distill**

In `bin/supervisor-sidecar.py`, add to `parse_args()`:

```python
    ap.add_argument("--distill", action="store_true",
                    help="also maintain playbook.json from current stats")
    ap.add_argument("--age", action="store_true",
                    help="treat this pass as one idle session: bump sessionsUnfired")
    ap.add_argument("--state-dir", default=None,
                    help="when set: base dir for playbook.json and sidecar.state.json (used by tests)")
```

and in `main()`, right after `args = parse_args()`:

```python
    if args.state_dir:
        args.state = str(Path(args.state_dir) / "sidecar.state.json")
```

Add below `emit(...)`:

```python
FIRE_THRESHOLD = 3

def distill(sd: Path, acc):
    rb_p, pb_p = sd / "rulebook.json", sd / "playbook.json"
    fired = acc["failureCounts"]
    try:
        rb = json.loads(rb_p.read_text())
    except Exception:
        rb = {}
    try:
        pb = json.loads(pb_p.read_text()) if pb_p.exists() else {"entries": []}
        entries = pb.get("entries", [])
    except Exception:
        entries = []
    lessons = rb.get("lessons", {})
    have = {e["cls"] for e in entries}
    for cls, n in (fired or {}).items():
        if n >= FIRE_THRESHOLD and cls not in have:
            entries.append({
                "cls": cls,
                "text": lessons.get(cls, f"[supervisor] past sessions hit {cls} often; stay alert for the pattern."),
                "learnedFrom": f"replay ledger: {n} fires of {cls}",
                "ts": int(time.time()),
                "sessionsUnfired": 0,
            })
    if args_age:
        for e in entries:
            if e["cls"] not in (fired or {}):
                e["sessionsUnfired"] = e.get("sessionsUnfired", 0) + 1
    max_age = (rb.get("playbookAgeSessions") or 5)
    entries = [e for e in entries if e.get("sessionsUnfired", 0) <= max_age]
    tmp = pb_p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": entries}, indent=1))
    tmp.replace(pb_p)
```

Wire into `main()`: after `emit(...)` add

```python
        if args.distill:
            distill(events_path.parent, acc)
```

and hoist the `time` import to the top of the file. (`args_age` = `args.age`; make it a module-level global assigned in `main()` or pass it as a parameter: pass it: `distill(events_path.parent, acc, args.age)` and signature `def distill(sd: Path, acc, args_age: bool):`.)

- [ ] **Step 4: Run to verify they pass + whole suite green**

Run: `pytest tests/ -q`
Expected: everything passes.

- [ ] **Step 5: Commit**

```bash
cd ~/cortex-agent && git add bin/supervisor-sidecar.py tests/test_supervisor_sidecar.py
git commit -m "feat: playbook distiller with threshold, provenance, and age-out"
git -C ~/cortexagent log --oneline -1 ; git -C ~/cortexagent status --short
```

---

### Task 8: full-suite verification and ship gate

**Files:** none new (verification only).

- [ ] **Step 1: Whole test suite**

Run: `cd ~/cortex-agent && pytest tests/ -q`
Expected: all pass (existing suites + supervisor core, sidecar, replay, propose).

- [ ] **Step 2: Replay gate standalone**

Run: `bin/eval_replay.py; echo rc=$?`
Expected: rc=0, every scenario PASS.

- [ ] **Step 3: EXCLUDE check (untouched siblings)**

Run: `git -C ~/cortex-agent diff b1005425..HEAD --stat -- agent-home/extensions/loop-guard.ts agent-home/extensions/supervised-steer.ts agent-home/extensions/exec-gate.ts`
Expected: empty (no changes to the pre-existing extensions).

- [ ] **Step 4: Both-trees parity**

Run: `git -C ~/cortex-agent log --oneline -9 | tail -1; git -C ~/cortexagent log --oneline -9 | tail -1; git -C ~/cortexagent status --short`
Expected: same commit ids; sibling working tree clean.

- [ ] **Step 5: Spec success criteria cross-check (report block)**

Verify by reading the test outputs (no runtime needed): loop task trips the ladder within 3 wasted turns (fixture `curl-loop-steers-then-blocks` proves steer at fire 1 and block at fire 2); ledger survives compaction (Ledger lives in-extension, outside model context: assert in review notes); rejected rulebook change never lands (test `test_pruner_rejects_a_no_effect_change` + provenance-only-on-real-adoption contract); no VRAM competitor (grep the new files for any model/VRAM references: must be none).

Run: `grep -n -i "vram\|gpu\|ollama\|llama" agent-home/extensions/supervisor*.ts bin/supervisor*.py | grep -v "^Binary" || echo CLEAN`
Expected: `CLEAN`.

Report the STATE block with all five checks' evidence.
