/**
 * Auto-continue on an unfinished announcement.
 *
 * The problem this solves (owner report 2026-09-27: "it'll usually output a
 * text string saying it's about to do something but then stop completely"):
 * the local model sometimes answers with a plan-shaped sentence — "I'll retry
 * and start the hotspot once it's back up.", "I'm going to pair Wolf and Parrot
 * now.", "Let me check the status:" — and issues NO tool call. A turn with no
 * tool call is how a run ends, so the agent halts mid-task having told the user
 * what it was about to do. Nothing was broken in the tool layer; the harness
 * simply had no answer for a turn that announces work instead of doing it.
 *
 * The fix is a bounded nudge: when a turn ends like that, push one user-role
 * message telling the model to either act now with a tool call or state that it
 * is finished, and keep the loop alive. The budget (default 2 per run) is what
 * keeps this from becoming the very loop it is meant to cure — a model that
 * keeps announcing and never acting gets its two chances and then the run ends
 * exactly as before.
 *
 * Detection is deliberately conservative: a false negative leaves the old
 * behaviour (run ends), a false positive spends one extra model turn. Anything
 * that reads as a finished report or a question back to the user is a false
 * positive we refuse to make.
 */

/** How many nudges a single run may spend. 0 disables the behaviour. */
export function autoContinueMax(): number {
	const raw = process.env.CORTEXAGENT_AUTO_CONTINUE_MAX;
	if (raw === undefined) return 2;
	const parsed = Number.parseInt(raw, 10);
	if (!Number.isFinite(parsed) || parsed < 0) return 2;
	return parsed;
}

/** Announcing an action that is about to happen — the shape that stalls a run. */
const ANNOUNCEMENT = new RegExp(
	[
		"\\b(?:let me|let's|lets)\\b",
		"\\bi(?:'|’)?ll\\b", // I'll
		"\\bi will\\b",
		"\\bi(?:'|’)?m going to\\b",
		"\\bi am going to\\b",
		"\\bi(?:'|’)?m about to\\b",
		"\\bi am about to\\b",
		"\\bnow i\\b",
		"\\bnext,? i\\b",
		"\\bgoing to (?:try|run|check|start|do|test|retry|continue|go)\\b",
	].join("|"),
	"i",
);

/** Handing the decision back to the user — never nudge on this. */
const HANDOFF =
	/\b(?:let me know|want me to|would you like|do you want|should i|your call|up to you|if you(?:'|’)?d like)\b/i;

/** Reads as a finished report. */
const COMPLETION =
	/\b(?:all done|done|complete|completed|finished|that(?:'|’)?s it|summary|recap|nothing (?:left|else) to do)\b/i;

/**
 * True when an assistant message that issued no tool call is telling the user
 * about work it is about to do rather than reporting work it has done.
 */
export function isUnfinishedAnnouncement(text: string | undefined | null): boolean {
	if (!text) return false;
	const body = text.trim();
	if (!body) return false;

	// A question back to the user is a legitimate reason to end the turn.
	if (body.endsWith("?")) return false;

	// Look at the tail: an announcement is the last thing said, and a long
	// message's opening rarely describes what it is about to do next.
	const tail = body.slice(-400);
	if (HANDOFF.test(tail)) return false;
	if (COMPLETION.test(tail)) return false;
	if (!ANNOUNCEMENT.test(tail)) return false;

	return true;
}

/** Collect the assistant's visible text, ignoring thinking blocks and tool calls. */
export function assistantText(content: ReadonlyArray<{ type?: string; text?: string }> | undefined): string {
	if (!content) return "";
	return content
		.filter((part) => part?.type === "text" && typeof part.text === "string")
		.map((part) => part.text as string)
		.join("\n")
		.trim();
}

/**
 * The nudge itself. Addressed as the user because that is the only voice the
 * model is trained to obey, and explicit about the two acceptable answers so a
 * compliant model does not answer by announcing again.
 */
export function buildAutoContinueNudge(attempt: number, max: number): string {
	return (
		`[harness] Your previous turn announced an action but issued no tool call, so the run ` +
		`ended before it happened (auto-continue ${attempt}/${max}). Do exactly one of these two ` +
		`things in THIS turn: (1) if the task is not finished, perform that action now — emit the ` +
		`tool call, do not describe it; or (2) if it IS finished, reply with the result only, with ` +
		`no announcement, no plan and no "let me" phrasing. Do not ask the user to confirm work ` +
		`that was already requested.`
	);
}
