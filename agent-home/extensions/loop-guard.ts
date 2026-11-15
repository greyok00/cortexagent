// loop-guard.ts — 2026-11-11 (owner order, after the 600x identical-read loop:
// "it's looping 600 times in a row! i had to stop it manually").
//
// WHY THIS FILE EXISTS: there was no call-level loop guard in this product —
// the launcher's "loop cap" env exports matched no code (an unverified claim
// that cost a whole session). Nothing bounded identical repetitions, so a
// model stuck in a verification loop could re-issue the same tool call
// hundreds of times until a human noticed. This extension makes the cap REAL.
//
// POLICY (tiers, tuned for legitimate iterative work):
//   REISSUE-WAIT TIER (owner orders 2026-11-15, after the greysearch poll-wedge
//     where the model re-emitted the same call ~4s apart until the window cap
//     stopped the 6th, refined by the owner mid-build: "check and see if the
//     tool is doing something, not just blast it again"): an identical re-issue
//     of a recent call is HELD by the loop, not executed.
//     - MCP tools backing long jobs (greysearch deep runs) read the tool's own
//       state on disk (runs/*.json status) every few seconds: the call executes
//       the MOMENT the backing work finishes, and after WAIT_MCP (several
//       minutes) at the latest even if the run looks stuck — the recheck
//       always happens, once, with fresh state. One call at a time, never a
//       blast of five.
//     - Fast tools (shell/reads/edits) wait a short fixed window (WAIT_FAST).
//   WINDOW TIER — an exact tool call (name + serialized args) appearing more
//     than 5 times within the last 20 tool calls is a loop: blocked, with a
//     refusal that orders the model to change approach or report to the owner.
//     (Reissues are spaced out by the hold and rarely trip this; it stays as
//     the backstop.)
//   LIFETIME TIER — the exact same call blocked-or-executed 40+ times in one
//     process is pathological no matter the spacing: permanently blocked and
//     directed to end the turn and ask the owner.
//   Env overrides: CORTEXAGENT_LOOPGUARD_WINDOW / _MAX_PER_WINDOW /
//   _LIFETIME_MAX / _WAIT_FAST / _WAIT_MCP / _GREYSEARCH_RUNS_DIR.
// owner's orders: mechanical iteration never pollutes the main loop —
// when repetition is genuinely the right tool it runs in the BACKGROUND
// ((a) compound command: shell loop -> file once; (b) background subagent
// returning one final result). The refusal texts are the off-ramp — they
// teach the model WHERE repetition belongs instead of just stopping it.
import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

const WINDOW = num(process.env.CORTEXAGENT_LOOPGUARD_WINDOW, 20);
const MAX_PER_WINDOW = num(process.env.CORTEXAGENT_LOOPGUARD_MAX_PER_WINDOW, 5);
const LIFETIME_MAX = num(process.env.CORTEXAGENT_LOOPGUARD_LIFETIME_MAX, 40);
// Reissue waits: fast tools are immediate; MCP tools back long jobs (a
// greysearch deep run is several minutes) so their wait is on that scale.
const WAIT_FAST_S = num(process.env.CORTEXAGENT_LOOPGUARD_WAIT_FAST, 10);
const WAIT_MCP_S = num(process.env.CORTEXAGENT_LOOPGUARD_WAIT_MCP, 300);
// Where the greysearch MCP persists one JSON per run with a status field;
// present-state truth for the hold loop. Overridable for other installs.
const GREYSEARCH_RUNS_DIR =
	process.env.CORTEXAGENT_LOOPGUARD_GREYSEARCH_RUNS_DIR ||
	path.join(os.homedir(), "cortex-agent/mcp/greysearch/runs");

function num(raw: string | undefined, fallback: number): number {
	const v = Number(raw);
	return Number.isFinite(v) && v > 0 ? v : fallback;
}

function isMcpTool(name: string): boolean {
	return name.startsWith("mcp_");
}

// True while a greysearch deep run is genuinely still in flight, read from
// the MCP's own run registry (status: running) — not from a clock.
function greysearchBusy(): boolean {
	try {
		for (const f of fs.readdirSync(GREYSEARCH_RUNS_DIR)) {
			if (!f.startsWith("run-") || !f.endsWith(".json")) continue;
			try {
				const s = JSON.parse(fs.readFileSync(path.join(GREYSEARCH_RUNS_DIR, f), "utf8"));
				if (s && s.status === "running") return true;
			} catch { /* unreadable or mid-write → treat as no state */ }
		}
	} catch { /* no runs dir → no busy state */ }
	return false;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function loopGuard(pi: ExtensionAPI): void {
	const window: string[] = [];
	const lifetime = new Map<string, number>();
	const lastIssue = new Map<string, number>();

	pi.on("tool_call", async (event: { toolName: string; input: Record<string, unknown> }) => {
		const key = event.toolName + "::" + JSON.stringify(event.input ?? {});
		const now = Date.now();
		const life = (lifetime.get(key) ?? 0) + 1;
		lifetime.set(key, life);
		window.push(key);
		if (window.length > WINDOW) window.shift();

		const inWin = window.filter((k) => k === key).length;
		const last = lastIssue.get(key) ?? 0;

		// REISSUE-WAIT TIER: hold the repeat until the backing work is done —
		// real state for greysearch-class MCP tools, the class wait otherwise —
		// then execute the one held call as the recheck, itself, once.
		if (last > 0 && now - last < WAIT_MCP_S * 1000) {
			if (isMcpTool(event.toolName)) {
				// Hold while the run registry says work is in flight, cap at
				// the MCP wait so a stuck run can never freeze the turn.
				const cap = now + WAIT_MCP_S * 1000;
				if (greysearchBusy()) {
					while (Date.now() < cap && greysearchBusy())
						await sleep(Math.min(5000, cap - Date.now()));
				} else if (Date.now() - last < WAIT_MCP_S * 1000) {
					// No visible run state: fall back to a short settle gap
					// instead of blasting through (fast tools never reach here).
					const settled = last + 30000;
					if (settled > Date.now()) await sleep(settled - Date.now());
				}
			} else {
				const elapsed = now - last;
				if (elapsed < WAIT_FAST_S * 1000) await sleep(WAIT_FAST_S * 1000 - elapsed);
			}
		}
		lastIssue.set(key, now);

		if (life > LIFETIME_MAX) {
			return {
				block: true,
				reason:
					`refused: loop-guard — this EXACT call has been issued ${life} times this ` +
					`session (limit ${LIFETIME_MAX}). It is pathological. Do NOT reissue it, do ` +
					`NOT vary it cosmetically: END YOUR TURN and report to the owner what you ` +
					`have verified and what is blocking you, in plain text.`,
			};
		}
		if (inWin > MAX_PER_WINDOW) {
			return {
				block: true,
				reason:
					`refused: loop-guard — identical call issued ${inWin}x within the last ` +
					`${WINDOW} calls (limit ${MAX_PER_WINDOW}). The result will not change. ` +
					`The main loop must never absorb mechanical repetition. Instead: ` +
					`(a) ONE compound command with the iteration inside it (shell loop -> file, ` +
					`read the file once at the end), or (b) a BACKGROUND SUBAGENT (subagent tool, ` +
					`async) that does the repetition in its own context and returns ONE final ` +
					`summary. If neither applies, END YOUR TURN and tell the owner what you ` +
					`found and what is stuck.`,
			};
		}
	});
}
