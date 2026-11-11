import type { SqliteDatabase } from "../types.ts";
export declare function readBranchTipIds(db: SqliteDatabase, sessionId: string): string[];
export declare function readBranchTipBranchId(db: SqliteDatabase, sessionId: string, tipId: string): string | undefined;
export declare function insertBranchTip(db: SqliteDatabase, sessionId: string, tipId: string, branchId: string): void;
export declare function updateBranchTip(db: SqliteDatabase, sessionId: string, branchId: string, oldTipId: string, newTipId: string): boolean;
export declare function deleteBranchTips(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=branch-tips.d.ts.map