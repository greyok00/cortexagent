import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@cortexagent/coding-agent";

const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function getBaseTitle(cortex: ExtensionAPI): string {
	const cwd = path.basename(process.cwd());
	const session = cortex.getSessionName();
	return session ? `cortex - ${session} - ${cwd}` : `cortex - ${cwd}`;
}

export default function (cortex: ExtensionAPI) {
	let timer: ReturnType<typeof setInterval> | null = null;
	let frameIndex = 0;

	function stopAnimation(ctx: ExtensionContext) {
		if (timer) {
			clearInterval(timer);
			timer = null;
		}
		frameIndex = 0;
		ctx.ui.setTitle(getBaseTitle(cortex));
	}

	function startAnimation(ctx: ExtensionContext) {
		stopAnimation(ctx);
		timer = setInterval(() => {
			const frame = BRAILLE_FRAMES[frameIndex % BRAILLE_FRAMES.length];
			const cwd = path.basename(process.cwd());
			const session = cortex.getSessionName();
			const title = session ? `${frame} cortex - ${session} - ${cwd}` : `${frame} cortex - ${cwd}`;
			ctx.ui.setTitle(title);
			frameIndex++;
		}, 80);
	}

	cortex.on("agent_start", async (_event, ctx) => {
		startAnimation(ctx);
	});

	cortex.on("agent_end", async (_event, ctx) => {
		stopAnimation(ctx);
	});

	cortex.on("session_shutdown", async (_event, ctx) => {
		stopAnimation(ctx);
	});
}
