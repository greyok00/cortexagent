import type { ExtensionAPI } from "@cortexagent/coding-agent";
import { Box, Text } from "@cortexagent/tui";

export default function (cortex: ExtensionAPI) {
	cortex.registerMessageRenderer("status-update", (message, { expanded, outputPad }, theme) => {
		const details = message.details as { level: string; timestamp: number } | undefined;
		const level = details?.level ?? "info";

		const color = level === "error" ? "error" : level === "warn" ? "warning" : "success";
		const prefix = theme.fg(color, `[${level.toUpperCase()}]`);

		let text = `${prefix} ${message.content}`;

		if (expanded && details?.timestamp) {
			const time = new Date(details.timestamp).toLocaleTimeString();
			text += `\n${theme.fg("dim", `  at ${time}`)}`;
		}

		const box = new Box(outputPad, 1, (t) => theme.bg("customMessageBg", t));
		box.addChild(new Text(text, 0, 0));
		return box;
	});

	cortex.registerCommand("status", {
		description: "Send a status message (usage: /status [warn|error] message)",
		handler: async (args, _ctx) => {
			const parts = args.trim().split(/\s+/);
			let level = "info";
			let content = args.trim();

			if (parts[0] === "warn" || parts[0] === "error") {
				level = parts[0];
				content = parts.slice(1).join(" ") || "Status update";
			}

			cortex.sendMessage({
				customType: "status-update",
				content,
				display: true,
				details: { level, timestamp: Date.now() },
			});
		},
	});
}
