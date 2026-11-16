import type { ExtensionAPI } from "@cortexagent/coding-agent";

export default function (cortex: ExtensionAPI) {
	cortex.on("agent_start", (_event, ctx) => {
		const prompt = ctx.getSystemPrompt();
		ctx.ui.setStatus("system-prompt", `System: ${prompt.length} chars`);
	});

	cortex.on("session_shutdown", (_event, ctx) => {
		ctx.ui.setStatus("system-prompt", undefined);
	});
}
