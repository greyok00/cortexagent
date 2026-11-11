import type { AssistantMessage, SimpleStreamOptions, StreamFunction, StreamOptions, ThinkingLevel, ToolCall } from "../types.ts";
export interface CortexMessagesOptions extends StreamOptions {
    reasoning?: ThinkingLevel;
    toolChoice?: "auto" | "none" | "required" | {
        type: "function";
        function: {
            name: string;
        };
    };
    debug?: boolean;
}
type CortexMessagesUsage = AssistantMessage["usage"];
type CortexMessagesStopReason = AssistantMessage["stopReason"];
export type CortexMessagesRewriteImpact = {
    policyId: string;
    policyVersion: number;
    changed: boolean;
    tokenCountChange: number;
    messageCountChange: number;
    systemPromptChanged: boolean;
};
export type CortexMessagesEvent = {
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
    content: string;
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
    content: string;
    contentSignature?: string;
    redacted?: boolean;
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
    reason: Extract<CortexMessagesStopReason, "stop" | "length" | "toolUse">;
    usage: CortexMessagesUsage;
    responseId?: string;
    rewrite?: CortexMessagesRewriteImpact;
} | {
    type: "error";
    reason: Extract<CortexMessagesStopReason, "aborted" | "error">;
    usage: CortexMessagesUsage;
    errorMessage?: string;
    responseId?: string;
    rewrite?: CortexMessagesRewriteImpact;
};
export declare class CortexMessagesResponseError extends Error {
    code?: string;
    readonly diagnosticDetails: Record<string, unknown>;
    constructor(message: string, code: string | undefined, diagnosticDetails: Record<string, unknown>);
}
export declare const stream: StreamFunction<"cortex-messages", CortexMessagesOptions>;
export declare const streamSimple: StreamFunction<"cortex-messages", SimpleStreamOptions>;
export {};
//# sourceMappingURL=cortex-messages.d.ts.map