import { type Entry } from "@cortexagent/agent-core";
import type { SqliteDatabase } from "../types.ts";
export interface CachedBranch {
    branchId: string;
    leafSeq: number;
}
export interface CachedBranchEntryRow {
    session_id: string;
    id: string;
    entry_seq: number;
    parent_id: string | null;
    type: Entry["type"];
    timestamp: number;
    payload: string;
}
export interface CachedBranchQuery {
    type?: Entry["type"];
    customType?: string;
    stopAtType?: Entry["type"];
    stopAtId?: string;
    cursor?: {
        afterSeq: number;
    };
    order?: "newestFirst" | "oldestFirst";
    limit?: number;
}
export declare function readCachedBranch(db: SqliteDatabase, sessionId: string, leafId: string): {
    branchId: string;
    leafSeq: number;
} | undefined;
export declare function queryCachedBranchRows(db: SqliteDatabase, sessionId: string, branch: CachedBranch, query: CachedBranchQuery): CachedBranchEntryRow[];
export declare function deleteBranchEntries(db: SqliteDatabase, sessionId: string): void;
export declare function insertBranchEntry(db: SqliteDatabase, sessionId: string, branchId: string, entryId: string, entrySeq: number, entryType: string, customType: string | null): void;
export declare function insertBranchEntriesForPath(db: SqliteDatabase, sessionId: string, branchId: string, leafId: string): void;
export declare function readBranchContainingEntry(db: SqliteDatabase, sessionId: string, entryId: string): {
    branchId: string;
    entrySeq: number;
} | undefined;
export declare function copyBranchEntriesThroughSeq(db: SqliteDatabase, sessionId: string, targetBranchId: string, sourceBranchId: string, throughSeq: number): void;
//# sourceMappingURL=branch-entries.d.ts.map