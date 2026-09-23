import type { ExtensionAPI } from "@cortex/coding-agent";

const REPO_ROOT = "/home/grey/cortexagent";
const PY = "python3";

async function runPy(code: string, args: string[]): Promise<string> {
	try {
		const { execFile } = await import("node:child_process");
		const { promisify } = await import("node:util");
		const run = promisify(execFile);
		const { stdout } = await run(PY, ["-c", code, ...args], {
			timeout: 15_000,
			env: { ...process.env, PYTHONPATH: REPO_ROOT },
		});
		return stdout;
	} catch (err) {
		// Never silently swallow memory failures again — log to stderr so the
		// session log shows why memory injection is missing.
		process.stderr.write(`[memory-ext] ${err}\n`);
		return "";
	}
}

// API (lib/memory_thin.py): append(content, role="user", *, session=…)
async function savePrompt(prompt: string): Promise<void> {
	if (!prompt.trim()) return;
	await runPy(
		"from lib.memory_thin import append; append(__import__('sys').argv[1], 'user')",
		[prompt],
	);
}

// API: read_last(n) — no platform kwarg (that call used to TypeError every time,
// which silently killed memory injection: session resume had zero memory).
async function readRecent(n: number): Promise<string> {
	return runPy(
		"import json,sys; from lib.memory_thin import read_last; " +
			"print(json.dumps(read_last(int(sys.argv[1]))))",
		[String(n)],
	);
}

// Append what the agent actually DID this agent run (last assistant text +
// tool names), so resume knows what happened, not just what was asked.
async function saveRunSummary(messages: unknown[]): Promise<void> {
	try {
		let lastText = "";
		const tools: string[] = [];
		for (const m of messages as Array<{ role?: string; content?: unknown }>) {
			if (m.role === "assistant" && Array.isArray((m as { content?: unknown[] }).content)) {
				const content = (m as { content: Array<{ type?: string; text?: string; name?: string }> }).content;
				for (const c of content) {
					if (c.type === "text" && c.text?.trim()) lastText = c.text;
					if (c.type === "toolCall" || c.type === "toolUse") {
						const name = (c as { name?: string }).name ?? (c as { toolName?: string }).toolName;
						if (name) tools.push(name);
					}
				}
			}
		}
		const summary = lastText.trim().slice(0, 600) || "(no text output)";
		const line = `[run] tools: ${tools.slice(-12).join(",") || "none"}\n[run] last output: ${summary}`;
		await runPy("from lib.memory_thin import append; append(__import__('sys').argv[1], 'assistant')", [line]);
	} catch {
		// never block the session on memory writes
	}
}

// Legacy hot-memory rows were written with role/content swapped
// ({"role": <prompt>, "content": "user"}) — normalize on read.
function formatMemory(raw: string): string {
	try {
		const entries = JSON.parse(raw) as Array<{ role?: string; content?: string; timestamp?: string }>;
		if (!entries.length) return "";
		const lines = entries
			.map((e) => {
				let { role, content } = e;
				if (role && !["user", "assistant", "system"].includes(role) && content === "user") {
					[role, content] = [content, role];
				}
				const text = (content ?? "").slice(0, 500);
				const ts = (e.timestamp ?? "").slice(0, 16);
				return `[${ts}] ${role}: ${text}`;
			})
			.join("\n");
		return `\n\n<recent_memory>\n${lines}\n</recent_memory>`;
	} catch {
		return "";
	}
}

export default function memoryExtension(pi: ExtensionAPI): void {
	let injected = false;
	pi.on("before_agent_start", async (event) => {
		const prompt = event.prompt;
		if (typeof prompt === "string" && prompt.trim()) {
			void savePrompt(prompt);
		}

		if (injected) return;
		injected = true;

		const memory = formatMemory(await readRecent(12));
		if (!memory) return;
		const current = event.systemPrompt ?? "";
		return { systemPrompt: current + memory };
	});

	pi.on("agent_end", async (event) => {
		void saveRunSummary(event.messages ?? []);
	});
}