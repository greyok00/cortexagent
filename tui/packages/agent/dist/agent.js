import { runAgentLoop, runAgentLoopContinue } from "./agent-loop.js";
import { getDefaultStreamFn } from "./stream-fn.js";
function defaultConvertToLlm(messages) {
    return messages.filter((message) => message.role === "user" || message.role === "assistant" || message.role === "toolResult");
}
const EMPTY_USAGE = {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};
const DEFAULT_MODEL = {
    id: "unknown",
    name: "unknown",
    api: "unknown",
    provider: "unknown",
    baseUrl: "",
    reasoning: false,
    input: [],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 0,
    maxTokens: 0,
};
function createMutableAgentState(initialState) {
    let tools = initialState?.tools?.slice() ?? [];
    let messages = initialState?.messages?.slice() ?? [];
    return {
        systemPrompt: initialState?.systemPrompt ?? "",
        model: initialState?.model ?? DEFAULT_MODEL,
        thinkingLevel: initialState?.thinkingLevel ?? "off",
        get tools() {
            return tools;
        },
        set tools(nextTools) {
            tools = nextTools.slice();
        },
        get messages() {
            return messages;
        },
        set messages(nextMessages) {
            messages = nextMessages.slice();
        },
        isStreaming: false,
        streamingMessage: undefined,
        pendingToolCalls: new Set(),
        errorMessage: undefined,
    };
}
class PendingMessageQueue {
    messages = [];
    mode;
    constructor(mode) {
        this.mode = mode;
    }
    enqueue(message) {
        this.messages.push(message);
    }
    hasItems() {
        return this.messages.length > 0;
    }
    drain() {
        if (this.mode === "all") {
            const drained = this.messages.slice();
            this.messages = [];
            return drained;
        }
        const first = this.messages[0];
        if (!first) {
            return [];
        }
        this.messages = this.messages.slice(1);
        return [first];
    }
    clear() {
        this.messages = [];
    }
}
export class Agent {
    _state;
    listeners = new Set();
    steeringQueue;
    followUpQueue;
    convertToLlm;
    transformContext;
    streamFunction;
    getApiKey;
    onPayload;
    onResponse;
    beforeToolCall;
    afterToolCall;
    shouldStopAfterTurn;
    prepareNextTurn;
    prepareNextTurnWithContext;
    activeRun;
    sessionId;
    thinkingBudgets;
    transport;
    maxRetryDelayMs;
    toolExecution;
    constructor(options) {
        const runtimeOptions = options ?? {};
        this._state = createMutableAgentState(runtimeOptions.initialState);
        this.convertToLlm = runtimeOptions.convertToLlm ?? defaultConvertToLlm;
        this.transformContext = runtimeOptions.transformContext;
        this.streamFunction = runtimeOptions.streamFn ?? getDefaultStreamFn();
        this.getApiKey = runtimeOptions.getApiKey;
        this.onPayload = runtimeOptions.onPayload;
        this.onResponse = runtimeOptions.onResponse;
        this.beforeToolCall = runtimeOptions.beforeToolCall;
        this.afterToolCall = runtimeOptions.afterToolCall;
        this.shouldStopAfterTurn = runtimeOptions.shouldStopAfterTurn;
        this.prepareNextTurn = runtimeOptions.prepareNextTurn;
        this.prepareNextTurnWithContext = runtimeOptions.prepareNextTurnWithContext;
        this.steeringQueue = new PendingMessageQueue(runtimeOptions.steeringMode ?? "one-at-a-time");
        this.followUpQueue = new PendingMessageQueue(runtimeOptions.followUpMode ?? "one-at-a-time");
        this.sessionId = runtimeOptions.sessionId;
        this.thinkingBudgets = runtimeOptions.thinkingBudgets;
        this.transport = runtimeOptions.transport ?? "auto";
        this.maxRetryDelayMs = runtimeOptions.maxRetryDelayMs;
        this.toolExecution = runtimeOptions.toolExecution ?? "parallel";
    }
    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    get state() {
        return this._state;
    }
    set steeringMode(mode) {
        this.steeringQueue.mode = mode;
    }
    get steeringMode() {
        return this.steeringQueue.mode;
    }
    set followUpMode(mode) {
        this.followUpQueue.mode = mode;
    }
    get followUpMode() {
        return this.followUpQueue.mode;
    }
    steer(message) {
        this.steeringQueue.enqueue(message);
    }
    followUp(message) {
        this.followUpQueue.enqueue(message);
    }
    clearSteeringQueue() {
        this.steeringQueue.clear();
    }
    clearFollowUpQueue() {
        this.followUpQueue.clear();
    }
    clearAllQueues() {
        this.clearSteeringQueue();
        this.clearFollowUpQueue();
    }
    hasQueuedMessages() {
        return this.steeringQueue.hasItems() || this.followUpQueue.hasItems();
    }
    get signal() {
        return this.activeRun?.abortController.signal;
    }
    abort() {
        this.activeRun?.abortController.abort();
    }
    waitForIdle() {
        return this.activeRun?.promise ?? Promise.resolve();
    }
    reset() {
        if (this.activeRun) {
            throw new Error("Agent is already processing. Wait for completion before resetting.");
        }
        this._state.messages = [];
        this._state.isStreaming = false;
        this._state.streamingMessage = undefined;
        this._state.pendingToolCalls = new Set();
        this._state.errorMessage = undefined;
        this.clearFollowUpQueue();
        this.clearSteeringQueue();
    }
    async prompt(input, images) {
        if (this.activeRun) {
            throw new Error("Agent is already processing a prompt. Use steer() or followUp() to queue messages, or wait for completion.");
        }
        const messages = this.normalizePromptInput(input, images);
        await this.runPromptMessages(messages);
    }
    async continue() {
        if (this.activeRun) {
            throw new Error("Agent is already processing. Wait for completion before continuing.");
        }
        const lastMessage = this._state.messages[this._state.messages.length - 1];
        if (!lastMessage) {
            throw new Error("No messages to continue from");
        }
        if (lastMessage.role === "assistant") {
            const queuedSteering = this.steeringQueue.drain();
            if (queuedSteering.length > 0) {
                await this.runPromptMessages(queuedSteering, { skipInitialSteeringPoll: true });
                return;
            }
            const queuedFollowUps = this.followUpQueue.drain();
            if (queuedFollowUps.length > 0) {
                await this.runPromptMessages(queuedFollowUps);
                return;
            }
            throw new Error("Cannot continue from message role: assistant");
        }
        await this.runContinuation();
    }
    normalizePromptInput(input, images) {
        if (Array.isArray(input)) {
            return input;
        }
        if (typeof input !== "string") {
            return [input];
        }
        const content = [{ type: "text", text: input }];
        if (images && images.length > 0) {
            content.push(...images);
        }
        return [{ role: "user", content, timestamp: Date.now() }];
    }
    async runPromptMessages(messages, options = {}) {
        await this.runWithLifecycle(async (signal) => {
            await runAgentLoop(messages, this.createContextSnapshot(), this.createLoopConfig(options), (event) => this.processEvents(event), signal, this.streamFunction);
        });
    }
    async runContinuation() {
        await this.runWithLifecycle(async (signal) => {
            await runAgentLoopContinue(this.createContextSnapshot(), this.createLoopConfig(), (event) => this.processEvents(event), signal, this.streamFunction);
        });
    }
    createContextSnapshot() {
        return {
            systemPrompt: this._state.systemPrompt,
            messages: this._state.messages.slice(),
            tools: this._state.tools.slice(),
        };
    }
    createLoopConfig(options = {}) {
        let skipInitialSteeringPoll = options.skipInitialSteeringPoll === true;
        const shouldStopAfterTurn = this.shouldStopAfterTurn;
        return {
            model: this._state.model,
            reasoning: this._state.thinkingLevel === "off" ? undefined : this._state.thinkingLevel,
            sessionId: this.sessionId,
            onPayload: this.onPayload,
            onResponse: this.onResponse,
            transport: this.transport,
            thinkingBudgets: this.thinkingBudgets,
            maxRetryDelayMs: this.maxRetryDelayMs,
            toolExecution: this.toolExecution,
            beforeToolCall: this.beforeToolCall,
            afterToolCall: this.afterToolCall,
            shouldStopAfterTurn: shouldStopAfterTurn
                ? async (context) => await shouldStopAfterTurn(context, this.signal)
                : undefined,
            prepareNextTurn: this.prepareNextTurnWithContext || this.prepareNextTurn
                ? async (context) => {
                    if (this.prepareNextTurnWithContext) {
                        return await this.prepareNextTurnWithContext(context, this.signal);
                    }
                    return await this.prepareNextTurn?.(this.signal);
                }
                : undefined,
            convertToLlm: this.convertToLlm,
            transformContext: this.transformContext,
            getApiKey: this.getApiKey,
            getSteeringMessages: async () => {
                if (skipInitialSteeringPoll) {
                    skipInitialSteeringPoll = false;
                    return [];
                }
                return this.steeringQueue.drain();
            },
            getFollowUpMessages: async () => this.followUpQueue.drain(),
        };
    }
    async runWithLifecycle(executor) {
        if (this.activeRun) {
            throw new Error("Agent is already processing.");
        }
        const abortController = new AbortController();
        let resolvePromise = () => { };
        const promise = new Promise((resolve) => {
            resolvePromise = resolve;
        });
        this.activeRun = { promise, resolve: resolvePromise, abortController };
        this._state.isStreaming = true;
        this._state.streamingMessage = undefined;
        this._state.errorMessage = undefined;
        try {
            await executor(abortController.signal);
        }
        catch (error) {
            await this.handleRunFailure(error, abortController.signal.aborted);
        }
        finally {
            this.finishRun();
        }
    }
    async handleRunFailure(error, aborted) {
        const failureMessage = {
            role: "assistant",
            content: [{ type: "text", text: "" }],
            api: this._state.model.api,
            provider: this._state.model.provider,
            model: this._state.model.id,
            usage: EMPTY_USAGE,
            stopReason: aborted ? "aborted" : "error",
            errorMessage: error instanceof Error ? error.message : String(error),
            timestamp: Date.now(),
        };
        await this.processEvents({ type: "message_start", message: failureMessage });
        await this.processEvents({ type: "message_end", message: failureMessage });
        await this.processEvents({ type: "turn_end", message: failureMessage, toolResults: [] });
        await this.processEvents({ type: "agent_end", messages: [failureMessage] });
    }
    finishRun() {
        this._state.isStreaming = false;
        this._state.streamingMessage = undefined;
        this._state.pendingToolCalls = new Set();
        this.activeRun?.resolve();
        this.activeRun = undefined;
    }
    async processEvents(event) {
        switch (event.type) {
            case "message_start":
                this._state.streamingMessage = event.message;
                break;
            case "message_update":
                this._state.streamingMessage = event.message;
                break;
            case "message_end":
                this._state.streamingMessage = undefined;
                this._state.messages.push(event.message);
                break;
            case "tool_execution_start": {
                const pendingToolCalls = new Set(this._state.pendingToolCalls);
                pendingToolCalls.add(event.toolCallId);
                this._state.pendingToolCalls = pendingToolCalls;
                break;
            }
            case "tool_execution_end": {
                const pendingToolCalls = new Set(this._state.pendingToolCalls);
                pendingToolCalls.delete(event.toolCallId);
                this._state.pendingToolCalls = pendingToolCalls;
                break;
            }
            case "turn_end":
                if (event.message.role === "assistant" && event.message.errorMessage) {
                    this._state.errorMessage = event.message.errorMessage;
                }
                break;
            case "agent_end":
                this._state.streamingMessage = undefined;
                break;
        }
        const signal = this.activeRun?.abortController.signal;
        if (!signal) {
            throw new Error("Agent listener invoked outside active run");
        }
        for (const listener of this.listeners) {
            await listener(event, signal);
        }
    }
}
//# sourceMappingURL=agent.js.map