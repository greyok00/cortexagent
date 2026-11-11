import type { AgentTool } from "@cortexagent/agent-core";
import { type Static, Type } from "typebox";
import type { ToolDefinition } from "../extensions/types.ts";
declare const writeSchema: Type.TObject<{
    path: Type.TString;
    content: Type.TString;
}>;
export declare const writeToolSystemPromptContribution: {
    readonly snippet: "Create or overwrite files";
    readonly guidelines: readonly ["Use write only for new files or complete rewrites."];
};
export type WriteToolInput = Static<typeof writeSchema>;
export interface WriteOperations {
    writeFile: (absolutePath: string, content: string) => Promise<void>;
    mkdir: (dir: string) => Promise<void>;
}
export interface WriteToolOptions {
    operations?: WriteOperations;
}
export declare function createWriteToolDefinition(cwd: string, options?: WriteToolOptions): ToolDefinition<typeof writeSchema, undefined>;
export declare function createWriteTool(cwd: string, options?: WriteToolOptions): AgentTool<typeof writeSchema>;
export {};
//# sourceMappingURL=write.d.ts.map