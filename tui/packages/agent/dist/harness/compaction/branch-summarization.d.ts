import { type Api, type Model, type Models, type RetryCallbacks, type RetryPolicy, type Usage } from "@cortexagent/ai";
import type { AgentMessage } from "../../types.ts";
import { type Entry, type Session } from "../session/index.ts";
import { BranchSummaryError, type Result } from "../types.ts";
import { type FileOperations } from "./utils.ts";
export interface BranchSummaryResult {
    summary: string;
    usage?: Usage;
    readFiles: string[];
    modifiedFiles: string[];
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
    entries: Entry[];
    commonAncestorId: string | null;
}
export interface GenerateBranchSummaryOptions {
    models: Models;
    model: Model<Api>;
    signal: AbortSignal;
    customInstructions?: string;
    replaceInstructions?: boolean;
    reserveTokens?: number;
    retry?: RetryPolicy;
    callbacks?: RetryCallbacks;
}
export declare function collectEntriesForBranchSummary(session: Session, oldLeafId: string | null, targetId: string): Promise<CollectEntriesResult>;
export declare function prepareBranchEntries(entries: Entry[], tokenBudget?: number): BranchPreparation;
export declare function generateBranchSummary(entries: Entry[], options: GenerateBranchSummaryOptions): Promise<Result<BranchSummaryResult, BranchSummaryError>>;
//# sourceMappingURL=branch-summarization.d.ts.map