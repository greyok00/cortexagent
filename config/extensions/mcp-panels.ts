import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

const DIR = path.join(os.homedir(), ".cortex", "mcp-status");
const HIDDEN = path.join(DIR, ".hidden.json");

function readHidden(): string[] {
	try {
		return JSON.parse(fs.readFileSync(HIDDEN, "utf8"));
	} catch {
		return [];
	}
}

function writeHidden(list: string[]): void {
	fs.mkdirSync(DIR, { recursive: true });
	fs.writeFileSync(HIDDEN, JSON.stringify(list, null, 1));
}

function listPanels(): string[] {
	const names: string[] = [];
	try {
		for (const f of fs.readdirSync(DIR)) {
			if (f.endsWith(".json") && !f.startsWith(".")) {
				names.push(f.replace(/\.json$/, ""));
			}
		}
	} catch { /* dir missing */ }
	return names;
}

export default function mcpPanelsExtension(pi: ExtensionAPI): void {
	// MCP status blocks render via the daemon (none registered by default);
	// visibility stays as last written.
	void readHidden;
	void writeHidden;
	void listPanels;
	void pi;
}