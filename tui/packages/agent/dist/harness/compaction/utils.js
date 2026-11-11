import { contentText } from "@cortexagent/ai";
export function createFileOps() {
    return {
        read: new Set(),
        written: new Set(),
        edited: new Set(),
    };
}
export function extractFileOpsFromMessage(message, fileOps) {
    if (message.role !== "assistant")
        return;
    if (!("content" in message) || !Array.isArray(message.content))
        return;
    for (const block of message.content) {
        if (typeof block !== "object" || block === null)
            continue;
        if (!("type" in block) || block.type !== "toolCall")
            continue;
        if (!("arguments" in block) || !("name" in block))
            continue;
        const args = block.arguments;
        if (!args)
            continue;
        const path = typeof args.path === "string" ? args.path : undefined;
        if (!path)
            continue;
        switch (block.name) {
            case "read":
                fileOps.read.add(path);
                break;
            case "write":
                fileOps.written.add(path);
                break;
            case "edit":
                fileOps.edited.add(path);
                break;
        }
    }
}
export function computeFileLists(fileOps) {
    const modified = new Set([...fileOps.edited, ...fileOps.written]);
    const readOnly = [...fileOps.read].filter((f) => !modified.has(f)).sort();
    const modifiedFiles = [...modified].sort();
    return { readFiles: readOnly, modifiedFiles };
}
export function formatFileOperations(readFiles, modifiedFiles) {
    const sections = [];
    if (readFiles.length > 0) {
        sections.push(`<read-files>\n${readFiles.join("\n")}\n</read-files>`);
    }
    if (modifiedFiles.length > 0) {
        sections.push(`<modified-files>\n${modifiedFiles.join("\n")}\n</modified-files>`);
    }
    if (sections.length === 0)
        return "";
    return `\n\n${sections.join("\n\n")}`;
}
// 2026-10-03 owner directive: no truncation, anywhere. Tool results are
// preserved in full.
function safeJsonStringify(value) {
    try {
        return JSON.stringify(value) ?? "undefined";
    }
    catch {
        return "[unserializable]";
    }
}
export function serializeConversation(messages) {
    const parts = [];
    for (const msg of messages) {
        if (msg.role === "user") {
            const content = contentText(msg.content, "");
            if (content)
                parts.push(`[User]: ${content}`);
        }
        else if (msg.role === "assistant") {
            const thinkingParts = [];
            const toolCalls = [];
            for (const block of msg.content) {
                if (block.type === "thinking") {
                    thinkingParts.push(block.thinking);
                }
                else if (block.type === "toolCall") {
                    const args = block.arguments;
                    const argsStr = Object.entries(args)
                        .map(([k, v]) => `${k}=${safeJsonStringify(v)}`)
                        .join(", ");
                    toolCalls.push(`${block.name}(${argsStr})`);
                }
            }
            if (thinkingParts.length > 0) {
                parts.push(`[Assistant thinking]: ${thinkingParts.join("\n")}`);
            }
            if (msg.content.some((block) => block.type === "text")) {
                parts.push(`[Assistant]: ${contentText(msg.content)}`);
            }
            if (toolCalls.length > 0) {
                parts.push(`[Assistant tool calls]: ${toolCalls.join("; ")}`);
            }
        }
        else if (msg.role === "toolResult") {
            const content = contentText(msg.content, "");
            if (content) {
                parts.push(`[Tool result]: ${content}`);
            }
        }
    }
    return parts.join("\n\n");
}
//# sourceMappingURL=utils.js.map