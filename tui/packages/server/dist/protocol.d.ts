import { type Usage as AiUsage, type Api, type AssistantMessage, type Model, type ToolCall, type ToolResultMessage, type UserMessage } from "@cortexagent/ai";
import type { AssistantTranscriptItem, JsonValue, ModelMetadata, ToolTranscriptItem, Usage, UserTranscriptItem } from "@cortexagent/protocol";
export interface AssistantTranscriptOptions {
    id: string;
}
export interface UserTranscriptOptions {
    id: string;
}
export interface ToolTranscriptOptions {
    id: string;
    call: ToolCall;
}
export declare function toProtocolJsonValue(value: unknown, seen?: Set<object>): JsonValue;
export declare function sanitizeProtocolDetails(value: unknown, seen?: Set<object>): JsonValue | undefined;
export declare function toProtocolUsage(usage: AiUsage | undefined): Usage | undefined;
export declare function toProtocolModelMetadata(model: Model<Api>, authenticated: boolean): ModelMetadata;
export declare function toProtocolUserMessage(message: UserMessage, options: UserTranscriptOptions): UserTranscriptItem;
export declare function toProtocolAssistantMessage(message: AssistantMessage, options: AssistantTranscriptOptions): AssistantTranscriptItem;
export declare function toProtocolToolResultMessage(message: ToolResultMessage, options: ToolTranscriptOptions): ToolTranscriptItem;
//# sourceMappingURL=protocol.d.ts.map