
import type { ExtensionAPI } from "@cortexagent/coding-agent";
import { state } from "./lib/shared.ts";

export default function permissionsExtension(pi: ExtensionAPI): void {
	pi.registerFlag("auto-yes", {
		description: "Auto-accept all tool calls (no permission prompts)",
		type: "boolean",
		default: false,
	});

	// 2026-10-13 (owner order, ported from cloud fork): extension-registered
	// commands are disabled — /auto-yes no longer exists in the TUI. The flag
	// (--auto-yes) and the tool_call permission gate stay live.
	pi.on("tool_call", async (event, ctx) => {
		if (state.autoYes) return undefined; // never block

		if (!ctx.hasUI) return undefined;

		const input = JSON.stringify(event.input ?? {});
		const preview = input.length > 200 ? `${input.slice(0, 200)}…` : input;
		const choice = await ctx.ui.confirm(
			`Allow ${event.toolName}?`,
			`${event.toolName}(${preview})`,
		);
		if (!choice) {
			return { block: true, reason: "Blocked by user (auto-yes off)" };
		}
		return undefined;
	});
}
