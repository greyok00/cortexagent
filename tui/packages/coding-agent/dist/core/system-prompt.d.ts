import { type Skill } from "./skills.ts";
export interface BuildSystemPromptOptions {
    customPrompt?: string;
    selectedTools?: string[];
    toolSnippets?: Record<string, string>;
    promptGuidelines?: string[];
    appendSystemPrompt?: string;
    cwd: string;
    contextFiles?: Array<{
        path: string;
        content: string;
    }>;
    skills?: Skill[];
    promptKeywords?: string;
}
export declare function buildSystemPrompt(options: BuildSystemPromptOptions): string;
//# sourceMappingURL=system-prompt.d.ts.map