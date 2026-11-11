import { ProcessTerminal } from "../src/terminal.ts";
import type { Component, TUI } from "../src/tui.ts";
import { TuiMainScreen } from "../src/tui-main-screen.ts";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

class Lines implements Component {
	private lines: string[] = [];

	set(lines: string[]): void {
		this.lines = lines;
	}

	append(lines: string[]): void {
		this.lines.push(...lines);
	}

	render(width: number): string[] {
		return this.lines.map((line) => {
			if (line.length > width) return line.slice(0, width);
			return line.padEnd(width, " ");
		});
	}

	invalidate(): void {}
}

async function streamLines(buffer: Lines, label: string, count: number, delayMs: number, ui: TUI): Promise<void> {
	for (let i = 1; i <= count; i += 1) {
		buffer.append([`${label} ${String(i).padStart(2, "0")}`]);
		ui.requestRender();
		await sleep(delayMs);
	}
}

async function main(): Promise<void> {
	const ui: TUI = new TuiMainScreen(new ProcessTerminal());
	const buffer = new Lines();
	ui.addChild(buffer);
	ui.start();

	const height = ui.terminal.rows;
	const preCount = height + 8;
	const toolCount = height + 12;
	const postCount = 6;

	buffer.set([
		"TUI viewport overwrite repro",
		`Viewport rows detected: ${height}`,
		"(Resize to ~8-12 rows for best repro)",
		"",
		"=== PRE-TOOL STREAM ===",
	]);
	ui.requestRender();
	await sleep(300);

	await streamLines(buffer, "PRE-TOOL LINE", preCount, 30, ui);

	buffer.append(["", "--- TOOL CALL START ---", "(pause...)", ""]);
	ui.requestRender();
	await sleep(700);

	await streamLines(buffer, "TOOL OUT", toolCount, 20, ui);

	buffer.append(["", "=== POST-TOOL STREAM ==="]);
	ui.requestRender();
	await sleep(300);
	await streamLines(buffer, "POST-TOOL LINE", postCount, 40, ui);

	await sleep(1500);
	ui.stop();
}

main().catch((error) => {
	try {
		const ui: TUI = new TuiMainScreen(new ProcessTerminal());
		ui.stop();
	} catch {
		// Ignore restore errors.
	}
	process.stderr.write(`${String(error)}\n`);
	process.exitCode = 1;
});
