import { APP_NAME } from "../config.ts";
import type { SourceInfo } from "./source-info.ts";

export type SlashCommandSource = "extension" | "prompt" | "skill";

export interface SlashCommandInfo {
	name: string;
	description?: string;
	source: SlashCommandSource;
	sourceInfo: SourceInfo;
}

export interface BuiltinSlashCommand {
	name: string;
	description: string;
	argumentHint?: string;
}

// ALL commands disabled
// except a deliberate keep-list. This list is what / autocomplete shows —
// everything else is removed from the initial list. Kept: settings (menu),
// plus the UI-only viewers (export/import/hotkeys/fork/clone/new) and quit.
// Model, scoped-models, share, copy, name, session, tree, trust, login,
// logout, resume and reload are NOT registered anywhere — dead in
// the TUI. Local model defaults / context windows untouched.
// /compact restored to the list — threshold
// auto-compact was broken (llama.cpp prompt_tokens reports the n_ctx cap),
// so manual compaction is the only working recovery until that's fixed.
export const BUILTIN_SLASH_COMMANDS: ReadonlyArray<BuiltinSlashCommand> = [
	{ name: "settings", description: "Open settings menu" },
	{ name: "compact", description: "Compact the conversation to free context", argumentHint: "[instructions]" },
	{ name: "export", description: "Export session (HTML default, or specify path: .html/.jsonl)" },
	{ name: "import", description: "Import and resume a session from a JSONL file" },
	{ name: "hotkeys", description: "Show all keyboard shortcuts" },
	{ name: "fork", description: "Create a new fork from a previous user message" },
	{ name: "clone", description: "Duplicate the current session at the current position" },
	{ name: "new", description: "Start a new session" },
	{ name: "quit", description: `Quit ${APP_NAME}` },
];
