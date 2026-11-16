import type { Usage } from "@cortexagent/ai";
import type { AgentSessionEvent } from "../core/agent-session.ts";

type WithoutPartial<T> = T extends { partial: unknown } ? Omit<T, "partial"> : T;

type ToJsonEvent<T> = T extends {
	type: "message_update";
	assistantMessageEvent: infer TAssistantMessageEvent;
}
	? {
			type: "message_update";
			usage: Usage;
			assistantMessageEvent: WithoutPartial<TAssistantMessageEvent>;
		}
	: T;

export type JsonAgentSessionEvent = ToJsonEvent<AgentSessionEvent>;

type MessageUpdateEvent = Extract<AgentSessionEvent, { type: "message_update" }>;
type JsonMessageUpdateEvent = Extract<JsonAgentSessionEvent, { type: "message_update" }>;

export function toJsonEvent(event: MessageUpdateEvent): JsonMessageUpdateEvent;
export function toJsonEvent(event: AgentSessionEvent): JsonAgentSessionEvent;
export function toJsonEvent(event: AgentSessionEvent): JsonAgentSessionEvent {
	if (event.type !== "message_update") {
		return event;
	}
	if (event.message.role !== "assistant") {
		throw new Error("message_update message is not an assistant message");
	}

	const assistantMessageEvent = event.assistantMessageEvent;
	if (!("partial" in assistantMessageEvent)) {
		return { type: "message_update", usage: event.message.usage, assistantMessageEvent };
	}

	const { partial: _partial, ...deltaEvent } = assistantMessageEvent;
	return { type: "message_update", usage: event.message.usage, assistantMessageEvent: deltaEvent };
}
