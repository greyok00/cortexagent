import { spawnSync } from "node:child_process";
import type { ExtensionAPI } from "@cortexagent/coding-agent";

const DEFAULT_INTERACTIVE_COMMANDS = [
	"vim",
	"nvim",
	"vi",
	"nano",
	"emacs",
	"pico",
	"micro",
	"helix",
	"hx",
	"kak",

	"less",
	"more",
	"most",

	"git commit",
	"git rebase",
	"git merge",
	"git cherry-pick",
	"git revert",
	"git add -p",
	"git add --patch",
	"git add -i",
	"git add --interactive",
	"git stash -p",
	"git stash --patch",
	"git reset -p",
	"git reset --patch",
	"git checkout -p",
	"git checkout --patch",
	"git difftool",
	"git mergetool",

	"htop",
	"top",
	"btop",
	"glances",

	"ranger",
	"nnn",
	"lf",
	"mc",
	"vifm",

	"tig",
	"lazygit",
	"gitui",

	"fzf",
	"sk",

	"ssh",
	"telnet",
	"mosh",

	"psql",
	"mysql",
	"sqlite3",
	"mongosh",
	"redis-cli",

	"kubectl edit",
	"kubectl exec -it",
	"docker exec -it",
	"docker run -it",

	"tmux",
	"screen",
	"ncdu",
];

function getInteractiveCommands(): string[] {
	const additional =
		process.env.INTERACTIVE_COMMANDS?.split(",")
			.map((s) => s.trim())
			.filter(Boolean) ?? [];
	const excluded = new Set(process.env.INTERACTIVE_EXCLUDE?.split(",").map((s) => s.trim().toLowerCase()) ?? []);
	return [...DEFAULT_INTERACTIVE_COMMANDS, ...additional].filter((cmd) => !excluded.has(cmd.toLowerCase()));
}

function isInteractiveCommand(command: string): boolean {
	const trimmed = command.trim().toLowerCase();
	const commands = getInteractiveCommands();

	for (const cmd of commands) {
		const cmdLower = cmd.toLowerCase();

		if (trimmed === cmdLower || trimmed.startsWith(`${cmdLower} `) || trimmed.startsWith(`${cmdLower}\t`)) {
			return true;
		}

		const pipeIdx = trimmed.lastIndexOf("|");
		if (pipeIdx !== -1) {
			const afterPipe = trimmed.slice(pipeIdx + 1).trim();
			if (afterPipe === cmdLower || afterPipe.startsWith(`${cmdLower} `)) {
				return true;
			}
		}
	}
	return false;
}

export default function (cortex: ExtensionAPI) {
	cortex.on("user_bash", async (event, ctx) => {
		let command = event.command;
		let forceInteractive = false;

		if (command.startsWith("i ") || command.startsWith("i\t")) {
			forceInteractive = true;
			command = command.slice(2).trim();
		}

		const shouldBeInteractive = forceInteractive || isInteractiveCommand(command);
		if (!shouldBeInteractive) {
			return;
		}

		if (ctx.mode !== "tui") {
			return {
				result: { output: "(interactive commands require TUI)", exitCode: 1, cancelled: false, truncated: false },
			};
		}

		const exitCode = await ctx.ui.custom<number | null>((tui, _theme, _kb, done) => {
			tui.stop();

			process.stdout.write("\x1b[2J\x1b[H");

			const shell = process.env.SHELL || "/bin/sh";
			const result = spawnSync(shell, ["-c", command], {
				stdio: "inherit",
				env: process.env,
			});

			tui.start();
			tui.requestRender(true);

			done(result.status);

			return { render: () => [], invalidate: () => {} };
		});

		const output =
			exitCode === 0
				? "(interactive command completed successfully)"
				: `(interactive command exited with code ${exitCode})`;

		return {
			result: {
				output,
				exitCode: exitCode ?? 1,
				cancelled: false,
				truncated: false,
			},
		};
	});
}
