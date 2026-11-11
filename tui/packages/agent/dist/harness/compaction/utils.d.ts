import { type Message } from "@cortexagent/ai";
import type { AgentMessage } from "../../types.ts";
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
//# sourceMappingURL=utils.d.ts.map