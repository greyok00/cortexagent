import type { AgentMessage } from "@cortexagent/agent-core";
import { type ImageContent, type Message, type TextContent, type Usage } from "@cortexagent/ai";
import { type BashExecutionMessage, type CustomMessage } from "./messages.ts";
export declare const CURRENT_SESSION_VERSION = 3;
export interface SessionHeader {
    type: "session";
    version?: number;
    id: string;
    timestamp: string;
    cwd: string;
    parentSession?: string;
}
export interface NewSessionOptions {
    id?: string;
    parentSession?: string;
}
export interface SessionEntryBase {
    type: string;
    id: string;
    parentId: string | null;
    timestamp: string;
}
export interface SessionMessageEntry extends SessionEntryBase {
    type: "message";
    message: AgentMessage;
}
export interface ThinkingLevelChangeEntry extends SessionEntryBase {
    type: "thinking_level_change";
    thinkingLevel: string;
}
export interface ModelChangeEntry extends SessionEntryBase {
    type: "model_change";
    provider: string;
    modelId: string;
}
export interface CompactionEntry<T = unknown> extends SessionEntryBase {
    type: "compaction";
    summary: string;
    firstKeptEntryId: string;
    tokensBefore: number;
    details?: T;
    usage?: Usage;
    fromHook?: boolean;
}
export interface BranchSummaryEntry<T = unknown> extends SessionEntryBase {
    type: "branch_summary";
    fromId: string;
    summary: string;
    details?: T;
    usage?: Usage;
    fromHook?: boolean;
}
export interface CustomEntry<T = unknown> extends SessionEntryBase {
    type: "custom";
    customType: string;
    data?: T;
}
export interface LabelEntry extends SessionEntryBase {
    type: "label";
    targetId: string;
    label: string | undefined;
}
export interface SessionInfoEntry extends SessionEntryBase {
    type: "session_info";
    name?: string;
}
export interface CustomMessageEntry<T = unknown> extends SessionEntryBase {
    type: "custom_message";
    customType: string;
    content: string | (TextContent | ImageContent)[];
    details?: T;
    display: boolean;
}
export type SessionEntry = SessionMessageEntry | ThinkingLevelChangeEntry | ModelChangeEntry | CompactionEntry | BranchSummaryEntry | CustomEntry | CustomMessageEntry | LabelEntry | SessionInfoEntry;
export type FileEntry = SessionHeader | SessionEntry;
export interface SessionTreeNode {
    entry: SessionEntry;
    children: SessionTreeNode[];
    label?: string;
    labelTimestamp?: string;
}
export interface SessionContext {
    messages: AgentMessage[];
    thinkingLevel: string;
    model: {
        provider: string;
        modelId: string;
    } | null;
}
export interface SessionInfo {
    path: string;
    id: string;
    cwd: string;
    name?: string;
    parentSessionPath?: string;
    created: Date;
    modified: Date;
    messageCount: number;
    firstMessage: string;
    allMessagesText: string;
}
export type ReadonlySessionManager = Pick<SessionManager, "getCwd" | "getSessionDir" | "getSessionId" | "getSessionFile" | "getLeafId" | "getLeafEntry" | "getEntry" | "getLabel" | "getBranch" | "buildContextEntries" | "getHeader" | "getEntries" | "getTree" | "getSessionName">;
export declare function assertValidSessionId(id: string): void;
export declare function migrateSessionEntries(entries: FileEntry[]): void;
export declare function parseSessionEntries(content: string): FileEntry[];
export declare function getLatestCompactionEntry(entries: SessionEntry[]): CompactionEntry | null;
export declare function sessionEntryToContextMessages(entry: SessionEntry): AgentMessage[];
export declare function buildContextEntries(entries: SessionEntry[], leafId?: string | null, byId?: Map<string, SessionEntry>): SessionEntry[];
export declare function buildSessionContext(entries: SessionEntry[], leafId?: string | null, byId?: Map<string, SessionEntry>): SessionContext;
export declare function getDefaultSessionDir(cwd: string, agentDir?: string): string;
export declare function loadEntriesFromFile(filePath: string): FileEntry[];
export declare function findMostRecentSession(sessionDir: string, cwd?: string): string | null;
export type SessionListProgress = (loaded: number, total: number) => void;
export declare class SessionManager {
    private sessionId;
    private sessionFile;
    private sessionDir;
    private cwd;
    private persist;
    private flushed;
    private fileEntries;
    private byId;
    private labelsById;
    private labelTimestampsById;
    private leafId;
    private constructor();
    setSessionFile(sessionFile: string): void;
    private _setSessionFile;
    newSession(options?: NewSessionOptions): string | undefined;
    private _buildIndex;
    private _rewriteFile;
    isPersisted(): boolean;
    getCwd(): string;
    getSessionDir(): string;
    usesDefaultSessionDir(): boolean;
    getSessionId(): string;
    getSessionFile(): string | undefined;
    _persist(entry: SessionEntry): void;
    private _appendEntry;
    appendMessage(message: Message | CustomMessage | BashExecutionMessage): string;
    appendThinkingLevelChange(thinkingLevel: string): string;
    appendModelChange(provider: string, modelId: string): string;
    appendCompaction<T = unknown>(summary: string, firstKeptEntryId: string, tokensBefore: number, details?: T, fromHook?: boolean, usage?: Usage): string;
    appendCustomEntry(customType: string, data?: unknown): string;
    appendSessionInfo(name: string): string;
    getSessionName(): string | undefined;
    appendCustomMessageEntry<T = unknown>(customType: string, content: string | (TextContent | ImageContent)[], display: boolean, details?: T): string;
    getLeafId(): string | null;
    getLeafEntry(): SessionEntry | undefined;
    getEntry(id: string): SessionEntry | undefined;
    getChildren(parentId: string): SessionEntry[];
    getLabel(id: string): string | undefined;
    appendLabelChange(targetId: string, label: string | undefined): string;
    getBranch(fromId?: string): SessionEntry[];
    buildContextEntries(): SessionEntry[];
    buildSessionContext(): SessionContext;
    getHeader(): SessionHeader | null;
    getEntries(): SessionEntry[];
    getTree(): SessionTreeNode[];
    branch(branchFromId: string): void;
    resetLeaf(): void;
    branchWithSummary(branchFromId: string | null, summary: string, details?: unknown, fromHook?: boolean, usage?: Usage): string;
    createBranchedSession(leafId: string): string | undefined;
    static create(cwd: string, sessionDir?: string, options?: NewSessionOptions): SessionManager;
    static open(path: string, sessionDir?: string, cwdOverride?: string): SessionManager;
    static continueRecent(cwd: string, sessionDir?: string): SessionManager;
    static inMemory(cwd?: string, options?: NewSessionOptions): SessionManager;
    static forkFrom(sourcePath: string, targetCwd: string, sessionDir?: string, options?: NewSessionOptions): SessionManager;
    static list(cwd: string, sessionDir?: string, onProgress?: SessionListProgress): Promise<SessionInfo[]>;
    static listAll(onProgress?: SessionListProgress): Promise<SessionInfo[]>;
    static listAll(sessionDir?: string, onProgress?: SessionListProgress): Promise<SessionInfo[]>;
}
//# sourceMappingURL=session-manager.d.ts.map