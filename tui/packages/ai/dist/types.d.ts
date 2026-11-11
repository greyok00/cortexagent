import type { TelemetryContext } from "@cortexagent/telemetry";
import type { AnthropicOptions } from "./api/anthropic-messages.ts";
import type { AzureOpenAIResponsesOptions } from "./api/azure-openai-responses.ts";
import type { BedrockOptions } from "./api/bedrock-converse-stream.ts";
import type { CortexMessagesOptions } from "./api/cortex-messages.ts";
import type { GoogleOptions } from "./api/google-generative-ai.ts";
import type { GoogleVertexOptions } from "./api/google-vertex.ts";
import type { MistralOptions } from "./api/mistral-conversations.ts";
import type { OpenAICodexResponsesOptions } from "./api/openai-codex-responses.ts";
import type { OpenAICompletionsOptions } from "./api/openai-completions.ts";
import type { OpenAIResponsesOptions } from "./api/openai-responses.ts";
import type { AssistantMessageDiagnostic } from "./utils/diagnostics.ts";
import type { AssistantMessageEventStream } from "./utils/event-stream.ts";
export type { AssistantMessageEventStream } from "./utils/event-stream.ts";
export type KnownApi = "openai-completions" | "mistral-conversations" | "openai-responses" | "azure-openai-responses" | "openai-codex-responses" | "anthropic-messages" | "bedrock-converse-stream" | "google-generative-ai" | "google-vertex" | "cortex-messages";
export type Api = KnownApi | (string & {});
export type KnownImagesApi = "openrouter-images";
export type ImagesApi = KnownImagesApi | (string & {});
export type KnownProvider = "amazon-bedrock" | "anthropic" | "google" | "google-vertex" | "openai" | "azure-openai-responses" | "openai-codex" | "radius" | "nvidia" | "github-copilot" | "xai" | "groq" | "cerebras" | "openrouter" | "vercel-ai-gateway" | "mistral" | "huggingface" | "fireworks" | "together" | "baseten" | "opencode" | "opencode-go" | "cloudflare-workers-ai" | "cloudflare-ai-gateway";
export type ProviderId = KnownProvider | string;
export type KnownImagesProvider = "openrouter";
export type ImagesProviderId = KnownImagesProvider | string;
export type ThinkingLevel = "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type ModelThinkingLevel = "off" | ThinkingLevel;
export type ThinkingLevelMap = Partial<Record<ModelThinkingLevel, string | null>>;
export type ChatTemplateKwargValue = string | number | boolean | null | {
    $var: "thinking.enabled" | "thinking.effort";
    omitWhenOff?: boolean;
};
export interface ThinkingBudgets {
    minimal?: number;
    low?: number;
    medium?: number;
    high?: number;
}
export type CacheRetention = "none" | "short" | "long";
export type Transport = "sse" | "websocket" | "websocket-cached" | "auto";
export type ProviderEnv = Record<string, string>;
export type ProviderHeaders = Record<string, string | null>;
export type FetchFunction = typeof globalThis.fetch;
export type SessionAffinityFormat = "openai" | "openai-nosession" | "openrouter";
export interface ProviderResponse {
    status: number;
    headers: Record<string, string>;
}
export interface ProviderRequestOptions<TModel = Model<Api>> {
    signal?: AbortSignal;
    telemetryContext?: TelemetryContext;
    apiKey?: string;
    fetch?: FetchFunction;
    env?: ProviderEnv;
    onPayload?: (payload: unknown, model: TModel) => unknown | undefined | Promise<unknown | undefined>;
    onResponse?: (response: ProviderResponse, model: TModel) => void | Promise<void>;
    headers?: ProviderHeaders;
    timeoutMs?: number;
    maxRetries?: number;
    maxRetryDelayMs?: number;
}
export interface StreamOptions extends ProviderRequestOptions<Model<Api>> {
    onResponse?: (response: ProviderResponse, model: Model<Api>) => void | Promise<void>;
    temperature?: number;
    samplingParams?: Record<string, unknown>;
    maxTokens?: number;
    transport?: Transport;
    cacheRetention?: CacheRetention;
    sessionId?: string;
    websocketConnectTimeoutMs?: number;
    metadata?: Record<string, unknown>;
}
export type ProviderStreamOptions = StreamOptions & Record<string, unknown>;
export interface DeferredFetchOptions extends ProviderRequestOptions<Model<Api>> {
    wait?: number;
}
export type DeferredCancelOptions = ProviderRequestOptions<Model<Api>>;
export interface ApiOptionsMap {
    "anthropic-messages": AnthropicOptions;
    "openai-completions": OpenAICompletionsOptions;
    "openai-responses": OpenAIResponsesOptions;
    "openai-codex-responses": OpenAICodexResponsesOptions;
    "azure-openai-responses": AzureOpenAIResponsesOptions;
    "google-generative-ai": GoogleOptions;
    "google-vertex": GoogleVertexOptions;
    "mistral-conversations": MistralOptions;
    "bedrock-converse-stream": BedrockOptions;
    "cortex-messages": CortexMessagesOptions;
}
export type ApiStreamOptions<TApi extends Api> = TApi extends keyof ApiOptionsMap ? ApiOptionsMap[TApi] : StreamOptions & Record<string, unknown>;
export interface ProviderStreams {
    stream(model: Model<Api>, context: Context, options?: StreamOptions): AssistantMessageEventStream;
    streamSimple(model: Model<Api>, context: Context, options?: SimpleStreamOptions): AssistantMessageEventStream;
    fetchDeferred?(model: Model<Api>, handle: DeferredHandle, options?: DeferredFetchOptions): AssistantMessageEventStream;
    cancelDeferred?(model: Model<Api>, handle: DeferredHandle, options?: DeferredCancelOptions): Promise<void>;
}
export interface ProviderImages {
    generateImages(model: ImagesModel<ImagesApi>, context: ImagesContext, options?: ImagesOptions): Promise<AssistantImages>;
}
export interface ImagesOptions extends ProviderRequestOptions<ImagesModel<ImagesApi>> {
    metadata?: Record<string, unknown>;
}
export type ProviderImagesOptions = ImagesOptions & Record<string, unknown>;
export interface SimpleStreamOptions extends StreamOptions {
    reasoning?: ThinkingLevel;
    deferred?: boolean | {
        window?: "15m" | "1h" | "24h";
    };
    thinkingBudgets?: ThinkingBudgets;
}
export type StreamFunction<TApi extends Api = Api, TOptions extends StreamOptions = StreamOptions> = (model: Model<TApi>, context: Context, options?: TOptions) => AssistantMessageEventStream;
export type ImagesFunction<TApi extends ImagesApi = ImagesApi, TOptions extends ImagesOptions = ImagesOptions> = (model: ImagesModel<TApi>, context: ImagesContext, options?: TOptions) => Promise<AssistantImages>;
export interface TextSignatureV1 {
    v: 1;
    id: string;
    phase?: "commentary" | "final_answer";
}
export interface TextContent {
    type: "text";
    text: string;
    textSignature?: string;
}
export interface ThinkingContent {
    type: "thinking";
    thinking: string;
    thinkingSignature?: string;
    redacted?: boolean;
}
export interface ImageContent {
    type: "image";
    data: string;
    mimeType: string;
}
export interface ToolCall {
    type: "toolCall";
    id: string;
    name: string;
    arguments: Record<string, any>;
    thoughtSignature?: string;
    namespace?: string;
}
export interface Usage {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    cacheWrite1h?: number;
    reasoning?: number;
    totalTokens: number;
    cost: {
        input: number;
        output: number;
        cacheRead: number;
        cacheWrite: number;
        total: number;
    };
}
export type StopReason = "pending" | "stop" | "length" | "toolUse" | "error" | "aborted" | "deferred";
export type JsonValue = string | number | boolean | null | JsonValue[] | {
    [key: string]: JsonValue;
};
export interface DeferredHandle {
    provider: string;
    modelId: string;
    api: string;
    id: string;
    expiresAt?: number;
    pollAfterMs?: number;
    data?: JsonValue;
}
export interface UserMessage {
    role: "user";
    content: string | (TextContent | ImageContent)[];
    timestamp: number;
}
export interface AssistantMessage {
    role: "assistant";
    content: (TextContent | ThinkingContent | ToolCall)[];
    api: Api;
    provider: ProviderId;
    model: string;
    responseModel?: string;
    responseId?: string;
    diagnostics?: AssistantMessageDiagnostic[];
    usage: Usage;
    stopReason: StopReason;
    deferred?: DeferredHandle;
    errorMessage?: string;
    rawStopReason?: string;
    endTurn?: boolean;
    timestamp: number;
}
export interface ToolResultMessage<TDetails = any> {
    role: "toolResult";
    toolCallId: string;
    toolName: string;
    content: (TextContent | ImageContent)[];
    details?: TDetails;
    usage?: Usage;
    addedToolNames?: string[];
    isError: boolean;
    timestamp: number;
}
export type Message = UserMessage | AssistantMessage | ToolResultMessage;
export type ImagesInputContent = TextContent | ImageContent;
export type ImagesOutputContent = TextContent | ImageContent;
export interface ImagesContext {
    input: ImagesInputContent[];
}
export type ImagesStopReason = "stop" | "error" | "aborted";
export interface AssistantImages {
    api: ImagesApi;
    provider: ImagesProviderId;
    model: string;
    output: ImagesOutputContent[];
    responseId?: string;
    usage?: Usage;
    stopReason: ImagesStopReason;
    errorMessage?: string;
    timestamp: number;
}
import type { TSchema } from "typebox";
export type GrammarFormat = "openai_lark" | "openai_regex";
export type GrammarVariants = Partial<Record<GrammarFormat, string>>;
export type ConstrainedSamplingConfig = {
    type: "json_schema";
    strict: "prefer" | "require";
} | {
    type: "grammar";
    variants: GrammarVariants;
};
export interface Tool<TParameters extends TSchema = TSchema> {
    name: string;
    description: string;
    parameters: TParameters;
    constrainedSampling?: false | ConstrainedSamplingConfig;
}
export interface Context {
    systemPrompt?: string;
    messages: Message[];
    tools?: Tool[];
}
export type AssistantMessageEvent = {
    type: "start";
    partial: AssistantMessage;
} | {
    type: "text_start";
    contentIndex: number;
    partial: AssistantMessage;
} | {
    type: "text_delta";
    contentIndex: number;
    delta: string;
    partial: AssistantMessage;
} | {
    type: "text_end";
    contentIndex: number;
    content: string;
    partial: AssistantMessage;
} | {
    type: "thinking_start";
    contentIndex: number;
    partial: AssistantMessage;
} | {
    type: "thinking_delta";
    contentIndex: number;
    delta: string;
    partial: AssistantMessage;
} | {
    type: "thinking_end";
    contentIndex: number;
    content: string;
    partial: AssistantMessage;
} | {
    type: "toolcall_start";
    contentIndex: number;
    partial: AssistantMessage;
} | {
    type: "toolcall_delta";
    contentIndex: number;
    delta: string;
    partial: AssistantMessage;
} | {
    type: "toolcall_end";
    contentIndex: number;
    toolCall: ToolCall;
    partial: AssistantMessage;
} | {
    type: "done";
    reason: Extract<StopReason, "stop" | "length" | "toolUse" | "deferred">;
    message: AssistantMessage;
} | {
    type: "error";
    reason: Extract<StopReason, "aborted" | "error">;
    error: AssistantMessage;
};
export interface OpenAICompletionsCompat {
    supportsStore?: boolean;
    supportsDeveloperRole?: boolean;
    supportsReasoningEffort?: boolean;
    supportsUsageInStreaming?: boolean;
    supportsFinishReason?: boolean;
    maxTokensField?: "max_completion_tokens" | "max_tokens";
    requiresToolResultName?: boolean;
    requiresAssistantAfterToolResult?: boolean;
    requiresThinkingAsText?: boolean;
    requiresReasoningContentOnAssistantMessages?: boolean;
    thinkingFormat?: "openai" | "openrouter" | "deepseek" | "together" | "baseten" | "zai" | "qwen" | "chat-template" | "qwen-chat-template" | "string-thinking" | "ant-ling";
    chatTemplateKwargs?: Record<string, ChatTemplateKwargValue>;
    chatTemplateArgs?: Record<string, ChatTemplateKwargValue>;
    openRouterRouting?: OpenRouterRouting;
    vercelGatewayRouting?: VercelGatewayRouting;
    zaiToolStream?: boolean;
    supportsThinkingTokenBudget?: boolean;
    supportsOpenAIGrammarTools?: boolean;
    supportsStrictMode?: boolean;
    cacheControlFormat?: "anthropic";
    sendSessionAffinityHeaders?: boolean;
    sessionAffinityFormat?: SessionAffinityFormat;
    supportsLongCacheRetention?: boolean;
}
export interface OpenAIResponsesCompat {
    supportsDeveloperRole?: boolean;
    sessionAffinityFormat?: SessionAffinityFormat;
    supportsLongCacheRetention?: boolean;
    supportsStrictMode?: boolean;
    supportsOpenAIGrammarTools?: boolean;
    supportsAdditionalTools?: boolean;
    supportsToolSearch?: boolean;
    supportsExplicitPromptCacheMode?: boolean;
}
export interface AnthropicMessagesCompat {
    supportsEagerToolInputStreaming?: boolean;
    supportsLongCacheRetention?: boolean;
    sendSessionAffinityHeaders?: boolean;
    supportsCacheControlOnTools?: boolean;
    supportsTemperature?: boolean;
    forceAdaptiveThinking?: boolean;
    allowEmptySignature?: boolean;
    supportsStrictTools?: boolean;
    supportsToolReferences?: boolean;
}
export interface BedrockCompat {
    supportsStrictMode?: boolean;
}
export interface OpenRouterRouting {
    allow_fallbacks?: boolean;
    require_parameters?: boolean;
    data_collection?: "deny" | "allow";
    zdr?: boolean;
    enforce_distillable_text?: boolean;
    order?: string[];
    only?: string[];
    ignore?: string[];
    quantizations?: string[];
    sort?: string | {
        by?: string;
        partition?: string | null;
    };
    max_price?: {
        prompt?: number | string;
        completion?: number | string;
        image?: number | string;
        audio?: number | string;
        request?: number | string;
    };
    preferred_min_throughput?: number | {
        p50?: number;
        p75?: number;
        p90?: number;
        p99?: number;
    };
    preferred_max_latency?: number | {
        p50?: number;
        p75?: number;
        p90?: number;
        p99?: number;
    };
}
export interface VercelGatewayRouting {
    only?: string[];
    order?: string[];
}
export interface ModelCostRates {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
}
export interface ModelCostTier extends ModelCostRates {
    inputTokensAbove: number;
}
export interface ModelCost extends ModelCostRates {
    tiers?: ModelCostTier[];
}
export interface Model<TApi extends Api> {
    id: string;
    name: string;
    api: TApi;
    provider: ProviderId;
    baseUrl: string;
    reasoning: boolean;
    thinkingLevelMap?: ThinkingLevelMap;
    input: ("text" | "image")[];
    cost: ModelCost;
    contextWindow: number;
    maxTokens: number;
    samplingParams?: Record<string, unknown>;
    headers?: Record<string, string>;
    compat?: TApi extends "openai-completions" ? OpenAICompletionsCompat : TApi extends "openai-responses" | "azure-openai-responses" | "openai-codex-responses" ? OpenAIResponsesCompat : TApi extends "anthropic-messages" ? AnthropicMessagesCompat : TApi extends "bedrock-converse-stream" ? BedrockCompat : never;
}
export interface ImagesModel<TApi extends ImagesApi> extends Omit<Model<Api>, "api" | "provider" | "reasoning" | "contextWindow" | "maxTokens" | "compat"> {
    api: TApi;
    provider: ImagesProviderId;
    output: ("text" | "image")[];
}
//# sourceMappingURL=types.d.ts.map