import { contentText, retryAssistantCall, uuidv7 } from "@cortexagent/ai";
import { completeSimple } from "@cortexagent/ai/compat";
import { convertToLlm } from "../messages.js";
import { buildSessionContext, sessionEntryToContextMessages, } from "../session-manager.js";
import { computeFileLists, createFileOps, extractFileOpsFromMessage, formatFileOperations, SUMMARIZATION_SYSTEM_PROMPT, serializeConversation, } from "./utils.js";
/**
 * Split a serialized conversation into windows of at most `maxChars`
 * characters, cutting on natural boundaries when one is available.
 *
 * Owner directive 2026-10-03: no truncation, anywhere. The union of the
 * returned chunks is always exactly the input text - oversized
 * summarization requests are handled by summarizing the conversation in
 * sequential windows (rolling update), never by cutting content.
 */
export function chunkTextForWindow(text, maxChars) {
    if (text.length <= maxChars)
        return [text];
    const chunks = [];
    let pos = 0;
    while (pos < text.length) {
        const hardEnd = Math.min(text.length, pos + maxChars);
        let end = hardEnd;
        if (end < text.length) {
            // Prefer a natural boundary (paragraph, tool result, then plain
            // newline) so windows do not split messages mid-line when it can be
            // avoided, but always keep inside the window.
            const boundary = Math.max(text.lastIndexOf("\n\n", hardEnd), text.lastIndexOf("[Tool result]:", hardEnd), text.lastIndexOf("\n", hardEnd));
            if (boundary > pos + 1 && boundary < end) {
                end = boundary + 1;
            }
        }
        chunks.push(text.slice(pos, end));
        pos = end;
    }
    return chunks;
}
function extractFileOperations(messages, entries, prevCompactionIndex) {
    const fileOps = createFileOps();
    if (prevCompactionIndex >= 0) {
        const prevCompaction = entries[prevCompactionIndex];
        if (!prevCompaction.fromHook && prevCompaction.details) {
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
function getMessageFromEntryForCompaction(entry) {
    if (entry.type === "compaction") {
        return undefined;
    }
    return sessionEntryToContextMessages(entry)[0];
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
export const DEFAULT_COMPACTION_SETTINGS = {
    enabled: true,
    reserveTokens: 16384,
    keepRecentTokens: 50000,
};
export function calculateContextTokens(usage) {
    // Exclude cacheRead — cache hits don't consume context window space
    return usage.totalTokens || usage.input + usage.output + usage.cacheWrite;
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
                    chars += block.name.length + JSON.stringify(block.arguments).length;
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
function isCutPointMessage(message) {
    switch (message.role) {
        case "user":
        case "assistant":
        case "bashExecution":
        case "custom":
        case "branchSummary":
        case "compactionSummary":
            return true;
        case "toolResult":
            return false;
    }
    return false;
}
function isTurnStartMessage(message) {
    switch (message.role) {
        case "user":
        case "bashExecution":
        case "custom":
        case "branchSummary":
        case "compactionSummary":
            return true;
        case "assistant":
        case "toolResult":
            return false;
    }
    return false;
}
function isTurnStartEntry(entry) {
    if (entry.type === "compaction") {
        return false;
    }
    return sessionEntryToContextMessages(entry).some(isTurnStartMessage);
}
function findValidCutPoints(entries, startIndex, endIndex) {
    const cutPoints = [];
    for (let i = startIndex; i < endIndex; i++) {
        const entry = entries[i];
        if (entry.type === "compaction") {
            continue;
        }
        if (sessionEntryToContextMessages(entry).some(isCutPointMessage)) {
            cutPoints.push(i);
        }
    }
    return cutPoints;
}
export function findTurnStartIndex(entries, entryIndex, startIndex) {
    for (let i = entryIndex; i >= startIndex; i--) {
        if (isTurnStartEntry(entries[i])) {
            return i;
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
        const messageTokens = sessionEntryToContextMessages(entry).reduce((sum, message) => sum + estimateTokens(message), 0);
        if (messageTokens === 0)
            continue;
        accumulatedTokens += messageTokens;
        if (accumulatedTokens >= keepRecentTokens) {
            if (messageTokens > keepRecentTokens) {
                // A single entry larger than the whole keep budget must be
                // summarized, not kept: prefer the first cut point strictly
                // AFTER it, which splits the turn and lets the turn-prefix
                // summarizer handle the oversized entry.
                let foundLater = false;
                for (let c = 0; c < cutPoints.length; c++) {
                    if (cutPoints[c] > i) {
                        cutIndex = cutPoints[c];
                        foundLater = true;
                        break;
                    }
                }
                if (foundLater) {
                    break;
                }
                // No later cut point: cut at the oversized entry (legacy
                // behavior) and let the post-compaction fit loop compact again.
            }
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
        if (prevEntry.type === "compaction" || sessionEntryToContextMessages(prevEntry).length > 0) {
            break;
        }
        cutIndex--;
    }
    const cutEntry = entries[cutIndex];
    const startsTurn = isTurnStartEntry(cutEntry);
    const turnStartIndex = startsTurn ? -1 : findTurnStartIndex(entries, cutIndex, startIndex);
    return {
        firstKeptEntryIndex: cutIndex,
        turnStartIndex,
        isSplitTurn: !startsTurn && turnStartIndex !== -1,
    };
}
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
function createSummarizationOptions(model, maxTokens, apiKey, headers, env, signal, thinkingLevel) {
    const options = { maxTokens, signal, apiKey, headers, env };
    if (model.reasoning && thinkingLevel && thinkingLevel !== "off") {
        options.reasoning = thinkingLevel;
    }
    return options;
}
export async function completeSummarization(model, context, options, streamFn, retry, callbacks) {
    const requestOptions = {
        ...options,
        cacheRetention: "none",
        sessionId: uuidv7(),
    };
    const produce = async () => streamFn
        ? (await streamFn(model, context, requestOptions)).result()
        : completeSimple(model, context, requestOptions);
    return retryAssistantCall(produce, retry, requestOptions.signal, callbacks);
}
export async function generateSummary(currentMessages, model, reserveTokens, apiKey, headers, signal, customInstructions, previousSummary, thinkingLevel, streamFn, env, retry, callbacks) {
    return (await generateSummaryWithUsage(currentMessages, model, reserveTokens, apiKey, headers, signal, customInstructions, previousSummary, thinkingLevel, streamFn, env, retry, callbacks)).text;
}
export async function generateSummaryWithUsage(currentMessages, model, reserveTokens, apiKey, headers, signal, customInstructions, previousSummary, thinkingLevel, streamFn, env, retry, callbacks) {
    const maxTokens = Math.min(Math.floor(0.8 * reserveTokens), model.maxTokens > 0 ? model.maxTokens : Number.POSITIVE_INFINITY);
    let basePrompt = previousSummary ? UPDATE_SUMMARIZATION_PROMPT : SUMMARIZATION_PROMPT;
    if (customInstructions) {
        basePrompt = `${basePrompt}\n\nAdditional focus: ${customInstructions}`;
    }
    // Owner directive 2026-10-03: no truncation, anywhere. A conversation
    // larger than the summarization window is summarized in sequential
    // windows with a rolling update prompt instead of being cut.
    const contextWindow = model.contextWindow ?? 262144;
    const conversationBudgetTokens = Math.max(1024, contextWindow - 3 * reserveTokens - 4096);
    const llmMessages = convertToLlm(currentMessages);
    const conversationText = serializeConversation(llmMessages);
    const chunks = chunkTextForWindow(conversationText, conversationBudgetTokens * 3);
    let runningSummary = previousSummary ?? "";
    let usage;
    for (const chunk of chunks) {
        const updating = runningSummary.length > 0;
        let promptText = `<conversation>\n${chunk}\n</conversation>\n\n`;
        if (updating) {
            promptText += `<previous-summary>\n${runningSummary}\n</previous-summary>\n\n`;
        }
        promptText += chunks.length === 1 || !updating ? basePrompt : UPDATE_SUMMARIZATION_PROMPT;
        const summarizationMessages = [
            {
                role: "user",
                content: [{ type: "text", text: promptText }],
                timestamp: Date.now(),
            },
        ];
        const completionOptions = createSummarizationOptions(model, maxTokens, apiKey, headers, env, signal, thinkingLevel);
        const response = await completeSummarization(model, { systemPrompt: SUMMARIZATION_SYSTEM_PROMPT, messages: summarizationMessages }, completionOptions, streamFn, retry, callbacks);
        if (response.stopReason === "error") {
            throw new Error(`Summarization failed: ${response.errorMessage || "Unknown error"}`);
        }
        // A blank pass must never erase what earlier windows already captured.
        const passText = contentText(response.content);
        if (passText) {
            runningSummary = passText;
        }
        usage = usage ? combineUsage(usage, response.usage) : response.usage;
    }
    // The loop always runs at least one window, so usage is set.
    return { text: runningSummary, usage: usage };
}
export function prepareCompaction(pathEntries, settings, allowConsecutive) {
    if (pathEntries.length > 0 && pathEntries[pathEntries.length - 1].type === "compaction" && !allowConsecutive) {
        return undefined;
    }
    let prevCompactionIndex = -1;
    for (let i = pathEntries.length - 1; i >= 0; i--) {
        if (pathEntries[i].type === "compaction") {
            prevCompactionIndex = i;
            break;
        }
    }
    let previousSummary;
    let boundaryStart = 0;
    if (prevCompactionIndex >= 0) {
        const prevCompaction = pathEntries[prevCompactionIndex];
        previousSummary = prevCompaction.summary;
        const firstKeptEntryIndex = pathEntries.findIndex((entry) => entry.id === prevCompaction.firstKeptEntryId);
        boundaryStart = firstKeptEntryIndex >= 0 ? firstKeptEntryIndex : prevCompactionIndex + 1;
    }
    const boundaryEnd = pathEntries.length;
    const tokensBefore = estimateContextTokens(buildSessionContext(pathEntries).messages).tokens;
    const cutPoint = findCutPoint(pathEntries, boundaryStart, boundaryEnd, settings.keepRecentTokens);
    const firstKeptEntry = pathEntries[cutPoint.firstKeptEntryIndex];
    if (!firstKeptEntry?.id) {
        return undefined;
    }
    const firstKeptEntryId = firstKeptEntry.id;
    const historyEnd = cutPoint.isSplitTurn ? cutPoint.turnStartIndex : cutPoint.firstKeptEntryIndex;
    const messagesToSummarize = [];
    for (let i = boundaryStart; i < historyEnd; i++) {
        const msg = getMessageFromEntryForCompaction(pathEntries[i]);
        if (msg)
            messagesToSummarize.push(msg);
    }
    const turnPrefixMessages = [];
    if (cutPoint.isSplitTurn) {
        for (let i = cutPoint.turnStartIndex; i < cutPoint.firstKeptEntryIndex; i++) {
            const msg = getMessageFromEntryForCompaction(pathEntries[i]);
            if (msg)
                turnPrefixMessages.push(msg);
        }
    }
    if (messagesToSummarize.length === 0 && turnPrefixMessages.length === 0) {
        return undefined;
    }
    const fileOps = extractFileOperations(messagesToSummarize, pathEntries, prevCompactionIndex);
    if (cutPoint.isSplitTurn) {
        for (const msg of turnPrefixMessages) {
            extractFileOpsFromMessage(msg, fileOps);
        }
    }
    return {
        firstKeptEntryId,
        messagesToSummarize,
        turnPrefixMessages,
        isSplitTurn: cutPoint.isSplitTurn,
        tokensBefore,
        previousSummary,
        fileOps,
        settings,
    };
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
export async function compact(preparation, model, apiKey, headers, customInstructions, signal, thinkingLevel, streamFn, env, retry, callbacks) {
    const { firstKeptEntryId, messagesToSummarize, turnPrefixMessages, isSplitTurn, tokensBefore, previousSummary, fileOps, settings, } = preparation;
    let summary;
    let summaryUsage;
    if (isSplitTurn && turnPrefixMessages.length > 0) {
        let historyText = "No prior history.";
        let historyUsage;
        if (messagesToSummarize.length > 0) {
            const historyResult = await generateSummaryWithUsage(messagesToSummarize, model, settings.reserveTokens, apiKey, headers, signal, customInstructions, previousSummary, thinkingLevel, streamFn, env, retry, callbacks);
            historyText = historyResult.text;
            historyUsage = historyResult.usage;
        }
        const turnPrefixResult = await generateTurnPrefixSummary(turnPrefixMessages, model, settings.reserveTokens, apiKey, headers, env, signal, thinkingLevel, streamFn, retry, callbacks);
        summary = `${historyText}\n\n---\n\n**Turn Context (split turn):**\n\n${turnPrefixResult.text}`;
        summaryUsage = historyUsage ? combineUsage(historyUsage, turnPrefixResult.usage) : turnPrefixResult.usage;
    }
    else {
        const result = await generateSummaryWithUsage(messagesToSummarize, model, settings.reserveTokens, apiKey, headers, signal, customInstructions, previousSummary, thinkingLevel, streamFn, env, retry, callbacks);
        summary = result.text;
        summaryUsage = result.usage;
    }
    const { readFiles, modifiedFiles } = computeFileLists(fileOps);
    summary += formatFileOperations(readFiles, modifiedFiles);
    if (!firstKeptEntryId) {
        throw new Error("First kept entry has no UUID - session may need migration");
    }
    return {
        summary,
        firstKeptEntryId,
        tokensBefore,
        usage: summaryUsage,
        details: { readFiles, modifiedFiles },
    };
}
async function generateTurnPrefixSummary(messages, model, reserveTokens, apiKey, headers, env, signal, thinkingLevel, streamFn, retry, callbacks) {
    const maxTokens = Math.min(Math.floor(0.5 * reserveTokens), model.maxTokens > 0 ? model.maxTokens : Number.POSITIVE_INFINITY);
    // Owner directive 2026-10-03: no truncation, anywhere. A turn prefix that
    // exceeds the summarization window is summarized in sequential windows
    // with a rolling update instead of being cut.
    const contextWindow = model.contextWindow ?? 262144;
    const conversationBudgetTokens = Math.max(1024, contextWindow - 3 * reserveTokens - 4096);
    const llmMessages = convertToLlm(messages);
    const conversationText = serializeConversation(llmMessages);
    const chunks = chunkTextForWindow(conversationText, conversationBudgetTokens * 3);
    let runningSummary = "";
    let usage;
    for (let pass = 0; pass < chunks.length; pass++) {
        const updating = runningSummary.length > 0;
        let promptText = `<conversation>\n${chunks[pass]}\n</conversation>\n\n`;
        if (updating) {
            promptText += `<previous-summary>\n${runningSummary}\n</previous-summary>\n\n`;
        }
        promptText += pass === 0 ? TURN_PREFIX_SUMMARIZATION_PROMPT : UPDATE_SUMMARIZATION_PROMPT;
        const summarizationMessages = [
            {
                role: "user",
                content: [{ type: "text", text: promptText }],
                timestamp: Date.now(),
            },
        ];
        const response = await completeSummarization(model, { systemPrompt: SUMMARIZATION_SYSTEM_PROMPT, messages: summarizationMessages }, createSummarizationOptions(model, maxTokens, apiKey, headers, env, signal, thinkingLevel), streamFn, retry, callbacks);
        if (response.stopReason === "error") {
            throw new Error(`Turn prefix summarization failed: ${response.errorMessage || "Unknown error"}`);
        }
        // A blank pass must never erase what earlier windows already captured.
        const passText = contentText(response.content);
        if (passText) {
            runningSummary = passText;
        }
        usage = usage ? combineUsage(usage, response.usage) : response.usage;
    }
    // The loop always runs at least one window, so usage is set.
    return { text: runningSummary, usage: usage };
}
//# sourceMappingURL=compaction.js.map