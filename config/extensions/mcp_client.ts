import type { ExtensionAPI } from "@cortexagent/coding-agent";
import * as childProcess from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// attach the family's MCP servers as REAL tools.
// Security model — nothing auto-installs, nothing enters unlisted:
// - only servers listed in ~/.cortex/agent/mcp_registry.json run,
// - only when enabled:true (compiled .so servers enable only after the
// hash rule /mcp enforces — this client never bypasses it),
// - the spawned process is the registry's own command line — no downloads,
// no external tool catalogs, at ANY point.
// Protocol: JSON-RPC 2.0 over stdio (initialize → initialized → tools/list,
// then tools/call per invocation), the MCP standard subset a converted
// server needs — no third-party client library in the TUI.

// Env-driven paths: the registry and root can be set externally
// (CORTEXAGENT_MCP_CONFIG / CORTEXAGENT_ROOT); the defaults below apply
// when neither is set.
const REGISTRY = process.env.CORTEXAGENT_MCP_CONFIG ?? path.join(os.homedir(), ".cortex", "agent", "mcp_registry.json");
const ROOT = process.env.CORTEXAGENT_ROOT ?? path.join(os.homedir(), "cortexagent");

interface RegistryServer {
	name: string;
	kind?: string;
	command?: string;
	so?: string;
	enabled: boolean;
	// per-suite tool slice — when present, only
	// these server tools register in this session (web registers all).
	tools?: string[];
}

interface McpServerConn {
	server: string;
	proc: childProcess.ChildProcess;
	nextId: number;
	pending: Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>;
	buffer: string;
	tools: { name: string; description?: string; inputSchema?: Record<string, unknown> }[];
}

function spawnServer(entry: RegistryServer): McpServerConn | null {
	const cmd = entry.command ?? (entry.so ? `python3 ${ROOT}/mcp/run_server.py --server ${entry.so.replace(/^.*[/\\]mcp\/|\.cpython.*$/g, "")}` : "");
	if (!cmd) return null;
	const proc = childProcess.spawn("/bin/sh", ["-c", cmd], {
		cwd: ROOT,
		stdio: ["pipe", "pipe", "pipe"],
	});
	const conn: McpServerConn = {
		server: entry.name,
		proc,
		nextId: 1,
		pending: new Map(),
		buffer: "",
		tools: [],
	};
	// Detach immediately: without this the child's open pipes keep the node
	// event loop alive after every print/exit (the exact -p exit hang).
	proc.unref();
	proc.stdio.forEach((s) => s && s.unref());
	proc.stdout!.on("data", (chunk: Buffer) => {
		conn.buffer += chunk.toString();
		let nl: number;
		while ((nl = conn.buffer.indexOf("\n")) !== -1) {
			const line = conn.buffer.slice(0, nl).trim();
			conn.buffer = conn.buffer.slice(nl + 1);
			if (!line) continue;
			try {
				const msg = JSON.parse(line);
				const id = msg.id as number | undefined;
				if (id !== undefined && conn.pending.has(id)) {
					const p = conn.pending.get(id)!;
					conn.pending.delete(id);
					if (msg.error) p.reject(new Error(String(msg.error.message ?? JSON.stringify(msg.error))));
					else p.resolve(msg.result);
				}
			} catch {
				/* non-JSON line — servers may log; ignore */
			}
		}
	});
	proc.stderr?.on("data", () => undefined);
	// A past defect: a dead server must not leave
	// pending promises waiting for their own 60–300 s timers.
	proc.on("exit", () => {
		for (const [, p] of conn.pending) {
			try { p.reject(new Error(`${entry.name}: server process exited`)); } catch {}
		}
		conn.pending.clear();
	});
	return conn;
}

async function handshake(entry: RegistryServer, conn: McpServerConn): Promise<void> {
	await call(conn, "initialize", {
		protocolVersion: "2024-11-05",
		capabilities: {},
		clientInfo: { name: "cortex", version: "0.7.5.1" },
	}, 15000);
	conn.proc.stdin!.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
	const listed = (await call(conn, "tools/list", {}, 15000)) as { tools?: { name: string; description?: string; inputSchema?: Record<string, unknown> }[] };
	logLine(entry.name + " tools=" + (listed.tools ?? []).map((t) => t.name).join(","));
	conn.tools = listed.tools ?? [];
}

