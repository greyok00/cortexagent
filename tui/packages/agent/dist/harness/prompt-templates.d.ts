import { type ExecutionEnv, type PromptTemplate } from "./types.ts";
export type PromptTemplateDiagnosticCode = "file_info_failed" | "list_failed" | "read_failed" | "parse_failed";
export interface PromptTemplateDiagnostic {
    type: "warning";
    code: PromptTemplateDiagnosticCode;
    message: string;
    path: string;
}
export declare function loadPromptTemplates(env: ExecutionEnv, paths: string | string[]): Promise<{
    promptTemplates: PromptTemplate[];
    diagnostics: PromptTemplateDiagnostic[];
}>;
export declare function loadSourcedPromptTemplates<TSource, TPromptTemplate extends PromptTemplate = PromptTemplate>(env: ExecutionEnv, inputs: Array<{
    path: string;
    source: TSource;
}>, mapPromptTemplate?: (promptTemplate: PromptTemplate, source: TSource) => TPromptTemplate): Promise<{
    promptTemplates: Array<{
        promptTemplate: TPromptTemplate;
        source: TSource;
    }>;
    diagnostics: Array<PromptTemplateDiagnostic & {
        source: TSource;
    }>;
}>;
export declare function parseCommandArgs(argsString: string): string[];
export declare function substituteArgs(content: string, args: string[]): string;
export declare function formatPromptTemplateInvocation(template: PromptTemplate, args?: string[]): string;
//# sourceMappingURL=prompt-templates.d.ts.map