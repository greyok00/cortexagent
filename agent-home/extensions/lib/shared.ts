// 2026-10-14: recreated — extensions/lib/ was lost during the boot-file
// removal; modes.ts, permissions.ts and thinking.ts all import `state` from
// "./lib/shared.ts", which made every cortex launch print three load errors.

type Mode = "auto" | "plan" | "normal";
type ThinkingLevel = "aggressive" | "balanced" | "preserve";

export interface SharedState {
	mode: Mode;
	autoYes: boolean;
	thinking: ThinkingLevel;
}

export const state: SharedState = {
	// 2026-10-14 (owner order): auto-yes by default — never prompt per tool
	// call. "auto" is the designed auto-yes mode (permissions.ts gate reads
	// this; modes.ts session_start re-applies mode === "auto" → autoYes true).
	// --plan still switches this to plan at session_start.
	mode: "auto",
	autoYes: true,
	thinking: "balanced",
};