function call(conn: McpServerConn, method: string, params: unknown, timeoutMs = 60000): Promise<unknown> {
	const id = conn.nextId++;
	const body = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n";
	return new Promise((resolve, reject) => {
		const timer = setTimeout(() => {
			conn.pending.delete(id);
			reject(new Error(`${conn.server}: ${method} timed out`));
		}, timeoutMs);
		conn.pending.set(id, {
			resolve: (v) => {
				clearTimeout(timer);
				resolve(v);
			},
			reject: (e: Error) => {
				clearTimeout(timer);
				reject(e);
			},
		});
		// A past defect: a write error (dead pipe / EPIPE) used to
		// swallow the request silently — the promise just hung until timeout.
		// Reject every pending call when stdin surfaces an error.
		conn.proc.stdin!.write(body, (err: Error | null | undefined) => {
			if (err) {
				for (const [, p] of conn.pending) {
					try { p.reject(new Error(`${conn.server}: request write failed: ${err.message}`)); } catch {}
				}
				conn.pending.clear();
			}
		});
	});
}

function textOf(result: unknown): string {
	const r = result as { content?: { type?: string; text?: string }[]; isError?: boolean } | null;
	if (!r || !Array.isArray(r.content)) return JSON.stringify(result ?? null);
	return r.content
		.map((c) => (c.type === "text" ? String(c.text ?? "") : JSON.stringify(c)))
		.join("\n");
}

function logLine(m: string): void {
	try {
		fs.appendFileSync("/tmp/mcp_client.log", new Date().toISOString() + " " + m + "\n");
	} catch {}
}

export default function mcpClient(pi: ExtensionAPI): void {
	logLine("extension loaded");
	const registry: { servers: RegistryServer[] } = (() => {
		try {
			return JSON.parse(fs.readFileSync(REGISTRY, "utf8"));
		} catch {
			return { servers: [] };
		}
	})();
	const conns: McpServerConn[] = [];

	logLine("registry servers=" + JSON.stringify(registry.servers.map((s) => [s.name, s.enabled])));
	for (const entry of registry.servers) {
		if (entry.name === "greysearch_mcp") continue; // registered once by the mcp.json entry — no duplicate
		if (!entry.enabled || !entry.command) continue;
		let conn: McpServerConn;
		try {
			const spawned = spawnServer(entry);
			if (!spawned) continue;
			conn = spawned;
			logLine("spawned " + entry.name + " pid=" + (conn.proc.pid ?? null));
		} catch (e) {
			logLine("spawn error " + String(e));
			continue;
		}
		void (async () => {
			try {
				await handshake(entry, conn);
				for (const t of (entry.tools
					? conn.tools.filter((lt) => entry.tools!.includes(lt.name))
					: conn.tools) ?? []) {
					const toolName = `mcp_${entry.name}_${t.name}`;
					pi.registerTool({
						name: toolName,
						label: toolName,
						description: `[${entry.name} MCP] ${t.description ?? t.name}`,
						parameters: (t.inputSchema ?? { type: "object", properties: {} }) as never,
						prepareArguments: (args) => args as never,
						execute: async (_id, params) => {
							// Per-tool call-ceiling overrides, env-driven: set
							// CORTEXAGENT_TOOL_TIMEOUTS to a JSON object mapping tool
							// name to ms. Long-running local pipeline tools can raise
							// the default 420s ceiling per tool without code changes.
							const TOOL_TIMEOUT_MS: Record<string, number> = (() => {
								try {
									const raw = JSON.parse(process.env.CORTEXAGENT_TOOL_TIMEOUTS ?? "{}") as Record<string, number>;
									return raw && typeof raw === "object" ? raw : {};
								} catch { return {}; }
							})();
							// A past defect: a spawned server that died
							// mid-session used to keep swallowing calls — respawn +
							// re-handshake on demand instead.
							if (conn.proc.exitCode !== null) {
								try { conn.proc.kill(); } catch {}
								const fresh = spawnServer(entry);
								if (!fresh) {
									return { content: [{ type: "text", text: `${entry.name}: server process died and could not be respawned` }] };
								}
								Object.assign(conn, fresh);
								await handshake(entry, conn);
							}
							const res = await call(conn, "tools/call", { name: t.name, arguments: params ?? {} }, TOOL_TIMEOUT_MS[t.name] ?? 420_000);
							return {
								content: [{ type: "text", text: textOf(res) }],
								details: { server: entry.name, tool: t.name },
							};
						},
					});
				}
			} catch (e) {
				logLine("handshake error " + String(e));
			}
		})();
		conns.push(conn);
	}
	// Open child stdio pipes keep node's event
	// loop alive forever — print mode generated its answer and then never
	// exited. Detach the handles AND reap the servers on session shutdown.
	pi.on("session_shutdown", () => {
		for (const conn of conns) {
			try { conn.proc.stdin?.destroy(); conn.proc.stdout?.destroy(); conn.proc.stderr?.destroy(); } catch {}
			try { conn.proc.kill("SIGKILL"); } catch {}
		}
	});
	for (const conn of conns) {
		try { conn.proc.stdio.forEach((s) => s && s.unref()); conn.proc.unref(); } catch {}
	}
}