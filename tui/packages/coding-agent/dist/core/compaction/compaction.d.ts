import type { AgentMessage, StreamFn, ThinkingLevel } from "@cortexagent/agent-core";
import { type RetryCallbacks, type RetryPolicy } from "@cortexagent/ai";
import type { AssistantMessage, Context, Model, SimpleStreamOptions, Usage } from "@cortexagent/ai/compat";
import { type SessionEntry } from "../session-manager.ts";
import { type FileOperations } from "./utils.ts";
/**
 * Split a serialized conversation into windows of at most `maxChars`
 * characters, cutting on natural boundaries when one is available.
 *
 * Owner directive 2026-10-03: no truncation, anywhere. The union of the
 * returned chunks is always exactly the input text - oversized
 * summarization requests are handled by summarizing the conversation in
 * sequential windows (rolling update), never by cutting content.
 */
export declare function chunkTextForWindow(text: string, maxChars: number): string[];
export interface CompactionDetails {
    readFiles: string[];
    modifiedFiles: string[];
}
export interface CompactionResult<T = unknown> {
    summary: string;
    firstKeptEntryId: string;
    tokensBefore: number;
    estimatedTokensAfter?: number;
    usage?: Usage;
    details?: T;
}
export interface CompactionSettings {
    enabled: boolean;
    reserveTokens: number;
    keepRecentTokens: number;
}
export declare const DEFAULT_COMPACTION_SETTINGS: CompactionSettings;
export declare function calculateContextTokens(usage: Usage): number;
export declare function getLastAssistantUsage(entries: SessionEntry[]): Usage | undefined;
export interface ContextUsageEstimate {
    tokens: number;
    usageTokens: number;
    trailingTokens: number;
    lastUsageIndex: number | null;
}
export declare function estimateContextTokens(messages: AgentMessage[]): ContextUsageEstimate;
export declare function shouldCompact(contextTokens: number, contextWindow: number, settings: CompactionSettings): boolean;
export declare function estimateTokens(message: AgentMessage): number;
export declare function findTurnStartIndex(entries: SessionEntry[], entryIndex: number, startIndex: number): number;
export interface CutPointResult {
    firstKeptEntryIndex: number;
    turnStartIndex: number;
    isSplitTurn: boolean;
}
export declare function findCutPoint(entries: SessionEntry[], startIndex: number, endIndex: number, keepRecentTokens: number): CutPointResult;
export declare function completeSummarization(model: Model<any>, context: Context, options: SimpleStreamOptions, streamFn?: StreamFn, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<AssistantMessage>;
export declare function generateSummary(currentMessages: AgentMessage[], model: Model<any>, reserveTokens: number, apiKey: string | undefined, headers?: Record<string, string>, signal?: AbortSignal, customInstructions?: string, previousSummary?: string, thinkingLevel?: ThinkingLevel, streamFn?: StreamFn, env?: Record<string, string>, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<string>;
export declare function generateSummaryWithUsage(currentMessages: AgentMessage[], model: Model<any>, reserveTokens: number, apiKey: string | undefined, headers?: Record<string, string>, signal?: AbortSignal, customInstructions?: string, previousSummary?: string, thinkingLevel?: ThinkingLevel, streamFn?: StreamFn, env?: Record<string, string>, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<{
    text: string;
    usage: Usage;
}>;
export interface CompactionPreparation {
    firstKeptEntryId: string;
    messagesToSummarize: AgentMessage[];
    turnPrefixMessages: AgentMessage[];
    isSplitTurn: boolean;
    tokensBefore: number;
    previousSummary?: string;
    fileOps: FileOperations;
    settings: CompactionSettings;
}
export declare function prepareCompaction(pathEntries: SessionEntry[], settings: CompactionSettings, allowConsecutive?: boolean): CompactionPreparation | undefined;
export declare function compact(preparation: CompactionPreparation, model: Model<any>, apiKey: string | undefined, headers?: Record<string, string>, customInstructions?: string, signal?: AbortSignal, thinkingLevel?: ThinkingLevel, streamFn?: StreamFn, env?: Record<string, string>, retry?: RetryPolicy, callbacks?: RetryCallbacks): Promise<CompactionResult>;
//# sourceMappingURL=compaction.d.ts.map