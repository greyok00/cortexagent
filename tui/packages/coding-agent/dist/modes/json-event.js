export function toJsonEvent(event) {
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
//# sourceMappingURL=json-event.js.map