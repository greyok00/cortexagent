import type { SqliteDatabase } from "./types.ts";
export declare function deleteBranchCache(db: SqliteDatabase, sessionId: string): void;
export declare function rebuildBranchCache(db: SqliteDatabase, sessionId: string): void;
export declare function buildCachedBranch(db: SqliteDatabase, sessionId: string, leafId: string): void;
export declare function appendEntryToBranchCache(db: SqliteDatabase, sessionId: string, entryId: string, entrySeq: number, entryType: string, customType: string | null, parentId: string | null): void;
//# sourceMappingURL=branch-cache.d.ts.map