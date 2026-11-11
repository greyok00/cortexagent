import type { AgentMessage, ThinkingLevel } from "@cortexagent/agent-core";
import type { ImageContent } from "@cortexagent/ai";
import type { SessionStats } from "../../core/agent-session.ts";
import type { BashResult } from "../../core/bash-executor.ts";
import type { CompactionResult } from "../../core/compaction/index.ts";
import type { SessionEntry, SessionTreeNode } from "../../core/session-manager.ts";
import type { JsonAgentSessionEvent } from "../json-event.ts";
import type { RpcSessionState, RpcSlashCommand } from "./rpc-types.ts";
export interface RpcClientOptions {
    cliPath?: string;
    cwd?: string;
    env?: Record<string, string>;
    provider?: string;
    model?: string;
    args?: string[];
}
export interface ModelInfo {
    provider: string;
    id: string;
    contextWindow: number;
    reasoning: boolean;
}
export type RpcEventListener = (event: JsonAgentSessionEvent) => void;
export declare class RpcClient {
    private process;
    private stopReadingStdout;
    private eventListeners;
    private pendingRequests;
    private requestId;
    private stderr;
    private exitError;
    private options;
    constructor(options?: RpcClientOptions);
    start(): Promise<void>;
    stop(): Promise<void>;
    onEvent(listener: RpcEventListener): () => void;
    getStderr(): string;
    prompt(message: string, images?: ImageContent[]): Promise<void>;
    steer(message: string, images?: ImageContent[]): Promise<void>;
    followUp(message: string, images?: ImageContent[]): Promise<void>;
    abort(): Promise<void>;
    newSession(parentSession?: string): Promise<{
        cancelled: boolean;
    }>;
    getState(): Promise<RpcSessionState>;
    setModel(provider: string, modelId: string): Promise<{
        provider: string;
        id: string;
    }>;
    cycleModel(): Promise<{
        model: {
            provider: string;
            id: string;
        };
        thinkingLevel: ThinkingLevel;
        isScoped: boolean;
    } | null>;
    getAvailableModels(): Promise<ModelInfo[]>;
    setThinkingLevel(level: ThinkingLevel): Promise<void>;
    cycleThinkingLevel(): Promise<{
        level: ThinkingLevel;
    } | null>;
    getAvailableThinkingLevels(): Promise<ThinkingLevel[]>;
    setSteeringMode(mode: "all" | "one-at-a-time"): Promise<void>;
    setFollowUpMode(mode: "all" | "one-at-a-time"): Promise<void>;
    compact(customInstructions?: string): Promise<CompactionResult>;
    setAutoCompaction(enabled: boolean): Promise<void>;
    setAutoRetry(enabled: boolean): Promise<void>;
    abortRetry(): Promise<void>;
    bash(command: string): Promise<BashResult>;
    abortBash(): Promise<void>;
    getSessionStats(): Promise<SessionStats>;
    exportHtml(outputPath?: string): Promise<{
        path: string;
    }>;
    switchSession(sessionPath: string): Promise<{
        cancelled: boolean;
    }>;
    fork(entryId: string): Promise<{
        text: string;
        cancelled: boolean;
    }>;
    clone(): Promise<{
        cancelled: boolean;
    }>;
    getForkMessages(): Promise<Array<{
        entryId: string;
        text: string;
    }>>;
    getEntries(since?: string): Promise<{
        entries: SessionEntry[];
        leafId: string | null;
    }>;
    getTree(): Promise<{
        tree: SessionTreeNode[];
        leafId: string | null;
    }>;
    getLastAssistantText(): Promise<string | null>;
    setSessionName(name: string): Promise<void>;
    getMessages(): Promise<AgentMessage[]>;
    getCommands(): Promise<RpcSlashCommand[]>;
    waitForIdle(timeout?: number): Promise<void>;
    collectEvents(timeout?: number): Promise<JsonAgentSessionEvent[]>;
    promptAndWait(message: string, images?: ImageContent[], timeout?: number): Promise<JsonAgentSessionEvent[]>;
    private handleLine;
    private createProcessExitError;
    private rejectPendingRequests;
    private send;
    private getData;
}
//# sourceMappingURL=rpc-client.d.ts.map