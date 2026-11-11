import { FinishReason, FunctionCallingConfigMode } from "@google/genai";
import { retryProviderRequest } from "../utils/provider-retry.js";
import { sanitizeSurrogates } from "../utils/sanitize-unicode.js";
import { getJsonSchemaToolParameters, resolveJsonSchemaStrictSampling } from "./constrained-sampling.js";
import { transformMessages } from "./transform-messages.js";
export function isThinkingPart(part) {
    return part.thought === true;
}
export function retainThoughtSignature(existing, incoming) {
    if (typeof incoming === "string" && incoming.length > 0)
        return incoming;
    return existing;
}
const base64SignaturePattern = /^[A-Za-z0-9+/]+={0,2}$/;
function isValidThoughtSignature(signature) {
    if (!signature)
        return false;
    if (signature.length % 4 !== 0)
        return false;
    return base64SignaturePattern.test(signature);
}
function resolveThoughtSignature(isSameProviderAndModel, signature) {
    return isSameProviderAndModel && isValidThoughtSignature(signature) ? signature : undefined;
}
export function requiresToolCallId(modelId) {
    const geminiMajorVersion = getGeminiMajorVersion(modelId);
    return (modelId.startsWith("claude-") ||
        modelId.startsWith("gpt-oss-") ||
        (geminiMajorVersion !== undefined && geminiMajorVersion >= 3));
}
function getGeminiMajorVersion(modelId) {
    const match = modelId.toLowerCase().match(/^gemini(?:-live)?-(\d+)/);
    if (!match)
        return undefined;
    return Number.parseInt(match[1], 10);
}
function supportsMultimodalFunctionResponse(modelId) {
    const geminiMajorVersion = getGeminiMajorVersion(modelId);
    if (geminiMajorVersion !== undefined) {
        return geminiMajorVersion >= 3;
    }
    return true;
}
export function convertMessages(model, context) {
    const contents = [];
    const normalizeToolCallId = (id) => {
        if (!requiresToolCallId(model.id))
            return id;
        return id.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64);
    };
    const transformedMessages = transformMessages(context.messages, model, normalizeToolCallId);
    for (const msg of transformedMessages) {
        if (msg.role === "user") {
            if (typeof msg.content === "string") {
                contents.push({
                    role: "user",
                    parts: [{ text: sanitizeSurrogates(msg.content) }],
                });
            }
            else {
                const parts = msg.content.map((item) => {
                    if (item.type === "text") {
                        return { text: sanitizeSurrogates(item.text) };
                    }
                    else {
                        return {
                            inlineData: {
                                mimeType: item.mimeType,
                                data: item.data,
                            },
                        };
                    }
                });
                if (parts.length === 0)
                    continue;
                contents.push({
                    role: "user",
                    parts,
                });
            }
        }
        else if (msg.role === "assistant") {
            const parts = [];
            const isSameProviderAndModel = msg.provider === model.provider && msg.model === model.id;
            for (const block of msg.content) {
                if (block.type === "text") {
                    const thoughtSignature = resolveThoughtSignature(isSameProviderAndModel, block.textSignature);
                    if ((!block.text || block.text.trim() === "") && !thoughtSignature)
                        continue;
                    parts.push({
                        text: sanitizeSurrogates(block.text),
                        ...(thoughtSignature && { thoughtSignature }),
                    });
                }
                else if (block.type === "thinking") {
                    if (isSameProviderAndModel) {
                        const thoughtSignature = resolveThoughtSignature(isSameProviderAndModel, block.thinkingSignature);
                        if ((!block.thinking || block.thinking.trim() === "") && !thoughtSignature)
                            continue;
                        parts.push({
                            thought: true,
                            text: sanitizeSurrogates(block.thinking),
                            ...(thoughtSignature && { thoughtSignature }),
                        });
                    }
                    else {
                        if (!block.thinking || block.thinking.trim() === "")
                            continue;
                        parts.push({
                            text: sanitizeSurrogates(block.thinking),
                        });
                    }
                }
                else if (block.type === "toolCall") {
                    const thoughtSignature = resolveThoughtSignature(isSameProviderAndModel, block.thoughtSignature);
                    const part = {
                        functionCall: {
                            name: block.name,
                            args: block.arguments ?? {},
                            ...(requiresToolCallId(model.id) ? { id: block.id } : {}),
                        },
                        ...(thoughtSignature && { thoughtSignature }),
                    };
                    parts.push(part);
                }
            }
            if (parts.length === 0)
                continue;
            contents.push({
                role: "model",
                parts,
            });
        }
        else if (msg.role === "toolResult") {
            const textContent = msg.content.filter((c) => c.type === "text");
            const textResult = textContent.map((c) => c.text).join("\n");
            const imageContent = model.input.includes("image")
                ? msg.content.filter((c) => c.type === "image")
                : [];
            const hasText = textResult.length > 0;
            const hasImages = imageContent.length > 0;
            const modelSupportsMultimodalFunctionResponse = supportsMultimodalFunctionResponse(model.id);
            const responseValue = hasText ? sanitizeSurrogates(textResult) : hasImages ? "(see attached image)" : "";
            const imageParts = imageContent.map((imageBlock) => ({
                inlineData: {
                    mimeType: imageBlock.mimeType,
                    data: imageBlock.data,
                },
            }));
            const includeId = requiresToolCallId(model.id);
            const functionResponsePart = {
                functionResponse: {
                    name: msg.toolName,
                    response: msg.isError ? { error: responseValue } : { output: responseValue },
                    ...(hasImages && modelSupportsMultimodalFunctionResponse && { parts: imageParts }),
                    ...(includeId ? { id: msg.toolCallId } : {}),
                },
            };
            const lastContent = contents[contents.length - 1];
            if (lastContent?.role === "user" && lastContent.parts?.some((p) => p.functionResponse)) {
                lastContent.parts.push(functionResponsePart);
            }
            else {
                contents.push({
                    role: "user",
                    parts: [functionResponsePart],
                });
            }
            if (hasImages && !modelSupportsMultimodalFunctionResponse) {
                contents.push({
                    role: "user",
                    parts: [{ text: "Tool result image:" }, ...imageParts],
                });
            }
        }
    }
    return contents;
}
const JSON_SCHEMA_META_DECLARATIONS = new Set([
    "$schema",
    "$id",
    "$anchor",
    "$dynamicAnchor",
    "$vocabulary",
    "$comment",
    "$defs",
    "definitions", // pre-draft-2019-09 equivalent of $defs
]);
function sanitizeForOpenApi(schema) {
    if (typeof schema !== "object" || schema === null || Array.isArray(schema)) {
        return schema;
    }
    const result = {};
    for (const [key, value] of Object.entries(schema)) {
        if (JSON_SCHEMA_META_DECLARATIONS.has(key))
            continue;
        result[key] = sanitizeForOpenApi(value);
    }
    return result;
}
export function convertTools(tools, useParameters = false, supportsStrictMode = true) {
    if (tools.length === 0)
        return undefined;
    return [
        {
            functionDeclarations: tools.map((tool) => {
                const strict = resolveJsonSchemaStrictSampling(tool, supportsStrictMode);
                const parameters = getJsonSchemaToolParameters(tool, strict);
                return {
                    name: tool.name,
                    description: tool.description,
                    ...(useParameters
                        ? { parameters: sanitizeForOpenApi(parameters) }
                        : { parametersJsonSchema: parameters }),
                };
            }),
        },
    ];
}
export function supportsGoogleStrictToolSampling(modelId) {
    const majorVersion = getGeminiMajorVersion(modelId);
    return majorVersion !== undefined && majorVersion >= 3;
}
export function mapToolChoice(choice) {
    switch (choice) {
        case "auto":
            return FunctionCallingConfigMode.AUTO;
        case "none":
            return FunctionCallingConfigMode.NONE;
        case "any":
            return FunctionCallingConfigMode.ANY;
        default:
            return FunctionCallingConfigMode.AUTO;
    }
}
export function resolveGoogleFunctionCallingMode(tools, toolChoice, supportsStrictMode) {
    const useStrictMode = tools.some((tool) => resolveJsonSchemaStrictSampling(tool, supportsStrictMode) === true);
    if (toolChoice === "none" || toolChoice === "any") {
        return mapToolChoice(toolChoice);
    }
    if (useStrictMode) {
        return FunctionCallingConfigMode.VALIDATED;
    }
    return toolChoice ? mapToolChoice(toolChoice) : undefined;
}
export function mapStopReason(reason) {
    switch (reason) {
        case FinishReason.STOP:
            return "stop";
        case FinishReason.MAX_TOKENS:
            return "length";
        case FinishReason.BLOCKLIST:
        case FinishReason.PROHIBITED_CONTENT:
        case FinishReason.SPII:
        case FinishReason.SAFETY:
        case FinishReason.IMAGE_SAFETY:
        case FinishReason.IMAGE_PROHIBITED_CONTENT:
        case FinishReason.IMAGE_RECITATION:
        case FinishReason.IMAGE_OTHER:
        case FinishReason.RECITATION:
        case FinishReason.FINISH_REASON_UNSPECIFIED:
        case FinishReason.OTHER:
        case FinishReason.LANGUAGE:
        case FinishReason.MALFORMED_FUNCTION_CALL:
        case FinishReason.UNEXPECTED_TOOL_CALL:
        case FinishReason.NO_IMAGE:
            return "error";
        default: {
            const _exhaustive = reason;
            throw new Error(`Unhandled stop reason: ${_exhaustive}`);
        }
    }
}
export function mapStopReasonString(reason) {
    switch (reason) {
        case "STOP":
            return "stop";
        case "MAX_TOKENS":
            return "length";
        default:
            return "error";
    }
}
export function retryGoogleRequest(request, options) {
    return retryProviderRequest(async () => {
        try {
            return await request();
        }
        catch (error) {
            if (error instanceof Error && "status" in error && !("headers" in error)) {
                error.headers = undefined;
            }
            throw error;
        }
    }, {
        maxRetries: options?.maxRetries,
        maxRetryDelayMs: options?.maxRetryDelayMs,
        signal: options?.signal,
    });
}
//# sourceMappingURL=google-shared.js.map