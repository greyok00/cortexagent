import { contentText, retryAssistantCall, uuidv7, } from "@cortexagent/ai";
import { convertToLlm, createBranchSummaryMessage, createCompactionSummaryMessage } from "../messages.js";
import { buildSessionContext } from "../session/context.js";
import { CompactionError, err, ok } from "../types.js";
import { computeFileLists, createFileOps, extractFileOpsFromMessage, formatFileOperations, serializeConversation, } from "./utils.js";
function safeJsonStringify(value) {
    try {
        return JSON.stringify(value) ?? "undefined";
    }
    catch {
        return "[unserializable]";
    }
}
function extractFileOperations(messages, entries, prevCompactionIndex) {
    const fileOps = createFileOps();
    if (prevCompactionIndex >= 0) {
        const prevCompaction = entries[prevCompactionIndex];
        if (prevCompaction.details) {
            const details = prevCompaction.details;
            if (Array.isArray(details.readFiles)) {
                for (const f of details.readFiles)
                    fileOps.read.add(f);
            }
            if (Array.isArray(details.modifiedFiles)) {
                for (const f of details.modifiedFiles)
                    fileOps.edited.add(f);
            }
        }
    }
    for (const msg of messages) {
        extractFileOpsFromMessage(msg, fileOps);
    }
    return fileOps;
}
function getMessageFromEntry(entry) {
    if (entry.type === "message") {
        return entry.message;
    }
    if (entry.type === "branch_summary") {
        return createBranchSummaryMessage(entry.summary, entry.fromId, entry.timestamp);
    }
    if (entry.type === "compaction") {
        return createCompactionSummaryMessage(entry.summary, entry.tokensBefore, entry.timestamp);
    }
    return undefined;
}
function getMessageFromEntryForCompaction(entry) {
    if (entry.type === "compaction") {
        return undefined;
    }
    return getMessageFromEntry(entry);
}
export async function completeSimpleWithRetries(models, model, context, options, retry, callbacks) {
    const requestOptions = {
        ...options,
        cacheRetention: "none",
        sessionId: uuidv7(),
    };
    return retryAssistantCall(() => models.completeSimple(model, context, requestOptions), retry, requestOptions.signal, callbacks);
}
function combineUsage(first, second) {
    return {
        input: first.input + second.input,
        output: first.output + second.output,
        cacheRead: first.cacheRead + second.cacheRead,
        cacheWrite: first.cacheWrite + second.cacheWrite,
        ...(first.cacheWrite1h !== undefined || second.cacheWrite1h !== undefined
            ? { cacheWrite1h: (first.cacheWrite1h ?? 0) + (second.cacheWrite1h ?? 0) }
            : {}),
        ...(first.reasoning !== undefined || second.reasoning !== undefined
            ? { reasoning: (first.reasoning ?? 0) + (second.reasoning ?? 0) }
            : {}),
        totalTokens: first.totalTokens + second.totalTokens,
        cost: {
            input: first.cost.input + second.cost.input,
            output: first.cost.output + second.cost.output,
            cacheRead: first.cost.cacheRead + second.cost.cacheRead,
            cacheWrite: first.cost.cacheWrite + second.cost.cacheWrite,
            total: first.cost.total + second.cost.total,
        },
    };
}
// reserveTokens is 15% of the model window so auto-compact fires at 85% of
// the live n_ctx reported by the engine-server. With locked big_ctx=131072
// the threshold is ~111411 tokens. Lower → compacts later (more room per
// turn, tighter tool-output reserve). Higher → compacts earlier (more
// reserve for tool-call output, less room per turn).
// The caller derives the actual value from model.contextWindow when known
// (see getCompactionSettingsForContext below). The fallback below is for
// the rare case where no model context is known yet.
export const DEFAULT_COMPACTION_SETTINGS = {
    enabled: true,
    reserveTokens: 16384,
    keepRecentTokens: 20000,
};
/**
 * Compute reserveTokens at 15% of the model's reported context window.
 * Guarantees at least 1024 reserve and a minimum 8192 effective window.
 */
