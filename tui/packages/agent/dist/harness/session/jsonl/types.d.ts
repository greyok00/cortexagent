import type { FileSystem } from "../../types.ts";
import type { JsonValue, SessionCreateOptions, SessionMetadata } from "../types.ts";
export type JsonlSessionRepoFileSystem = Pick<FileSystem, "absolutePath" | "joinPath" | "readTextFile" | "readTextLines" | "writeFile" | "appendFile" | "renameFile" | "fileInfo" | "listDir" | "exists" | "createDir" | "remove">;
export interface JsonlSessionRepoOptions {
    fs: JsonlSessionRepoFileSystem;
    sessionsRoot: string;
}
export interface JsonlSessionMetadata extends SessionMetadata {
    cwd: string;
    path: string;
    modifiedAt: number;
    sourceFormat: 3 | 4;
    legacyParentSessionPath?: string;
    metadata?: Record<string, JsonValue>;
}
export interface JsonlSessionCreateOptions extends SessionCreateOptions {
    cwd: string;
    metadata?: Record<string, JsonValue>;
}
export interface JsonlSessionListOptions {
    cwd?: string;
}
export interface JsonlV4Header {
    kind: "header";
    version: 4;
    id: string;
    createdAt: number;
    cwd: string;
    parentSessionId?: string;
    legacyParentSessionPath?: string;
    metadata?: Record<string, JsonValue>;
}
//# sourceMappingURL=types.d.ts.map