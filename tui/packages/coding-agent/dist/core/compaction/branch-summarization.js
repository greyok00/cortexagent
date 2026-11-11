import { contentText } from "@cortexagent/ai";
import { convertToLlm, createBranchSummaryMessage, createCompactionSummaryMessage, createCustomMessage, } from "../messages.js";
import { completeSummarization, estimateTokens } from "./compaction.js";
import { computeFileLists, createFileOps, extractFileOpsFromMessage, formatFileOperations, SUMMARIZATION_SYSTEM_PROMPT, serializeConversation, } from "./utils.js";
export function collectEntriesForBranchSummary(session, oldLeafId, targetId) {
    if (!oldLeafId) {
        return { entries: [], commonAncestorId: null };
    }
    const oldPath = new Set(session.getBranch(oldLeafId).map((e) => e.id));
    const targetPath = session.getBranch(targetId);
    let commonAncestorId = null;
    for (let i = targetPath.length - 1; i >= 0; i--) {
        if (oldPath.has(targetPath[i].id)) {
            commonAncestorId = targetPath[i].id;
            break;
        }
    }
    const entries = [];
    let current = oldLeafId;
    while (current && current !== commonAncestorId) {
        const entry = session.getEntry(current);
        if (!entry)
            break;
        entries.push(entry);
        current = entry.parentId;
    }
    entries.reverse();
    return { entries, commonAncestorId };
}
function getMessageFromEntry(entry) {
    switch (entry.type) {
        case "message":
            if (entry.message.role === "toolResult")
                return undefined;
            return entry.message;
        case "custom_message":
            return createCustomMessage(entry.customType, entry.content, entry.display, entry.details, entry.timestamp);
        case "branch_summary":
            return createBranchSummaryMessage(entry.summary, entry.fromId, entry.timestamp);
        case "compaction":
            return createCompactionSummaryMessage(entry.summary, entry.tokensBefore, entry.timestamp);
        case "thinking_level_change":
        case "model_change":
        case "custom":
        case "label":
        case "session_info":
            return undefined;
    }
}
export function prepareBranchEntries(entries, tokenBudget = 0) {
    const messages = [];
    const fileOps = createFileOps();
    let totalTokens = 0;
    for (const entry of entries) {
        if (entry.type === "branch_summary" && !entry.fromHook && entry.details) {
            const details = entry.details;
            if (Array.isArray(details.readFiles)) {
                for (const f of details.readFiles)
                    fileOps.read.add(f);
            }
            if (Array.isArray(details.modifiedFiles)) {
                for (const f of details.modifiedFiles) {
                    fileOps.edited.add(f);
                }
            }
        }
    }
    for (let i = entries.length - 1; i >= 0; i--) {
        const entry = entries[i];
        const message = getMessageFromEntry(entry);
        if (!message)
            continue;
        extractFileOpsFromMessage(message, fileOps);
        const tokens = estimateTokens(message);
        if (tokenBudget > 0 && totalTokens + tokens > tokenBudget) {
            if (entry.type === "compaction" || entry.type === "branch_summary") {
                if (totalTokens < tokenBudget * 0.9) {
                    messages.unshift(message);
                    totalTokens += tokens;
                }
            }
            break;
        }
        messages.unshift(message);
        totalTokens += tokens;
    }
    return { messages, fileOps, totalTokens };
}
const BRANCH_SUMMARY_PREAMBLE = `The user explored a different conversation branch before returning here.
Summary of that exploration:

`;
const BRANCH_SUMMARY_PROMPT = `Create a structured summary of this conversation branch for context when returning later.

Use this EXACT format:

## Goal
[What was the user trying to accomplish in this branch?]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Work that was started but not finished]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [What should happen next to continue this work]

Keep each section concise. Preserve exact file paths, function names, and error messages.`;
export async function generateBranchSummary(entries, options) {
    const { model, apiKey, headers, env, signal, customInstructions, replaceInstructions, reserveTokens, streamFn, retry, callbacks, } = options;
    const contextWindow = model.contextWindow || 262144;
    // reserveTokens is 15% of the model window — same convention as
    // DEFAULT_COMPACTION_SETTINGS in compaction.ts. When reserveTokens is
    // not passed, derive it here so the budget matches the live engine-server
    // n_ctx (real locked default 131072) rather than any stale fallback.
    const effectiveReserve = reserveTokens ?? Math.max(1024, Math.floor(contextWindow * 0.15));
    const tokenBudget = contextWindow - effectiveReserve;
    const { messages, fileOps } = prepareBranchEntries(entries, tokenBudget);
    if (messages.length === 0) {
        return { summary: "No content to summarize" };
    }
    const llmMessages = convertToLlm(messages);
    const conversationText = serializeConversation(llmMessages);
    let instructions;
    if (replaceInstructions && customInstructions) {
        instructions = customInstructions;
    }
    else if (customInstructions) {
        instructions = `${BRANCH_SUMMARY_PROMPT}\n\nAdditional focus: ${customInstructions}`;
    }
    else {
        instructions = BRANCH_SUMMARY_PROMPT;
    }
    const promptText = `<conversation>\n${conversationText}\n</conversation>\n\n${instructions}`;
    const summarizationMessages = [
        {
            role: "user",
            content: [{ type: "text", text: promptText }],
            timestamp: Date.now(),
        },
    ];
    const context = { systemPrompt: SUMMARIZATION_SYSTEM_PROMPT, messages: summarizationMessages };
    const requestOptions = { apiKey, headers, env, signal, maxTokens: 2048 };
    const response = await completeSummarization(model, context, requestOptions, streamFn, retry, callbacks);
    if (response.stopReason === "aborted") {
        return { aborted: true };
    }
    if (response.stopReason === "error") {
        return { error: response.errorMessage || "Summarization failed" };
    }
    let summary = contentText(response.content);
    summary = BRANCH_SUMMARY_PREAMBLE + summary;
    const { readFiles, modifiedFiles } = computeFileLists(fileOps);
    summary += formatFileOperations(readFiles, modifiedFiles);
    return {
        summary: summary || "No summary generated",
        usage: response.usage,
        readFiles,
        modifiedFiles,
    };
}
//# sourceMappingURL=branch-summarization.js.map