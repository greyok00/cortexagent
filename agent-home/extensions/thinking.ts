
import type { ExtensionAPI, ExtensionContext } from "@cortexagent/coding-agent";
import { Key } from "@cortexagent/tui";
import { state } from "./lib/shared.ts";

const LEVELS = ["aggressive", "balanced", "preserve"] as const;
type Level = (typeof LEVELS)[number];

const LEVEL_HINT: Record<Level, string> = {
	aggressive: "aggressive (~20 words; strip everything but the ask)",
	balanced: "balanced (~50 words; tight business prose, default)",
	preserve: "preserve (~150 words; light cleanup only)",
};

export default function thinkingExtension(pi: ExtensionAPI): void {
	function cycleThinking(ctx: ExtensionContext): void {
		const idx = LEVELS.indexOf(state.thinking);
		state.thinking = LEVELS[(idx + 1) % LEVELS.length];
		ctx.ui.notify(
			`Thinking: ${state.thinking} — ${LEVEL_HINT[state.thinking]}`,
			"info",
		);
	}

	// 2026-10-13 (owner order, ported from cloud fork): extension-registered
	// commands are disabled — /thinking and ctrl+shift+x no longer exist in the
	// TUI. The before_agent_start hook stays (system-prompt level note).
	void cycleThinking;

	pi.on("before_agent_start", async (_event, ctx) => {
		const current = ctx.getSystemPrompt();
		return {
			systemPrompt:
				`${current}\n\n[THINKING LEVEL: ${state.thinking}]\n` +
				`${LEVEL_HINT[state.thinking]}`,
		};
	});
}
