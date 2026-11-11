import type { AgentMessage, StreamFn } from "@cortexagent/agent-core";
import type { RetryCallbacks, RetryPolicy } from "@cortexagent/ai";
import type { Model, Usage } from "@cortexagent/ai/compat";
import type { ReadonlySessionManager, SessionEntry } from "../session-manager.ts";
import { type FileOperations } from "./utils.ts";
export interface BranchSummaryResult {
    summary?: string;
    usage?: Usage;
    readFiles?: string[];
    modifiedFiles?: string[];
    aborted?: boolean;
    error?: string;
}
export interface BranchSummaryDetails {
    readFiles: string[];
    modifiedFiles: string[];
}
export type { FileOperations } from "./utils.ts";
export interface BranchPreparation {
    messages: AgentMessage[];
    fileOps: FileOperations;
    totalTokens: number;
}
export interface CollectEntriesResult {
    entries: SessionEntry[];
    commonAncestorId: string | null;
}
export interface GenerateBranchSummaryOptions {
    model: Model<any>;
    apiKey?: string;
    headers?: Record<string, string>;
    env?: Record<string, string>;
    signal: AbortSignal;
    customInstructions?: string;
    replaceInstructions?: boolean;
    reserveTokens?: number;
    streamFn?: StreamFn;
    retry?: RetryPolicy;
    callbacks?: RetryCallbacks;
}
export declare function collectEntriesForBranchSummary(session: ReadonlySessionManager, oldLeafId: string | null, targetId: string): CollectEntriesResult;
export declare function prepareBranchEntries(entries: SessionEntry[], tokenBudget?: number): BranchPreparation;
export declare function generateBranchSummary(entries: SessionEntry[], options: GenerateBranchSummaryOptions): Promise<BranchSummaryResult>;
//# sourceMappingURL=branch-summarization.d.ts.map