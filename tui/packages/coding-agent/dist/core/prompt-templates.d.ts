import { type SourceInfo } from "./source-info.ts";
export interface PromptTemplate {
    name: string;
    description: string;
    argumentHint?: string;
    content: string;
    sourceInfo: SourceInfo;
    filePath: string;
}
export declare function parseCommandArgs(argsString: string): string[];
export declare function substituteArgs(content: string, args: string[]): string;
export interface LoadPromptTemplatesOptions {
    cwd: string;
    agentDir: string;
    promptPaths: string[];
    includeDefaults: boolean;
}
export declare function loadPromptTemplates(options: LoadPromptTemplatesOptions): PromptTemplate[];
export declare function expandPromptTemplate(text: string, templates: PromptTemplate[]): string;
//# sourceMappingURL=prompt-templates.d.ts.map