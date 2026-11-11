// loop-guard.ts — 2026-11-11 (owner order, after the 600x identical-read loop:
// "it's looping 600 times in a row! i had to stop it manually").
//
// WHY THIS FILE EXISTS: there was no call-level loop guard in this product —
// the launcher's "loop cap" env exports matched no code (an unverified claim
// that cost a whole session). Nothing bounded identical repetitions, so a
// model stuck in a verification loop could re-issue the same tool call
// hundreds of times until a human noticed. This extension makes the cap REAL.
//
// POLICY (two tiers, tuned for legitimate iterative work):
//   WINDOW TIER  — an exact tool call (name + serialized args) appearing more
//     than 5 times within the last 20 tool calls is a loop: blocked, with a
//     refusal that orders the model to change approach or report to the owner.
//     (Iterative read→edit→re-read cycles stay legal; a true loop fills the
//     window with 20 copies and trips at the 6th.)
//   LIFETIME TIER — the exact same call blocked-or-executed 40+ times in one
//     process is pathological no matter the spacing: permanently blocked and
//     directed to end the turn and ask the owner.
//   Env overrides: CORTEXAGENT_LOOPGUARD_WINDOW / _MAX_PER_WINDOW / _LIFETIME_MAX.
// owner's order 2026-11-11: mechanical iteration never pollutes the main
// loop. When repetition is genuinely the right tool, it must run in the
// BACKGROUND and surface exactly one output:
//   (a) a compound command (shell loop -> file -> read once), or
//   (b) a background subagent (pi-subagents, async) returning one final result.
// The refusal texts are the off-ramp — they teach the model WHERE repetition
// belongs instead of just stopping it.
import type { ExtensionAPI } from "@cortexagent/coding-agent";

const WINDOW = num(process.env.CORTEXAGENT_LOOPGUARD_WINDOW, 20);
const MAX_PER_WINDOW = num(process.env.CORTEXAGENT_LOOPGUARD_MAX_PER_WINDOW, 5);
const LIFETIME_MAX = num(process.env.CORTEXAGENT_LOOPGUARD_LIFETIME_MAX, 40);

function num(raw: string | undefined, fallback: number): number {
	const v = Number(raw);
	return Number.isFinite(v) && v > 0 ? v : fallback;
}

export default function loopGuard(pi: ExtensionAPI): void {
	const window: string[] = [];
	const lifetime = new Map<string, number>();

	pi.on("tool_call", async (event: { toolName: string; input: Record<string, unknown> }) => {
		const key = event.toolName + "::" + JSON.stringify(event.input ?? {});
		lifetime.set(key, (lifetime.get(key) ?? 0) + 1);
		window.push(key);
		if (window.length > WINDOW) window.shift();

		const life = lifetime.get(key) ?? 0;
		const inWin = window.filter((k) => k === key).length;

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
