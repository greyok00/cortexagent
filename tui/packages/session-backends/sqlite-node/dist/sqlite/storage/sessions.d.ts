import type { SqliteDatabase, SqliteSessionMetadata } from "../types.ts";
export interface SessionRow {
    id: string;
    created_at: number;
    metadata: string | null;
    cwd: string;
    parent_session_id: string | null;
    has_session_name: number;
    session_name: string | null;
}
export interface NewSessionRow {
    id: string;
    createdAt: number;
    cwd: string;
    parentSessionId?: string;
    metadata?: Record<string, unknown>;
}
export declare function sessionExists(db: SqliteDatabase, sessionId: string): boolean;
export declare function insertSessionRow(db: SqliteDatabase, session: NewSessionRow): void;
export declare function readSessionRow(db: SqliteDatabase, sessionId: string): SessionRow | undefined;
export declare function readSessionRows(db: SqliteDatabase, options?: {
    cwd?: string;
}): SessionRow[];
export declare function deleteSessionRow(db: SqliteDatabase, sessionId: string): void;
export declare function decodeSessionMetadata(row: SessionRow, path: string): SqliteSessionMetadata;
//# sourceMappingURL=sessions.d.ts.map