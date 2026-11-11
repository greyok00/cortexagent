import type { AssistantMessage, DeferredHandle, StopReason } from "@cortexagent/ai";
import type { AgentMessage, AgentToolCall, ThinkingLevel } from "../types.ts";
import type { Entry, LaneRecord, OperationStartedRecord, ProvisionedEntry, ToolStartedRecord } from "./session/types.ts";
export type RecordLogCorruptionReason = "multiple_open_operations" | "unknown_operation" | "record_after_finish" | "non_consecutive_attempt" | "invalid_compaction_reason" | "queue_after_abort" | "invalid_queue_cancellation" | "inconsistent_step" | "tool_call_mismatch" | "duplicate_tool_invocation" | "provisioned_entry_mismatch" | "invalid_deferred_handle";
export declare class RecordLogCorruption extends Error {
    readonly reason: RecordLogCorruptionReason;
    constructor(reason: RecordLogCorruptionReason, message: string);
}
export interface RecordLogSlice {
    lane: string;
    openOperations: readonly OperationStartedRecord[];
    records: readonly LaneRecord[];
    entries: readonly Entry[];
}
export interface EffectiveLaneConfiguration {
    model: {
        provider: string;
        modelId: string;
    };
    thinkingLevel: ThinkingLevel;
    activeToolNames: string[];
}
export interface TerminalFailureState {
    entryId: string;
    source: "step" | "deferred_fetch";
    message: AssistantMessage;
}
export interface ToolBatchState {
    assistantEntryId: string;
    calls: {
        toolIndex: number;
        toolCall: AgentToolCall;
        started?: ToolStartedRecord;
        resultExists: boolean;
        terminate?: boolean;
    }[];
    truncated: boolean;
    unresolved: boolean;
}
export interface LaneState {
    lane: string;
    leafId: string | null;
    operation: null | {
        id: string;
        kind: "run" | "compaction" | "navigation";
        intent: OperationStartedRecord["intent"];
        aborting: boolean;
        step: null | {
            kind: "assistant" | "compaction" | "branch_summary";
            attempts: number;
            resultEntryId: string;
            compactionReason?: "manual" | "threshold" | "overflow";
        };
        toolBatch: ToolBatchState | null;
        missingInitialMessages: ProvisionedEntry[];
        pendingSteer: ProvisionedEntry[];
        pendingFollowUp: ProvisionedEntry[];
        pendingWrites: ProvisionedEntry[];
        deferred: DeferredHandle | null;
        overflowRecoveryUsed: boolean;
        newestOwn: null | {
            entryId: string;
            type: Entry["type"];
            role?: AgentMessage["role"];
            stopReason?: StopReason;
        };
        targets: {
            result?: boolean;
            summary?: boolean;
        };
    };
    pendingNextRun: ProvisionedEntry[];
}
export interface LaneReductionInput extends RecordLogSlice {
    leafId: string | null;
    ownEntries: readonly Entry[];
    configurationEntries: readonly Entry[];
    defaults: EffectiveLaneConfiguration;
}
export interface LaneReductionResult {
    laneState: LaneState;
    effectiveConfiguration: EffectiveLaneConfiguration;
    terminalFailure: TerminalFailureState | null;
}
export declare function validateRecordLog(input: RecordLogSlice): void;
export declare function reduceLaneState(input: LaneReductionInput): LaneReductionResult;
//# sourceMappingURL=reducer.d.ts.map