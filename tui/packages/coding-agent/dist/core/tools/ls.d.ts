import type { AgentTool } from "@cortexagent/agent-core";
import { type Static, Type } from "typebox";
import type { ToolDefinition } from "../extensions/types.ts";
import { type TruncationResult } from "./truncate.ts";
declare const lsSchema: Type.TObject<{
    path: Type.TOptional<Type.TString>;
    limit: Type.TOptional<Type.TNumber>;
}>;
export declare const lsToolSystemPromptContribution: {
    readonly snippet: "List directory contents";
    readonly guidelines: readonly [];
};
export type LsToolInput = Static<typeof lsSchema>;
export interface LsToolDetails {
    truncation?: TruncationResult;
    entryLimitReached?: number;
}
export interface LsOperations {
    exists: (absolutePath: string) => Promise<boolean> | boolean;
    stat: (absolutePath: string) => Promise<{
        isDirectory: () => boolean;
    }> | {
        isDirectory: () => boolean;
    };
    readdir: (absolutePath: string) => Promise<string[]> | string[];
}
export interface LsToolOptions {
    operations?: LsOperations;
}
export declare function createLsToolDefinition(cwd: string, options?: LsToolOptions): ToolDefinition<typeof lsSchema, LsToolDetails | undefined>;
export declare function createLsTool(cwd: string, options?: LsToolOptions): AgentTool<typeof lsSchema>;
export {};
//# sourceMappingURL=ls.d.ts.map