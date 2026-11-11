import { type AssistantMessage, type AssistantMessageEvent, type Context, EventStream, type Model, type SimpleStreamOptions, type StopReason, type ToolCall } from "@cortexagent/ai";
declare class ProxyMessageEventStream extends EventStream<AssistantMessageEvent, AssistantMessage> {
    constructor();
}
export type ProxyAssistantMessageEvent = {
    type: "start";
} | {
    type: "text_start";
    contentIndex: number;
} | {
    type: "text_delta";
    contentIndex: number;
    delta: string;
} | {
    type: "text_end";
    contentIndex: number;
    contentSignature?: string;
} | {
    type: "thinking_start";
    contentIndex: number;
} | {
    type: "thinking_delta";
    contentIndex: number;
    delta: string;
} | {
    type: "thinking_end";
    contentIndex: number;
    contentSignature?: string;
} | {
    type: "toolcall_start";
    contentIndex: number;
    id: string;
    toolName: string;
} | {
    type: "toolcall_delta";
    contentIndex: number;
    delta: string;
} | {
    type: "toolcall_end";
    contentIndex: number;
    toolCall: ToolCall;
} | {
    type: "done";
    reason: Extract<StopReason, "stop" | "length" | "toolUse">;
    usage: AssistantMessage["usage"];
} | {
    type: "error";
    reason: Extract<StopReason, "aborted" | "error">;
    errorMessage?: string;
    usage: AssistantMessage["usage"];
};
type ProxySerializableStreamOptions = Pick<SimpleStreamOptions, "temperature" | "samplingParams" | "maxTokens" | "reasoning" | "cacheRetention" | "sessionId" | "headers" | "metadata" | "transport" | "thinkingBudgets" | "maxRetryDelayMs">;
export interface ProxyStreamOptions extends ProxySerializableStreamOptions {
    signal?: AbortSignal;
    authToken: string;
    proxyUrl: string;
}
export declare function streamProxy(model: Model<any>, context: Context, options: ProxyStreamOptions): ProxyMessageEventStream;
export {};
//# sourceMappingURL=proxy.d.ts.map