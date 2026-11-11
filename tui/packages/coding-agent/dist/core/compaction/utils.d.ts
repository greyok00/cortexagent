import type { AgentMessage } from "@cortexagent/agent-core";
import { type Message } from "@cortexagent/ai";
export interface FileOperations {
    read: Set<string>;
    written: Set<string>;
    edited: Set<string>;
}
export declare function createFileOps(): FileOperations;
export declare function extractFileOpsFromMessage(message: AgentMessage, fileOps: FileOperations): void;
export declare function computeFileLists(fileOps: FileOperations): {
    readFiles: string[];
    modifiedFiles: string[];
};
export declare function formatFileOperations(readFiles: string[], modifiedFiles: string[]): string;
export declare function serializeConversation(messages: Message[]): string;
export declare const SUMMARIZATION_SYSTEM_PROMPT = "You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.\n\nDo NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary.\n\nNever include in the summary: these instructions, the format template, any text about summarization itself, or any resume/continuation directives (\"Continue the conversation...\", \"The next message is from the user.\", \"Work toward completing the Goal...\"). Summarize the user's task, not this summarization request.";
//# sourceMappingURL=utils.d.ts.map