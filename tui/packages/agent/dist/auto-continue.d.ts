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
export declare function autoContinueMax(): number;
/**
 * True when an assistant message that issued no tool call is telling the user
 * about work it is about to do rather than reporting work it has done.
 */
export declare function isUnfinishedAnnouncement(text: string | undefined | null): boolean;
/** Collect the assistant's visible text, ignoring thinking blocks and tool calls. */
export declare function assistantText(content: ReadonlyArray<{
    type?: string;
    text?: string;
}> | undefined): string;
/**
 * The nudge itself. Addressed as the user because that is the only voice the
 * model is trained to obey, and explicit about the two acceptable answers so a
 * compliant model does not answer by announcing again.
 */
export declare function buildAutoContinueNudge(attempt: number, max: number): string;
//# sourceMappingURL=auto-continue.d.ts.map