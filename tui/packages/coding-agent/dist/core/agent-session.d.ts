import type { Agent, AgentEvent, AgentMessage, AgentState, AgentTool, ThinkingLevel } from "@cortexagent/agent-core";
import type { ImageContent, Model, TextContent } from "@cortexagent/ai/compat";
import { type BashResult } from "./bash-executor.ts";
import { type CompactionResult } from "./compaction/index.ts";
import { type ContextUsage, type ExtensionCommandContextActions, type ExtensionErrorListener, type ExtensionMode, ExtensionRunner, type ExtensionUIContext, type InputSource, type ReplacedSessionContext, type SessionStartEvent, type ShutdownHandler, type ToolDefinition, type ToolInfo } from "./extensions/index.ts";
import type { CustomMessage } from "./messages.ts";
import type { ModelRuntime } from "./model-runtime.ts";
import { type PromptTemplate } from "./prompt-templates.ts";
import type { ResourceLoader } from "./resource-loader.ts";
import type { BranchSummaryEntry, SessionEntry, SessionManager } from "./session-manager.ts";
import type { SettingsManager } from "./settings-manager.ts";
import { type BashOperations } from "./tools/bash.ts";
export interface ParsedSkillBlock {
    name: string;
    location: string;
    content: string;
    userMessage: string | undefined;
}
export declare function parseSkillBlock(text: string): ParsedSkillBlock | null;
export type AgentSessionEvent = Exclude<AgentEvent, {
    type: "agent_end";
}> | {
    type: "agent_end";
    messages: AgentMessage[];
    willRetry: boolean;
} | {
    type: "agent_settled";
} | {
    type: "queue_update";
    steering: readonly string[];
    followUp: readonly string[];
} | {
    type: "compaction_start";
    reason: "manual" | "threshold" | "overflow";
} | {
    type: "entry_appended";
    entry: SessionEntry;
} | {
    type: "session_info_changed";
    name: string | undefined;
} | {
    type: "thinking_level_changed";
    level: ThinkingLevel;
} | {
    type: "compaction_end";
    reason: "manual" | "threshold" | "overflow";
    result: CompactionResult | undefined;
    aborted: boolean;
    willRetry: boolean;
    errorMessage?: string;
} | {
    type: "auto_retry_start";
    attempt: number;
    maxAttempts: number;
    delayMs: number;
    errorMessage: string;
} | {
    type: "auto_retry_end";
    success: boolean;
    attempt: number;
    finalError?: string;
} | {
    type: "summarization_retry_scheduled";
    attempt: number;
    maxAttempts: number;
    delayMs: number;
    errorMessage: string;
} | {
    type: "summarization_retry_attempt_start";
    source: "branchSummary";
} | {
    type: "summarization_retry_attempt_start";
    source: "compaction";
    reason: "manual" | "threshold" | "overflow";
} | {
    type: "summarization_retry_finished";
} | {
    type: "auto_retry_end";
    success: boolean;
    attempt: number;
    finalError?: string;
} | {
    type: "auto_continue";
    attempt: number;
    maxAttempts: number;
} | {
    type: "bash_execution_update";
    id?: string;
    delta: string;
};
export type AgentSessionEventListener = (event: AgentSessionEvent) => void;
export interface AgentSessionConfig {
    agent: Agent;
    sessionManager: SessionManager;
    settingsManager: SettingsManager;
    cwd: string;
    scopedModels?: Array<{
        model: Model<any>;
        thinkingLevel?: ThinkingLevel;
    }>;
    resourceLoader: ResourceLoader;
    customTools?: ToolDefinition[];
    modelRuntime: ModelRuntime;
    initialActiveToolNames?: string[];
    allowedToolNames?: string[];
    excludedToolNames?: string[];
    baseToolsOverride?: Record<string, AgentTool>;
    extensionRunnerRef?: {
        current?: ExtensionRunner;
    };
    sessionStartEvent?: SessionStartEvent;
}
export interface ExtensionBindings {
    uiContext?: ExtensionUIContext;
    mode?: ExtensionMode;
    commandContextActions?: ExtensionCommandContextActions;
    abortHandler?: () => void;
    shutdownHandler?: ShutdownHandler;
    onError?: ExtensionErrorListener;
}
export interface PromptOptions {
    expandPromptTemplates?: boolean;
    images?: ImageContent[];
    streamingBehavior?: "steer" | "followUp";
    source?: InputSource;
    preflightResult?: (success: boolean) => void;
}
export interface ModelCycleResult {
    model: Model<any>;
    thinkingLevel: ThinkingLevel;
    isScoped: boolean;
}
export interface SessionStats {
    sessionFile: string | undefined;
    sessionId: string;
    userMessages: number;
    assistantMessages: number;
    toolCalls: number;
    toolResults: number;
    totalMessages: number;
    tokens: {
        input: number;
        output: number;
        cacheRead: number;
        cacheWrite: number;
        total: number;
    };
    cost: number;
    contextUsage?: ContextUsage;
}
export declare class AgentSession {
    readonly agent: Agent;
    readonly sessionManager: SessionManager;
    readonly settingsManager: SettingsManager;
    private _scopedModels;
    private _unsubscribeAgent?;
    private _eventListeners;
    private _isAgentRunActive;
    private _idleWaitPromise;
    private _resolveIdleWait;
    private _steeringMessages;
    private _followUpMessages;
    private _pendingNextTurnMessages;
    private _compactionAbortController;
    private _autoCompactionAbortController;
    private static OVERFLOW_MAX_ATTEMPTS;
    private _overflowRecoveryAttempts;
    private static AUTO_CONTINUE_MAX_ATTEMPTS;
    private _autoContinueAttempts;
    private _branchSummaryAbortController;
    private _retryAbortController;
    private _retryAttempt;
    private readonly _bashAbortControllers;
    private _pendingBashMessages;
    private _extensionRunner;
    private _turnIndex;
    private _resourceLoader;
    private _customTools;
    private _baseToolDefinitions;
    private _cwd;
    private _extensionRunnerRef?;
    private _initialActiveToolNames?;
    private _allowedToolNames?;
    private _excludedToolNames?;
    private _baseToolsOverride?;
    private _sessionStartEvent;
    private _extensionUIContext?;
    private _extensionMode;
    private _extensionCommandContextActions?;
    private _extensionAbortHandler?;
    private _extensionShutdownHandler?;
    private _extensionErrorListener?;
    private _extensionErrorUnsubscriber?;
    private _modelRuntime;
    private _toolRegistry;
    private _toolDefinitions;
    private _toolPromptSnippets;
    private _toolPromptGuidelines;
    private _baseSystemPrompt;
    private _baseSystemPromptOptions;
    private _systemPromptOverride?;
    constructor(config: AgentSessionConfig);
    get modelRuntime(): ModelRuntime;
    private _getRequiredRequestAuth;
    private _getSummarizationRequestAuth;
    private _installAgentToolHooks;
    private _installAgentNextTurnRefresh;
    private _emit;
    private _emitQueueUpdate;
    private _getIdleWaitPromise;
    private _resolveIdleWaitIfIdle;
    private _emitAgentSettled;
    private _lastAssistantMessage;
    private _handleAgentEvent;
    private _willRetryAfterAgentEnd;
    private _findLastAssistantMessage;
    private _replaceMessageInPlace;
    private _emitExtensionEvent;
    subscribe(listener: AgentSessionEventListener): () => void;
    private _disconnectFromAgent;
    dispose(): void;
    get state(): AgentState;
    get model(): Model<any> | undefined;
    get thinkingLevel(): ThinkingLevel;
    get isStreaming(): boolean;
    get isIdle(): boolean;
    get systemPrompt(): string;
    get retryAttempt(): number;
    getActiveToolNames(): string[];
    getAllTools(): ToolInfo[];
    getToolDefinition(name: string): ToolDefinition | undefined;
    setActiveToolsByName(toolNames: string[]): void;
    get isCompacting(): boolean;
    get messages(): AgentMessage[];
    get steeringMode(): "all" | "one-at-a-time";
    get followUpMode(): "all" | "one-at-a-time";
    get sessionFile(): string | undefined;
    get sessionId(): string;
    get sessionName(): string | undefined;
    get scopedModels(): ReadonlyArray<{
        model: Model<any>;
        thinkingLevel?: ThinkingLevel;
    }>;
    setScopedModels(scopedModels: Array<{
        model: Model<any>;
        thinkingLevel?: ThinkingLevel;
    }>): void;
    get promptTemplates(): ReadonlyArray<PromptTemplate>;
    private _normalizePromptSnippet;
    private _normalizePromptGuidelines;
    private _rebuildSystemPrompt;
    private _runAgentPrompt;
    private _handlePostAgentRun;
    /**
     * Continue a turn that the model did not finish (stopReason "length"):
     * output hit the per-request cap or the context ceiling. Compaction and
     * retries above already had their chance; if the turn still ended here,
     * the only thing that used to happen next was waiting for the owner to
     * type "CONTINUE". It now happens automatically, up to
     * AUTO_CONTINUE_MAX_ATTEMPTS until one turn ends cleanly.
     *
     * The prompt is deliberately identical in spirit to what the owner typed,
     * because it worked: keep going from the exact stopping point.
     */
    private _autoContinueAfterStall;
    prompt(text: string, options?: PromptOptions): Promise<void>;
    private _tryExecuteExtensionCommand;
    private _expandSkillCommand;
    steer(text: string, images?: ImageContent[]): Promise<void>;
    followUp(text: string, images?: ImageContent[]): Promise<void>;
    private _queueSteer;
    private _queueFollowUp;
    private _throwIfExtensionCommand;
    sendCustomMessage<T = unknown>(message: Pick<CustomMessage<T>, "customType" | "content" | "display" | "details">, options?: {
        triggerTurn?: boolean;
        deliverAs?: "steer" | "followUp" | "nextTurn";
    }): Promise<void>;
    sendUserMessage(content: string | (TextContent | ImageContent)[], options?: {
        deliverAs?: "steer" | "followUp";
        expandPromptTemplates?: boolean;
    }): Promise<void>;
    clearQueue(): {
        steering: string[];
        followUp: string[];
    };
    get pendingMessageCount(): number;
    getSteeringMessages(): readonly string[];
    getFollowUpMessages(): readonly string[];
    get resourceLoader(): ResourceLoader;
    abort(): Promise<void>;
    waitForIdle(): Promise<void>;
    private _emitModelSelect;
    setModel(model: Model<any>): Promise<void>;
    cycleModel(direction?: "forward" | "backward"): Promise<ModelCycleResult | undefined>;
    private _cycleScopedModel;
    private _cycleAvailableModel;
    setThinkingLevel(level: ThinkingLevel): void;
    cycleThinkingLevel(): ThinkingLevel | undefined;
    getAvailableThinkingLevels(): ThinkingLevel[];
    supportsThinking(): boolean;
    private _getThinkingLevelForModelSwitch;
    private _clampThinkingLevel;
    private syncQueueModesFromSettings;
    setSteeringMode(mode: "all" | "one-at-a-time"): void;
    setFollowUpMode(mode: "all" | "one-at-a-time"): void;
    compact(customInstructions?: string): Promise<CompactionResult>;
    abortCompaction(): void;
    abortBranchSummary(): void;
    private _checkCompaction;
    private _runAutoCompaction;
    setAutoCompactionEnabled(enabled: boolean): void;
    get autoCompactionEnabled(): boolean;
    bindExtensions(bindings: ExtensionBindings): Promise<void>;
    private extendResourcesFromExtensions;
    private buildExtensionResourcePaths;
    private getExtensionSourceLabel;
    private _applyExtensionBindings;
    private _refreshCurrentModelFromRegistry;
    private _bindExtensionCore;
    private _refreshToolRegistry;
    private _buildRuntime;
    reload(options?: {
        beforeSessionStart?: () => void | Promise<void>;
    }): Promise<void>;
    private _isRetryableError;
    private _summarizationRetryCallbacks;
    private _prepareRetry;
    abortRetry(): void;
    get isRetrying(): boolean;
    get autoRetryEnabled(): boolean;
    setAutoRetryEnabled(enabled: boolean): void;
    executeBash(command: string, onChunk?: (chunk: string) => void, options?: {
        excludeFromContext?: boolean;
        id?: string;
        operations?: BashOperations;
    }): Promise<BashResult>;
    recordBashResult(command: string, result: BashResult, options?: {
        excludeFromContext?: boolean;
    }): void;
    abortBash(): void;
    get isBashRunning(): boolean;
    get hasPendingBashMessages(): boolean;
    private _flushPendingBashMessages;
    setSessionName(name: string): void;
    navigateTree(targetId: string, options?: {
        summarize?: boolean;
        customInstructions?: string;
        replaceInstructions?: boolean;
        label?: string;
    }): Promise<{
        editorText?: string;
        cancelled: boolean;
        aborted?: boolean;
        summaryEntry?: BranchSummaryEntry;
    }>;
    getUserMessagesForForking(): Array<{
        entryId: string;
        text: string;
    }>;
    getSessionStats(): SessionStats;
    getContextUsage(): ContextUsage | undefined;
    exportToHtml(outputPath?: string, options?: {
        themeName?: string;
    }): Promise<string>;
    exportToJsonl(outputPath?: string): string;
    getLastAssistantText(): string | undefined;
    createReplacedSessionContext(): ReplacedSessionContext;
    hasExtensionHandlers(eventType: string): boolean;
    get extensionRunner(): ExtensionRunner;
}
//# sourceMappingURL=agent-session.d.ts.map