export function getCompactionSettingsForContext(contextWindow, base) {
    const enabled = base?.enabled ?? DEFAULT_COMPACTION_SETTINGS.enabled;
    const keepRecent = base?.keepRecentTokens ?? DEFAULT_COMPACTION_SETTINGS.keepRecentTokens;
    if (!Number.isFinite(contextWindow) || contextWindow <= 0) {
        return { enabled, reserveTokens: DEFAULT_COMPACTION_SETTINGS.reserveTokens, keepRecentTokens: keepRecent };
    }
    const desired = Math.floor(contextWindow * 0.15);
    const minReserve = 1024;
    const maxReserve = Math.max(1024, contextWindow - 8192);
    return {
        enabled,
        reserveTokens: Math.min(maxReserve, Math.max(minReserve, desired)),
        keepRecentTokens: keepRecent,
    };
}
export function calculateContextTokens(usage) {
    return usage.totalTokens || usage.input + usage.output + usage.cacheRead + usage.cacheWrite;
}
function getAssistantUsage(msg) {
    if (msg.role === "assistant" && "usage" in msg) {
        const assistantMsg = msg;
        if (assistantMsg.stopReason !== "aborted" &&
            assistantMsg.stopReason !== "error" &&
            assistantMsg.usage &&
            calculateContextTokens(assistantMsg.usage) > 0) {
            return assistantMsg.usage;
        }
    }
    return undefined;
}
export function getLastAssistantUsage(entries) {
    for (let i = entries.length - 1; i >= 0; i--) {
        const entry = entries[i];
        if (entry.type === "message") {
            const usage = getAssistantUsage(entry.message);
            if (usage)
                return usage;
        }
    }
    return undefined;
}
function getLastAssistantUsageInfo(messages) {
    for (let i = messages.length - 1; i >= 0; i--) {
        const usage = getAssistantUsage(messages[i]);
        if (usage)
            return { usage, index: i };
    }
    return undefined;
}
export function estimateContextTokens(messages) {
    const usageInfo = getLastAssistantUsageInfo(messages);
    if (!usageInfo) {
        let estimated = 0;
        for (const message of messages) {
            estimated += estimateTokens(message);
        }
        return {
            tokens: estimated,
            usageTokens: 0,
            trailingTokens: estimated,
            lastUsageIndex: null,
        };
    }
    const usageTokens = calculateContextTokens(usageInfo.usage);
    let trailingTokens = 0;
    for (let i = usageInfo.index + 1; i < messages.length; i++) {
        trailingTokens += estimateTokens(messages[i]);
    }
    return {
        tokens: usageTokens + trailingTokens,
        usageTokens,
        trailingTokens,
        lastUsageIndex: usageInfo.index,
    };
}
export function shouldCompact(contextTokens, contextWindow, settings) {
    if (!settings.enabled)
        return false;
    // Guard: never compact when the reserve budget exceeds the context window.
    // A negative or zero effective window means the model can't fit any output
    // after reserving space, so compaction would trigger on every turn.
    const effectiveWindow = contextWindow - settings.reserveTokens;
    if (effectiveWindow <= 0)
        return false;
    return contextTokens > effectiveWindow;
}
const ESTIMATED_IMAGE_CHARS = 4800;
function estimateTextAndImageContentChars(content) {
    if (typeof content === "string") {
        return content.length;
    }
    let chars = 0;
    for (const block of content) {
        if (block.type === "text" && block.text) {
            chars += block.text.length;
        }
        else if (block.type === "image") {
            chars += ESTIMATED_IMAGE_CHARS;
        }
    }
    return chars;
}
export function estimateTokens(message) {
    let chars = 0;
    switch (message.role) {
        case "user": {
            chars = estimateTextAndImageContentChars(message.content);
            return Math.ceil(chars / 4);
        }
        case "assistant": {
            const assistant = message;
            for (const block of assistant.content) {
                if (block.type === "text") {
                    chars += block.text.length;
                }
                else if (block.type === "thinking") {
                    chars += block.thinking.length;
                }
                else if (block.type === "toolCall") {
                    chars += block.name.length + safeJsonStringify(block.arguments).length;
                }
            }
            return Math.ceil(chars / 4);
        }
        case "custom":
        case "toolResult": {
            chars = estimateTextAndImageContentChars(message.content);
            return Math.ceil(chars / 4);
        }
        case "bashExecution": {
            chars = message.command.length + message.output.length;
            return Math.ceil(chars / 4);
        }
        case "branchSummary":
        case "compactionSummary": {
            chars = message.summary.length;
            return Math.ceil(chars / 4);
        }
    }
    return 0;
}
function findValidCutPoints(entries, startIndex, endIndex) {
    const cutPoints = [];
    for (let i = startIndex; i < endIndex; i++) {
        const entry = entries[i];
        switch (entry.type) {
            case "message": {
                const role = entry.message.role;
                switch (role) {
                    case "bashExecution":
                    case "custom":
                    case "branchSummary":
                    case "compactionSummary":
                    case "user":
                    case "assistant":
                        cutPoints.push(i);
                        break;
                    case "toolResult":
                        break;
                }
                break;
            }
            case "thinking_level_change":
            case "model_change":
            case "active_tools_change":
            case "compaction":
            case "branch_summary":
            case "custom":
                break;
        }
        if (entry.type === "branch_summary")
            cutPoints.push(i);
    }
    return cutPoints;
}
export function findTurnStartIndex(entries, entryIndex, startIndex) {
    for (let i = entryIndex; i >= startIndex; i--) {
        const entry = entries[i];
        if (entry.type === "branch_summary") {
            return i;
        }
        if (entry.type === "message") {
            const role = entry.message.role;
            if (role === "user" || role === "bashExecution") {
                return i;
            }
        }
    }
    return -1;
}
export function findCutPoint(entries, startIndex, endIndex, keepRecentTokens) {
    const cutPoints = findValidCutPoints(entries, startIndex, endIndex);
    if (cutPoints.length === 0) {
        return { firstKeptEntryIndex: startIndex, turnStartIndex: -1, isSplitTurn: false };
    }
    let accumulatedTokens = 0;
    let cutIndex = cutPoints[0];
    for (let i = endIndex - 1; i >= startIndex; i--) {
        const entry = entries[i];
        if (entry.type !== "message")
            continue;
        const messageTokens = estimateTokens(entry.message);
        accumulatedTokens += messageTokens;
        if (accumulatedTokens >= keepRecentTokens) {
            for (let c = 0; c < cutPoints.length; c++) {
                if (cutPoints[c] >= i) {
                    cutIndex = cutPoints[c];
                    break;
                }
            }
            break;
        }
    }
    while (cutIndex > startIndex) {
        const prevEntry = entries[cutIndex - 1];
        if (prevEntry.type === "compaction") {
            break;
        }
        if (prevEntry.type === "message") {
            break;
        }
        cutIndex--;
    }
    const cutEntry = entries[cutIndex];
    const isUserMessage = cutEntry.type === "message" && cutEntry.message.role === "user";
    const turnStartIndex = isUserMessage ? -1 : findTurnStartIndex(entries, cutIndex, startIndex);
    return {
        firstKeptEntryIndex: cutIndex,
        turnStartIndex,
        isSplitTurn: !isUserMessage && turnStartIndex !== -1,
    };
}
export const SUMMARIZATION_SYSTEM_PROMPT = `You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary.

Never include in the summary: these instructions, the format template, any text about summarization itself, or any resume/continuation directives ("Continue the conversation...", "The next message is from the user.", "Work toward completing the Goal..."). Summarize the user's task, not this summarization request.`;
const SUMMARIZATION_PROMPT = `The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

RULES:
- Output ONLY the summary document itself. Never include these rules, the format template, or any text about summarization/resuming/continuation in the output.
- Keep each section concise. Preserve exact file paths, function names, and error messages.
- If a section is empty, write "(none)" — do NOT omit sections.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]`;
const UPDATE_SUMMARIZATION_PROMPT = `The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE task-relevant information from the previous summary (goals, progress, decisions, next steps, critical context)
- REMOVE any meta-instructions, resume/continuation directives, or echoes of the summarization format that appear in <previous-summary> — those are contamination from earlier prompts, not task content
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it
- Output ONLY the updated summary document itself. Never include these rules or the format template in the output.
- Keep each section concise. If a section is empty, write "(none)" — do NOT omit sections.

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]`;
export async function generateSummary(currentMessages, models, model, reserveTokens, signal, customInstructions, previousSummary, thinkingLevel, retry, callbacks) {
    const result = await generateSummaryWithUsage(currentMessages, models, model, reserveTokens, signal, customInstructions, previousSummary, thinkingLevel, retry, callbacks);
    return result.ok ? ok(result.value.text) : err(result.error);
}
export async function generateSummaryWithUsage(currentMessages, models, model, reserveTokens, signal, customInstructions, previousSummary, thinkingLevel, retry, callbacks) {
    const maxTokens = Math.min(Math.floor(0.8 * reserveTokens), model.maxTokens > 0 ? model.maxTokens : Number.POSITIVE_INFINITY);
    let basePrompt = previousSummary ? UPDATE_SUMMARIZATION_PROMPT : SUMMARIZATION_PROMPT;
    if (customInstructions) {
        basePrompt = `${basePrompt}\n\nAdditional focus: ${customInstructions}`;
    }
    const llmMessages = convertToLlm(currentMessages);
    const conversationText = serializeConversation(llmMessages);
    let promptText = `<conversation>\n${conversationText}\n</conversation>\n\n`;
    if (previousSummary) {
        promptText += `<previous-summary>\n${previousSummary}\n</previous-summary>\n\n`;
    }
    promptText += basePrompt;
    const summarizationMessages = [
        {
            role: "user",
            content: [{ type: "text", text: promptText }],
            timestamp: Date.now(),
        },
    ];
    const completionOptions = model.reasoning && thinkingLevel && thinkingLevel !== "off"
        ? { maxTokens, signal, reasoning: thinkingLevel }
        : { maxTokens, signal };
    const response = await completeSimpleWithRetries(models, model, { systemPrompt: SUMMARIZATION_SYSTEM_PROMPT, messages: summarizationMessages }, completionOptions, retry, callbacks);
    if (response.stopReason === "aborted") {
        return err(new CompactionError("aborted", response.errorMessage || "Summarization aborted"));
    }
    if (response.stopReason === "error") {
        return err(new CompactionError("summarization_failed", `Summarization failed: ${response.errorMessage || "Unknown error"}`));
    }
    const textContent = contentText(response.content);
    return ok({ text: textContent, usage: response.usage });
}
export function prepareCompaction(pathEntries, settings) {
    if (pathEntries.length === 0 || pathEntries[pathEntries.length - 1].type === "compaction") {
        return ok(undefined);
    }
    let prevCompactionIndex = -1;
    for (let i = pathEntries.length - 1; i >= 0; i--) {
        if (pathEntries[i].type === "compaction") {
            prevCompactionIndex = i;
            break;
        }
    }
    let previousSummary;
    let compactableEntries = pathEntries;
    if (prevCompactionIndex >= 0) {
        const prevCompaction = pathEntries[prevCompactionIndex];
        previousSummary = prevCompaction.summary;
        const virtualRetainedEntries = prevCompaction.retainedTail.map((message, index) => ({
            type: "message",
            id: `${prevCompaction.id}:retained:${index}`,
            parentId: index === 0 ? prevCompaction.id : `${prevCompaction.id}:retained:${index - 1}`,
            seq: prevCompaction.seq,
            timestamp: message.timestamp,
            message,
        }));
        compactableEntries = [...virtualRetainedEntries, ...pathEntries.slice(prevCompactionIndex + 1)];
    }
    const boundaryEnd = compactableEntries.length;
    const tokensBefore = estimateContextTokens(buildSessionContext(pathEntries).messages).tokens;
    const cutPoint = findCutPoint(compactableEntries, 0, boundaryEnd, settings.keepRecentTokens);
    const historyEnd = cutPoint.isSplitTurn ? cutPoint.turnStartIndex : cutPoint.firstKeptEntryIndex;
    const messagesToSummarize = [];
    for (let i = 0; i < historyEnd; i++) {
        const msg = getMessageFromEntryForCompaction(compactableEntries[i]);
        if (msg)
            messagesToSummarize.push(msg);
    }
    const turnPrefixMessages = [];
    if (cutPoint.isSplitTurn) {
        for (let i = cutPoint.turnStartIndex; i < cutPoint.firstKeptEntryIndex; i++) {
            const msg = getMessageFromEntryForCompaction(compactableEntries[i]);
            if (msg)
                turnPrefixMessages.push(msg);
        }
    }
    const retainedTail = [];
    for (let i = cutPoint.firstKeptEntryIndex; i < boundaryEnd; i++) {
        const msg = getMessageFromEntryForCompaction(compactableEntries[i]);
        if (msg)
            retainedTail.push(msg);
    }
    const fileOps = extractFileOperations(messagesToSummarize, pathEntries, prevCompactionIndex);
    if (cutPoint.isSplitTurn) {
        for (const msg of turnPrefixMessages) {
            extractFileOpsFromMessage(msg, fileOps);
        }
    }
    return ok({
        messagesToSummarize,
        turnPrefixMessages,
        retainedTail,
        isSplitTurn: cutPoint.isSplitTurn,
        tokensBefore,
        previousSummary,
        fileOps,
        settings,
    });
}
const TURN_PREFIX_SUMMARIZATION_PROMPT = `This is the PREFIX of a turn that was too large to keep. The SUFFIX (recent work) is retained.

Summarize the prefix to provide context for the retained suffix:

## Original Request
[What did the user ask for in this turn?]

## Early Progress
- [Key decisions and work done in the prefix]

## Context for Suffix
- [Information needed to understand the retained recent work]

Be concise. Focus on what's needed to understand the kept suffix.`;
export { serializeConversation } from "./utils.js";
export async function compact(preparation, models, model, customInstructions, signal, thinkingLevel, retry, callbacks) {
    const { messagesToSummarize, turnPrefixMessages, retainedTail, isSplitTurn, tokensBefore, previousSummary, fileOps, settings, } = preparation;
    let summary;
    let summaryUsage;
    if (isSplitTurn && turnPrefixMessages.length > 0) {
        let historyText = "No prior history.";
        let historyUsage;
        if (messagesToSummarize.length > 0) {
            const historyResult = await generateSummaryWithUsage(messagesToSummarize, models, model, settings.reserveTokens, signal, customInstructions, previousSummary, thinkingLevel, retry, callbacks);
            if (!historyResult.ok)
                return err(historyResult.error);
            historyText = historyResult.value.text;
            historyUsage = historyResult.value.usage;
        }
        const turnPrefixResult = await generateTurnPrefixSummary(turnPrefixMessages, models, model, settings.reserveTokens, signal, thinkingLevel, retry, callbacks);
        if (!turnPrefixResult.ok)
            return err(turnPrefixResult.error);
        summary = `${historyText}\n\n---\n\n**Turn Context (split turn):**\n\n${turnPrefixResult.value.text}`;
        summaryUsage = historyUsage
            ? combineUsage(historyUsage, turnPrefixResult.value.usage)
            : turnPrefixResult.value.usage;
    }
    else {
        const summaryResult = await generateSummaryWithUsage(messagesToSummarize, models, model, settings.reserveTokens, signal, customInstructions, previousSummary, thinkingLevel, retry, callbacks);
        if (!summaryResult.ok)
            return err(summaryResult.error);
        summary = summaryResult.value.text;
        summaryUsage = summaryResult.value.usage;
    }
    const { readFiles, modifiedFiles } = computeFileLists(fileOps);
    summary += formatFileOperations(readFiles, modifiedFiles);
    return ok({
        summary,
        tokensBefore,
        usage: summaryUsage,
        retainedTail,
        details: { readFiles, modifiedFiles },
    });
}
async function generateTurnPrefixSummary(messages, models, model, reserveTokens, signal, thinkingLevel, retry, callbacks) {
    const maxTokens = Math.min(Math.floor(0.5 * reserveTokens), model.maxTokens > 0 ? model.maxTokens : Number.POSITIVE_INFINITY);
    const llmMessages = convertToLlm(messages);
    const conversationText = serializeConversation(llmMessages);
    const promptText = `<conversation>\n${conversationText}\n</conversation>\n\n${TURN_PREFIX_SUMMARIZATION_PROMPT}`;
    const summarizationMessages = [
        {
            role: "user",
            content: [{ type: "text", text: promptText }],
            timestamp: Date.now(),
        },
    ];
    const completionOptions = model.reasoning && thinkingLevel && thinkingLevel !== "off"
        ? { maxTokens, signal, reasoning: thinkingLevel }
        : { maxTokens, signal };
    const response = await completeSimpleWithRetries(models, model, { systemPrompt: SUMMARIZATION_SYSTEM_PROMPT, messages: summarizationMessages }, completionOptions, retry, callbacks);
    if (response.stopReason === "aborted") {
        return err(new CompactionError("aborted", response.errorMessage || "Turn prefix summarization aborted"));
    }
    if (response.stopReason === "error") {
        return err(new CompactionError("summarization_failed", `Turn prefix summarization failed: ${response.errorMessage || "Unknown error"}`));
    }
    return ok({
        text: contentText(response.content),
        usage: response.usage,
    });
}
//# sourceMappingURL=compaction.js.map