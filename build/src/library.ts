import type { ExtensionAPI } from "@greyagent/coding-agent";
import { execFile } from "node:child_process";

// library.ts — 2026-11-10 (owner: quick easy access to the knowledge library
// produced by kb-ingestor + greysearch, with the ui framework themes): the
// greysearch portal renders the whole library at http://127.0.0.1:8792
// (loopback only). /library opens it in the browser, starting the local
// portal first if it isn't listening. Theme switch lives on the library page
// itself (◐ button, obsidian ⇄ paper), persisted in localStorage.

const PORT = 8792; // 8791 is the sibling portal — cortex-agent serves its OWN on 8792 (loopback)
const URL_ = `http://127.0.0.1:${PORT}/library.html`;

function run(args: string[], timeout = 20000): Promise<string> {
	return new Promise((resolve) => {
		execFile("sh", ["-c", args.join(" ")], { timeout }, (err, stdout, stderr) => {
			resolve(String(stdout || "") + String(stderr || "") + (err ? ` (${err.message})` : ""));
		});
	});
}

export default function library(pi: ExtensionAPI): void {
	pi.registerCommand("library", {
		description: "Open the knowledge library UI (starts the loopback portal on 8791 if needed)",
		handler: async (ctx: { ui: { notify: (m: string, level?: string) => void } }) => {
			const up = await run([
				`ss -ltn | grep -q ':${PORT} ' && echo UP || echo DOWN`,
			]);
			if (!up.includes("UP")) {
				await run([
					`GREYSEARCH_PORTAL_PORT=8792 GREYSEARCH_PORTAL_HOST=127.0.0.1 nohup python3 "${HOME}/cortex-agent"/mcp/greysearch/portal_server.py`,
					`>> "${HOME}/cortex-agent"/state/logs/library-portal.log 2>&1 &`,
				]);
				await new Promise<void>((r) => setTimeout(r, 2500));
			}
			const check = await run([`ss -ltn | grep -q ':${PORT} ' && echo UP || echo DOWN`]);
			if (!check.includes("UP")) {
				return void ctx.ui.notify(`library: portal failed to start on :${PORT} — see state/logs/library-portal.log`, "warning");
			}
			await run(["xdg-open", URL_]);
			return void ctx.ui.notify(`library: ${URL_} — theme switch (obsidian ⇄ paper) is the ◐ button on the page`, "info");
		},
	});
}
