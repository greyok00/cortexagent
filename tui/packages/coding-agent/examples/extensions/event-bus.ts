import type { ExtensionAPI, ExtensionContext } from "@cortexagent/coding-agent";

export default function (cortex: ExtensionAPI) {
	let currentCtx: ExtensionContext | undefined;

	cortex.on("session_start", async (_event, ctx) => {
		currentCtx = ctx;
	});

	cortex.events.on("my:notification", (data) => {
		const { message, from } = data as { message: string; from: string };
		currentCtx?.ui.notify(`Event from ${from}: ${message}`, "info");
	});

	cortex.registerCommand("emit", {
		description: "Emit my:notification event (usage: /emit message)",
		handler: async (args, _ctx) => {
			const message = args.trim() || "hello";
			cortex.events.emit("my:notification", { message, from: "/emit command" });
			// Listener above will show the notification
		},
	});

	cortex.on("session_start", async () => {
		cortex.events.emit("my:notification", {
			message: "Session started",
			from: "event-bus-example",
		});
	});
}
