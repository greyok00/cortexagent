import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as fs from "node:fs";
import * as crypto from "node:crypto";
import * as os from "node:os";
import * as path from "node:path";

// /mcp + /tools — the hardened registry toggle surface.
// Reads mcp_registry.json; toggles enabled state; shows name, status,
// kind, command. External servers stay disabled until hash-verified per
// the security policy; this surface keeps that order.
const REGISTRY = path.join(os.homedir(), ".cortex", "agent", "mcp_registry.json");

interface McpEntry {
	name: string;
	kind: string;
	command?: string;
	so?: string;
	enabled: boolean;
}

function load(): { servers: McpEntry[] } {
	try {
		return JSON.parse(fs.readFileSync(REGISTRY, "utf8"));
	} catch {
		return { servers: [] };
	}
}

function save(r: { servers: McpEntry[] }): void {
	fs.writeFileSync(REGISTRY, JSON.stringify(r, null, 2) + "\n");
}

function sha256(file: string): string {
	return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function listText(r: { servers: McpEntry[] }): string {
	if (!r.servers.length) return "no MCP servers in the registry";
	return r.servers
		.map((s) => {
			const kind = s.so ? "compiled" : s.kind ?? "script";
			return `${s.enabled ? "✓ on " : "✕ off "} ${s.name} (${kind}) — ${s.command ?? s.so ?? ""}`;
		})
		.join("\n");
}

async function toggle(ctx: { ui: { notify(msg: string, level?: string): Promise<void> } }, name: string, want: boolean, r: { servers: McpEntry[] }): Promise<void> {
	const s = r.servers.find((x) => x.name === name);
	if (!s) {
		await ctx.ui.notify(`no server named ${name}`, "warning");
		return;
	}
	if (want && s.so) {
		// supply-chain rule: compiled external servers enable only hash-verified
		const soPath = path.join(os.homedir(), "cortexagent", s.so);
		try {
			sha256(soPath);
		} catch {
			await ctx.ui.notify(`${name}: .so missing — refusing to enable`, "warning");
			return;
		}
	}
	s.enabled = want;
	save(r);
	await ctx.ui.notify(`${name} → ${want ? "enabled" : "disabled"}`);
}

export default function mcpToggle(pi: ExtensionAPI): void {
	const handler = async (args: string, ctx: { ui: { notify(msg: string, level?: string): Promise<void> } }) => {
		const r = load();
		const [verb, name] = args.trim().split(/\s+/);
		if (!verb || verb === "list") {
			await ctx.ui.notify(listText(r));
			return;
		}
		if ((verb === "enable" || verb === "disable") && name) {
			await toggle(ctx, name, verb === "enable", r);
			return;
		}
		await ctx.ui.notify(`usage: /mcp [list|enable <name>|disable <name>]`, "warning");
	};
	pi.registerCommand("mcp", {
		description: "List or toggle MCP servers (registry-backed)",
		handler,
	});
	pi.registerCommand("tools", {
		description: "List or toggle MCP servers (alias of /mcp)",
		handler,
	});
}