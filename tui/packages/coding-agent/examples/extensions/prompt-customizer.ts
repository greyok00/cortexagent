import type { BuildSystemPromptOptions, ExtensionAPI } from "@cortexagent/coding-agent";

function addToolGuidance(options: BuildSystemPromptOptions, basePrompt: string): string {
	const hasTool = (name: string) => options.selectedTools?.includes(name) ?? false;

	const parts: string[] = [];

	if (hasTool("read")) {
		parts.push(
			"• Use the `read` tool for file contents (supports text and images).",
			"  - For large files, use `offset` and `limit` to read in chunks.",
		);
	}

	if (hasTool("bash")) {
		parts.push("• Execute commands with the `bash` tool. Use it for file operations like `ls`, `find`, `grep`.");
	}

	if (hasTool("edit")) {
		parts.push(
			"• Use the `edit` tool for precise text replacements in files. Match exact content including whitespace.",
		);
	}

	if (hasTool("write")) {
		parts.push("• Use the `write` tool to create new files or overwrite existing ones completely.");
	}

	if (options.skills && options.skills.length > 0) {
		const skillNames = options.skills.map((s) => s.name).join(", ");
		parts.push(`\nAvailable skills: ${skillNames}`, "Use skill documentation for best practices on specific tools.");
	}

	if (parts.length === 0) {
		return basePrompt;
	}

	return `${basePrompt}

## Tool Guidance

${parts.join("\n")}
`;
}

function mergeWithUserAppend(options: BuildSystemPromptOptions): string {
	const userAppend = options.appendSystemPrompt;
	const extensionSpecific = `
## Extension-Added Context

This prompt includes tool guidance and skill information loaded dynamically.
If you have additional requirements, configure them via --append-system-prompt or project context files.
`;

	if (userAppend) {
		return `${userAppend}\n\n${extensionSpecific}`;
	}

	return extensionSpecific;
}

export default function promptCustomizer(cortex: ExtensionAPI) {
	cortex.on("before_agent_start", async (event) => {
		const { systemPrompt, systemPromptOptions } = event;

		const customPrompt = addToolGuidance(systemPromptOptions, systemPrompt);
		const appendSection = mergeWithUserAppend(systemPromptOptions);

		return {
			systemPrompt: `${customPrompt}${appendSection}`,
		};
	});
}
