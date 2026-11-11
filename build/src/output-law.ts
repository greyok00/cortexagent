import type { ExtensionAPI } from "@cortexagent/coding-agent";

// output-law.ts — 2026-11-10 owner: beautification ON BY DEFAULT, enforced in
// CODE. This used to live only in APPEND_SYSTEM.md, which made the default
// depend on an optional file. This extension is vendored + hard-installed
// every boot (see bin/cortex-agent), so the law holds with NO append file at
// all: same hook mechanism as plan mode (before_agent_start injection).
const LAW = `[OUTPUT LAW — always active]
Beautify every reply by default: headings where they help, tables for ANY
comparison or multi-item data, ✅/❌/🔄/⚠️ status markers, and
\`\`\`chart / \`\`\`spark fences for numeric series. Skills, brainstorming,
clarifying questions, one-liners — no exceptions; even a single question lists
its options as a table. Flush left, never indent, never wrap. Prose never goes
inside code fences; code/commands stay fenced.`;


export default function outputLaw(pi: ExtensionAPI): void {
	pi.on("before_agent_start", async () => {
		return {
			message: {
				customType: "cortexagent-output-law",
				content: LAW,
				display: false,
			},
		};
	});
}
