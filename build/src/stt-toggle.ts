import type { ExtensionAPI } from "@cortexagent/coding-agent";
import { execFile } from "node:child_process";

// stt-toggle.ts — 2026-11-09 (owner: "bring the stt tray back as well as
// auto on... have some sort of /disable for it"). The tray itself runs as
// the standalone stt-tray.service (/home/grey/stt-tray, faster-whisper
// local dictation); the LAUNCHER ensures it is active with a check-first
// start (never a twin). This command is the operator's honest on/off:
//
//   /stt          -> show state
//   /stt on|off   -> start/stop the service and confirm the result

const UNIT = "stt-tray.service";

function run(args: string[], timeout = 15000): Promise<string> {
	return new Promise((resolve) => {
		execFile("systemctl", ["--user", ...args], { timeout }, (err, stdout, stderr) => {
			resolve(String(stdout || "") + String(stderr || "") + (err ? ` (${err.message})` : ""));
		});
	});
}

export default function sttToggle(pi: ExtensionAPI): void {
	pi.registerCommand("stt", {
		description: "Show or toggle the STT tray (voice dictation) service",
		handler: async (ctx: { ui: { notify: (m: string, level?: string) => void } }, args?: string) => {
			const verb = String(args ?? "").trim().toLowerCase();
			if (!verb || verb === "status") {
				const st = await run(["is-active", UNIT]);
				return void ctx.ui.notify(`stt tray: ${st.trim() || "unknown"} — /stt on|off to change`, "info");
			}
			if (verb !== "on" && verb !== "off") {
				return void ctx.ui.notify("usage: /stt [on|off|status]", "warning");
			}
			const want = verb === "on" ? "start" : "stop";
			await run([want, UNIT]);
			const st = await run(["is-active", UNIT]);
			return void ctx.ui.notify(`stt tray ${want}: now ${st.trim() || "unknown"}`, "info");
		},
	});
}
