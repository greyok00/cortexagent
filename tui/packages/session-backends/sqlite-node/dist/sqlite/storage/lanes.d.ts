import type { SqliteDatabase } from "../types.ts";
export interface LaneRow {
    session_id: string;
    lane: string;
    leaf_id: string | null;
    open_operation_id: string | null;
}
export interface LaneMoveRow {
    session_id: string;
    seq: number;
    lane: string;
    leaf_id: string | null;
}
export declare function createInitialLane(db: SqliteDatabase, sessionId: string, lane?: string, leafId?: string | null): void;
export declare function readLanes(db: SqliteDatabase, sessionId: string): {
    session_id: string;
    lane: string;
    leaf_id: string | null;
    open_operation_id: string | null;
}[];
export declare function readLane(db: SqliteDatabase, sessionId: string, lane: string): LaneRow | undefined;
export declare function readLaneHead(db: SqliteDatabase, sessionId: string, lane: string): {
    leafId: string | null;
};
export declare function createLane(db: SqliteDatabase, sessionId: string, seq: number, lane: string, leafId: string | null): void;
export declare function moveLane(db: SqliteDatabase, sessionId: string, seq: number, lane: string, leafId: string | null): void;
export declare function setLaneLeaf(db: SqliteDatabase, sessionId: string, lane: string, leafId: string | null): void;
export declare function startLaneOperation(db: SqliteDatabase, sessionId: string, lane: string, runId: string): void;
export declare function finishLaneOperation(db: SqliteDatabase, sessionId: string, lane: string, runId: string): void;
export declare function readLaneMoveRows(db: SqliteDatabase, sessionId: string, options?: {
    afterSeq?: number;
    limit?: number;
}): LaneMoveRow[];
export declare function deleteLaneRows(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=lanes.d.ts.map