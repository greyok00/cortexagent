import type { Usage } from "@cortexagent/ai";
import type { AgentSessionEvent } from "../core/agent-session.ts";
type WithoutPartial<T> = T extends {
    partial: unknown;
} ? Omit<T, "partial"> : T;
type ToJsonEvent<T> = T extends {
    type: "message_update";
    assistantMessageEvent: infer TAssistantMessageEvent;
} ? {
    type: "message_update";
    usage: Usage;
    assistantMessageEvent: WithoutPartial<TAssistantMessageEvent>;
} : T;
export type JsonAgentSessionEvent = ToJsonEvent<AgentSessionEvent>;
type MessageUpdateEvent = Extract<AgentSessionEvent, {
    type: "message_update";
}>;
type JsonMessageUpdateEvent = Extract<JsonAgentSessionEvent, {
    type: "message_update";
}>;
export declare function toJsonEvent(event: MessageUpdateEvent): JsonMessageUpdateEvent;
export declare function toJsonEvent(event: AgentSessionEvent): JsonAgentSessionEvent;
export {};
//# sourceMappingURL=json-event.d.ts.map