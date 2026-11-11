
import type { ExtensionAPI, ExtensionContext } from "@cortexagent/coding-agent";
import { Key } from "@cortexagent/tui";
import { state } from "./lib/shared.ts";

const WRITE_TOOLS = new Set(["edit", "write"]);
const MODES = ["auto", "plan", "normal"] as const;
type Mode = (typeof MODES)[number];

export default function modesExtension(pi: ExtensionAPI): void {
	pi.registerFlag("plan", {
		description: "Start in plan mode (read-only exploration)",
		type: "boolean",
		default: false,
	});

	function applyMode(ctx: ExtensionContext): void {
		state.autoYes = state.mode === "auto";
		const active = pi.getActiveTools();
		if (state.mode === "plan") {
			pi.setActiveTools(active.filter((name) => !WRITE_TOOLS.has(name)));
		} else {
			const all = pi.getAllTools().map((t) => t.name);
			const missing = [...WRITE_TOOLS].filter((t) => !active.includes(t) && all.includes(t));
			if (missing.length > 0) {
				pi.setActiveTools([...active, ...missing]);
			}
		}
		ctx.ui.notify(`Mode: ${state.mode}`, "info");
	}

	function cycleMode(ctx: ExtensionContext): void {
		const idx = MODES.indexOf(state.mode);
		state.mode = MODES[(idx + 1) % MODES.length];
		applyMode(ctx);
	}

	// 2026-10-13 (owner order, ported from cloud fork): extension-registered
	// commands are disabled — /mode and ctrl+shift+tab no longer exist in the
	// TUI. Plan mode still engages via session_start flag + tool_call hook.
	void cycleMode;

	pi.on("tool_call", async (event) => {
		if (state.mode !== "plan") return undefined;
		if (WRITE_TOOLS.has(event.toolName)) {
			return {
				block: true,
				reason: `Plan mode: ${event.toolName} is disabled. Ctrl+Shift+Tab to leave plan mode.`,
			};
		}
		return undefined;
	});

	pi.on("before_agent_start", async () => {
		if (state.mode !== "plan") return;
		return {
			message: {
				customType: "cortexagent-plan-mode",
				content: `[PLAN MODE ACTIVE]
You are in plan mode — read-only exploration. Write tools (edit/write) are disabled.
Explore the codebase, ask clarifying questions, and produce a numbered plan under a
"Plan:" header. Do NOT attempt to make changes.`,
				display: false,
			},
		};
	});

	pi.on("session_start", async (_event, ctx) => {
		if (pi.getFlag("plan") === true) {
			state.mode = "plan";
		}
		applyMode(ctx);
	});
}
