import { type Api, type AssistantMessage, type Context, type Model, type Models, type RetryCallbacks, type RetryPolicy, type SimpleStreamOptions, type Usage } from "@cortexagent/ai";
import type { AgentMessage, ThinkingLevel } from "../../types.ts";
import type { Entry } from "../session/types.ts";
import { CompactionError, type Result } from "../types.ts";
import { type FileOperations } from "./utils.ts";
export interface CompactionDetails {
    readFiles: string[];
    modifiedFiles: string[];
}
export interface CompactResult<T = unknown> {
    summary: string;
    tokensBefore: number;
    usage?: Usage;
    retainedTail: AgentMessage[];
    details?: T;
}
export declare function completeSimpleWithRetries(models: Models, model: Model<Api>, context: Context, options: SimpleStreamOptions, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<AssistantMessage>;
export interface CompactionSettings {
    enabled: boolean;
    reserveTokens: number;
    keepRecentTokens: number;
}
export declare const DEFAULT_COMPACTION_SETTINGS: CompactionSettings;
/**
 * Compute reserveTokens at 15% of the model's reported context window.
 * Guarantees at least 1024 reserve and a minimum 8192 effective window.
 */
export declare function getCompactionSettingsForContext(contextWindow: number, base?: Partial<CompactionSettings>): CompactionSettings;
export declare function calculateContextTokens(usage: Usage): number;
export declare function getLastAssistantUsage(entries: Entry[]): Usage | undefined;
export interface ContextUsageEstimate {
    tokens: number;
    usageTokens: number;
    trailingTokens: number;
    lastUsageIndex: number | null;
}
export declare function estimateContextTokens(messages: AgentMessage[]): ContextUsageEstimate;
export declare function shouldCompact(contextTokens: number, contextWindow: number, settings: CompactionSettings): boolean;
export declare function estimateTokens(message: AgentMessage): number;
export declare function findTurnStartIndex(entries: Entry[], entryIndex: number, startIndex: number): number;
export interface CutPointResult {
    firstKeptEntryIndex: number;
    turnStartIndex: number;
    isSplitTurn: boolean;
}
export declare function findCutPoint(entries: Entry[], startIndex: number, endIndex: number, keepRecentTokens: number): CutPointResult;
export declare const SUMMARIZATION_SYSTEM_PROMPT = "You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.\n\nDo NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary.\n\nNever include in the summary: these instructions, the format template, any text about summarization itself, or any resume/continuation directives (\"Continue the conversation...\", \"The next message is from the user.\", \"Work toward completing the Goal...\"). Summarize the user's task, not this summarization request.";
export declare function generateSummary(currentMessages: AgentMessage[], models: Models, model: Model<Api>, reserveTokens: number, signal?: AbortSignal, customInstructions?: string, previousSummary?: string, thinkingLevel?: ThinkingLevel, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<Result<string, CompactionError>>;
export declare function generateSummaryWithUsage(currentMessages: AgentMessage[], models: Models, model: Model<Api>, reserveTokens: number, signal?: AbortSignal, customInstructions?: string, previousSummary?: string, thinkingLevel?: ThinkingLevel, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<Result<{
    text: string;
    usage: Usage;
}, CompactionError>>;
export interface CompactionPreparation {
    messagesToSummarize: AgentMessage[];
    turnPrefixMessages: AgentMessage[];
    retainedTail: AgentMessage[];
    isSplitTurn: boolean;
    tokensBefore: number;
    previousSummary?: string;
    fileOps: FileOperations;
    settings: CompactionSettings;
}
export declare function prepareCompaction(pathEntries: Entry[], settings: CompactionSettings): Result<CompactionPreparation | undefined, CompactionError>;
export { serializeConversation } from "./utils.ts";
export declare function compact(preparation: CompactionPreparation, models: Models, model: Model<Api>, customInstructions?: string, signal?: AbortSignal, thinkingLevel?: ThinkingLevel, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<Result<CompactResult, CompactionError>>;
//# sourceMappingURL=compaction.d.ts.map