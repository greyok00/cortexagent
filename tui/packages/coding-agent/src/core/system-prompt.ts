import { getExamplesPath } from "../config.ts";
import { recallColdMemory } from "./cold-memory.ts";
import { formatSkillsForPrompt, type Skill } from "./skills.ts";

export interface BuildSystemPromptOptions {
	customPrompt?: string;

	selectedTools?: string[];

	toolSnippets?: Record<string, string>;

	promptGuidelines?: string[];

	appendSystemPrompt?: string;

	cwd: string;

	contextFiles?: Array<{ path: string; content: string }>;

	skills?: Skill[];

	// Latest user prompt text — used for cold-memory recall. Optional:
	// when absent, no cold-memory block is injected.
	promptKeywords?: string;
}

export function buildSystemPrompt(options: BuildSystemPromptOptions): string {
	const {
		customPrompt,
		selectedTools,
		toolSnippets,
		promptGuidelines,
		appendSystemPrompt,
		cwd,
		contextFiles: providedContextFiles,
		skills: providedSkills,
	} = options;
	const promptCwd = cwd.replace(/\\/g, "/");

	const appendSection = appendSystemPrompt ? `\n\n${appendSystemPrompt}` : "";

	const contextFiles = providedContextFiles ?? [];
	const skills = providedSkills ?? [];
	const examplesPath = getExamplesPath();

	// Cold-memory recall — pulls relevant pre-cached facts from
	// ~/.config/cortexllm/memory/cold/. Triggered when an extra option
	// `promptKeywords` is passed (typically the latest user prompt).
	const promptKeywords = options.promptKeywords ?? "";
	const coldRecall = recallColdMemory({ prompt: promptKeywords, limit: 3 });

	if (customPrompt) {
		let prompt = customPrompt;

		if (appendSection) {
			prompt += appendSection;
		}

		if (contextFiles.length > 0) {
			prompt += "\n\n<project_context>\n\n";
			prompt += "Project-specific instructions and guidelines:\n\n";
			for (const { path: filePath, content } of contextFiles) {
				prompt += `<project_instructions path="${filePath}">\n${content}\n</project_instructions>\n\n`;
			}
			prompt += "</project_context>\n";
		}

		const customPromptHasRead = !selectedTools || selectedTools.includes("read");
		if (customPromptHasRead && skills.length > 0) {
			prompt += formatSkillsForPrompt(skills);
		}

		if (coldRecall.formatted) {
			prompt += coldRecall.formatted;
		}

		prompt += `\nCurrent working directory: ${promptCwd}\n`;

		return prompt;
	}

	const tools = selectedTools || ["read", "bash", "edit", "write"];
	const visibleTools = tools.filter((name) => !!toolSnippets?.[name]);
	const toolsList =
		visibleTools.length > 0 ? visibleTools.map((name) => `- ${name}: ${toolSnippets![name]}`).join("\n") : "(none)";

	const guidelinesList: string[] = [];
	const guidelinesSet = new Set<string>();
	const addGuideline = (guideline: string): void => {
		if (guidelinesSet.has(guideline)) {
			return;
		}
		guidelinesSet.add(guideline);
		guidelinesList.push(guideline);
	};

	const hasBash = tools.includes("bash");
	const hasGrep = tools.includes("grep");
	const hasFind = tools.includes("find");
	const hasLs = tools.includes("ls");
	const hasRead = tools.includes("read");

	if (hasBash && !hasGrep && !hasFind && !hasLs) {
		addGuideline("Use bash for file operations like ls, rg, find");
	}

	for (const guideline of promptGuidelines ?? []) {
		const normalized = guideline.trim();
		if (normalized.length > 0) {
			addGuideline(normalized);
		}
	}

	addGuideline("Be concise in your responses");
	addGuideline("Show file paths clearly when working with files");

	const guidelines = guidelinesList.map((g) => `- ${g}`).join("\n");

	let prompt = `You are an expert coding assistant operating inside cortex, a coding agent harness. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
${toolsList}

In addition to the tools above, you may have access to other custom tools depending on the project.

Guidelines:
${guidelines}

Cortex documentation (read only when the user asks about cortex itself, its SDK, extensions, themes, skills, or TUI):
- Examples: ${examplesPath} (extensions, custom tools, SDK)
- When asked about: extensions (examples/extensions/), themes, skills, prompt templates, TUI components, keybindings, SDK integrations, custom providers, adding models, cortex packages, environment variables
- When working on cortex topics, read the examples and follow .md cross-references before implementing`;

	if (appendSection) {
		prompt += appendSection;
	}

	if (contextFiles.length > 0) {
		prompt += "\n\n<project_context>\n\n";
		prompt += "Project-specific instructions and guidelines:\n\n";
		for (const { path: filePath, content } of contextFiles) {
			prompt += `<project_instructions path="${filePath}">\n${content}\n</project_instructions>\n\n`;
		}
		prompt += "</project_context>\n";
	}

	if (hasRead && skills.length > 0) {
		prompt += formatSkillsForPrompt(skills);
	}

	if (coldRecall.formatted) {
		prompt += coldRecall.formatted;
	}

	prompt += `\nCurrent working directory: ${promptCwd}`;

	return prompt;
}
