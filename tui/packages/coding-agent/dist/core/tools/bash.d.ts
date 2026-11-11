import type { AgentTool } from "@cortexagent/agent-core";
import { type Static, Type } from "typebox";
import type { ToolDefinition } from "../extensions/types.ts";
import { type TruncationResult } from "./truncate.ts";
declare const bashSchema: Type.TObject<{
    command: Type.TString;
    timeout: Type.TOptional<Type.TNumber>;
}>;
export declare const bashToolSystemPromptContribution: {
    readonly snippet: "Execute bash commands (ls, grep, find, etc.)";
    readonly guidelines: readonly ["You can inspect CORTEX_* environment variables for current model and session details."];
};
export type BashToolInput = Static<typeof bashSchema>;
export interface BashToolDetails {
    truncation?: TruncationResult;
    fullOutputPath?: string;
}
export interface BashOperations {
    exec: (command: string, cwd: string, options: {
        onData: (data: Buffer) => void;
        signal?: AbortSignal;
        timeout?: number;
        env?: NodeJS.ProcessEnv;
    }) => Promise<{
        exitCode: number | null;
    }>;
}
export declare function createLocalBashOperations(options?: {
    shellPath?: string;
}): BashOperations;
export interface BashSpawnContext {
    command: string;
    cwd: string;
    env: NodeJS.ProcessEnv;
}
export type BashSpawnHook = (context: BashSpawnContext) => BashSpawnContext;
export interface BashToolOptions {
    operations?: BashOperations;
    commandPrefix?: string;
    shellPath?: string;
    exposeSessionEnvironment?: boolean;
    spawnHook?: BashSpawnHook;
}
type BashRenderState = {
    startedAt: number | undefined;
    endedAt: number | undefined;
    interval: NodeJS.Timeout | undefined;
};
export declare function createBashToolDefinition(cwd: string, options?: BashToolOptions): ToolDefinition<typeof bashSchema, BashToolDetails | undefined, BashRenderState>;
export declare function createBashTool(cwd: string, options?: BashToolOptions): AgentTool<typeof bashSchema>;
export {};
//# sourceMappingURL=bash.d.ts.map