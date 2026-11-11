import type { AgentTool } from "@cortexagent/agent-core";
import { type Static, Type } from "typebox";
import type { ToolDefinition } from "../extensions/types.ts";
import { type TruncationResult } from "./truncate.ts";
declare const readSchema: Type.TObject<{
    path: Type.TString;
    offset: Type.TOptional<Type.TNumber>;
    limit: Type.TOptional<Type.TNumber>;
}>;
export declare const readToolSystemPromptContribution: {
    readonly snippet: "Read file contents";
    readonly guidelines: readonly ["Use read to examine files instead of cat or sed."];
};
export type ReadToolInput = Static<typeof readSchema>;
export interface ReadToolDetails {
    truncation?: TruncationResult;
}
export interface ReadOperations {
    readFile: (absolutePath: string) => Promise<Buffer>;
    access: (absolutePath: string) => Promise<void>;
    detectImageMimeType?: (absolutePath: string) => Promise<string | null | undefined>;
}
export interface ReadToolOptions {
    autoResizeImages?: boolean;
    operations?: ReadOperations;
}
export declare function createReadToolDefinition(cwd: string, options?: ReadToolOptions): ToolDefinition<typeof readSchema, ReadToolDetails | undefined>;
export declare function createReadTool(cwd: string, options?: ReadToolOptions): AgentTool<typeof readSchema>;
export {};
//# sourceMappingURL=read.d.ts.map