import type { Entry, EntryOrder } from "@cortexagent/agent-core";
import type { SqliteDatabase } from "../types.ts";
export interface EntryRow {
    session_id: string;
    seq: number;
    id: string;
    parent_id: string | null;
    type: Entry["type"];
    timestamp: number;
    payload: string;
}
export interface NewEntryRow {
    seq: number;
    id: string;
    parentId: string | null;
    type: Entry["type"];
    timestamp: number;
    payload: string;
}
export declare function entryPayload(entry: Entry): Record<string, unknown>;
export declare function insertEntryRow(db: SqliteDatabase, sessionId: string, entry: NewEntryRow): void;
export declare function readEntryRow(db: SqliteDatabase, sessionId: string, entryId: string): EntryRow | undefined;
export declare function readEntryRows(db: SqliteDatabase, sessionId: string, options?: {
    afterSeq?: number;
    cursor?: {
        afterSeq: number;
    };
    type?: Entry["type"];
    order?: EntryOrder;
    limit?: number;
}): EntryRow[];
export declare function idExistsInEntries(db: SqliteDatabase, sessionId: string, id: string): boolean;
export declare function deleteEntryRows(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=entries.d.ts.map