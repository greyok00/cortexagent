import { getSupportedThinkingLevels, } from "@cortexagent/ai";
function nonNegativeInteger(value) {
    if (value === undefined || !Number.isFinite(value))
        return undefined;
    return Math.max(0, Math.floor(value));
}
function nonNegativeNumber(value) {
    return Number.isFinite(value) ? Math.max(0, value) : 0;
}
function identifier(value, label) {
    if (typeof value !== "string" || value.length === 0)
        throw new TypeError(`${label} must be a non-empty string`);
    return value;
}
function timestamp(value) {
    if (!Number.isSafeInteger(value) || value < 0)
        throw new TypeError("Protocol timestamps must be non-negative integers");
    return value;
}
export function toProtocolJsonValue(value, seen = new Set()) {
    if (value === null || typeof value === "string" || typeof value === "boolean")
        return value;
    if (typeof value === "number") {
        if (!Number.isFinite(value))
            throw new TypeError("Protocol JSON numbers must be finite");
        return value;
    }
    if (typeof value !== "object")
        throw new TypeError(`Unsupported protocol JSON value: ${typeof value}`);
    if (seen.has(value))
        throw new TypeError("Protocol JSON values must not contain circular references");
    const prototype = Object.getPrototypeOf(value);
    if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) {
        throw new TypeError("Protocol JSON objects must be plain objects");
    }
    seen.add(value);
    try {
        if (Array.isArray(value))
            return Array.from(value, (entry) => toProtocolJsonValue(entry, seen));
        const result = {};
        for (const [key, entry] of Object.entries(value))
            result[key] = toProtocolJsonValue(entry, seen);
        return result;
    }
    finally {
        seen.delete(value);
    }
}
export function sanitizeProtocolDetails(value, seen = new Set()) {
    if (value === null || typeof value === "string" || typeof value === "boolean")
        return value;
    if (typeof value === "number")
        return Number.isFinite(value) ? value : String(value);
    if (typeof value === "bigint")
        return value.toString();
    if (value === undefined || typeof value === "function" || typeof value === "symbol")
        return undefined;
    if (value instanceof Date)
        return value.toISOString();
    if (typeof value !== "object")
        return String(value);
    if (seen.has(value))
        return "[Circular]";
    seen.add(value);
    try {
        if (Array.isArray(value))
            return Array.from(value, (entry) => sanitizeProtocolDetails(entry, seen) ?? null);
        const result = {};
        for (const [key, entry] of Object.entries(value)) {
            const normalized = sanitizeProtocolDetails(entry, seen);
            if (normalized !== undefined)
                result[key] = normalized;
        }
        return result;
    }
    finally {
        seen.delete(value);
    }
}
export function toProtocolUsage(usage) {
    if (!usage)
        return undefined;
    const reasoning = nonNegativeInteger(usage.reasoning);
    const result = {
        input: nonNegativeInteger(usage.input) ?? 0,
        output: nonNegativeInteger(usage.output) ?? 0,
        cacheRead: nonNegativeInteger(usage.cacheRead) ?? 0,
        cacheWrite: nonNegativeInteger(usage.cacheWrite) ?? 0,
        ...(reasoning === undefined ? {} : { reasoning }),
        totalTokens: nonNegativeInteger(usage.totalTokens) ?? 0,
        cost: {
            input: nonNegativeNumber(usage.cost.input),
            output: nonNegativeNumber(usage.cost.output),
            cacheRead: nonNegativeNumber(usage.cost.cacheRead),
            cacheWrite: nonNegativeNumber(usage.cost.cacheWrite),
            total: nonNegativeNumber(usage.cost.total),
        },
    };
    return result;
}
export function toProtocolModelMetadata(model, authenticated) {
    const result = {
        provider: identifier(model.provider, "Model provider"),
        id: identifier(model.id, "Model id"),
        name: identifier(model.name, "Model name"),
        api: identifier(model.api, "Model API"),
        reasoning: model.reasoning,
        input: [...model.input],
        contextWindow: Math.max(1, Math.floor(model.contextWindow)),
        maxTokens: Math.max(1, Math.floor(model.maxTokens)),
        cost: {
            input: nonNegativeNumber(model.cost.input),
            output: nonNegativeNumber(model.cost.output),
            cacheRead: nonNegativeNumber(model.cost.cacheRead),
            cacheWrite: nonNegativeNumber(model.cost.cacheWrite),
        },
        supportedThinkingLevels: getSupportedThinkingLevels(model),
        authenticated,
    };
    return result;
}
function toProtocolUserContent(content) {
    if (typeof content === "string")
        return [{ type: "text", text: content }];
    return content.map((part) => {
        switch (part.type) {
            case "text":
                return { type: "text", text: part.text };
            case "image":
                return { type: "image", data: part.data, mimeType: part.mimeType };
            default: {
                const exhaustive = part;
                return exhaustive;
            }
        }
    });
}
export function toProtocolUserMessage(message, options) {
    const result = {
        id: identifier(options.id, "Transcript item id"),
        role: "user",
        content: toProtocolUserContent(message.content),
        timestamp: timestamp(message.timestamp),
    };
    return result;
}
function toProtocolAssistantContent(message) {
    return message.content.map((part) => {
        switch (part.type) {
            case "text":
                return { type: "text", text: part.text };
            case "thinking":
                return {
                    type: "thinking",
                    thinking: part.thinking,
                    ...(part.redacted === undefined ? {} : { redacted: part.redacted }),
                };
            case "toolCall":
                return {
                    type: "toolCall",
                    toolCallId: identifier(part.id, "Tool call id"),
                    toolName: identifier(part.name, "Tool call name"),
                    input: toProtocolJsonValue(part.arguments),
                };
            default: {
                const exhaustive = part;
                return exhaustive;
            }
        }
    });
}
export function toProtocolAssistantMessage(message, options) {
    const usage = toProtocolUsage(message.usage);
    const common = {
        id: identifier(options.id, "Transcript item id"),
        role: "assistant",
        content: toProtocolAssistantContent(message),
        model: {
            provider: identifier(message.provider, "Assistant provider"),
            id: identifier(message.model, "Assistant model"),
        },
        ...(message.responseModel === undefined
            ? {}
            : { responseModel: identifier(message.responseModel, "Assistant response model") }),
        ...(usage ? { usage } : {}),
        timestamp: timestamp(message.timestamp),
    };
    switch (message.stopReason) {
        case "pending":
            return { ...common, status: "streaming" };
        case "stop":
        case "length":
        case "toolUse":
            return {
                ...common,
                status: "complete",
                stopReason: message.stopReason,
            };
        case "deferred":
            throw new TypeError("Deferred assistant messages are not supported by protocol v1");
        case "error":
            if (message.errorMessage?.length === 0) {
                throw new TypeError("Assistant error messages must not be empty");
            }
            return {
                ...common,
                status: "error",
                stopReason: "error",
                ...(message.errorMessage === undefined ? {} : { errorMessage: message.errorMessage }),
            };
        case "aborted":
            return {
                ...common,
                status: "aborted",
                stopReason: "aborted",
                ...(message.errorMessage === undefined ? {} : { errorMessage: message.errorMessage }),
            };
        default: {
            const exhaustive = message.stopReason;
            return exhaustive;
        }
    }
}
function toProtocolToolContent(content) {
    return content.map((part) => {
        switch (part.type) {
            case "text":
                return { type: "text", text: part.text };
            case "image":
                return { type: "image", data: part.data, mimeType: part.mimeType };
            default: {
                const exhaustive = part;
                return exhaustive;
            }
        }
    });
}
export function toProtocolToolResultMessage(message, options) {
    const callId = identifier(options.call.id, "Tool call id");
    const callName = identifier(options.call.name, "Tool call name");
    if (identifier(message.toolCallId, "Tool result call id") !== callId) {
        throw new TypeError(`Tool result ${message.toolCallId} does not match tool call ${callId}`);
    }
    if (identifier(message.toolName, "Tool result name") !== callName) {
        throw new TypeError(`Tool result ${message.toolName} does not match tool call ${callName}`);
    }
    const details = sanitizeProtocolDetails(message.details);
    const usage = toProtocolUsage(message.usage);
    const common = {
        id: identifier(options.id, "Transcript item id"),
        role: "tool",
        toolCallId: callId,
        toolName: callName,
        input: toProtocolJsonValue(options.call.arguments),
        content: toProtocolToolContent(message.content),
        ...(details === undefined ? {} : { details }),
        ...(usage ? { usage } : {}),
        timestamp: timestamp(message.timestamp),
    };
    return message.isError
        ? { ...common, status: "error", isError: true }
        : { ...common, status: "complete", isError: false };
}
//# sourceMappingURL=protocol.js.map