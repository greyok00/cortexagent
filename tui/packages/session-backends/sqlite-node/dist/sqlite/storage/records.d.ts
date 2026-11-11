import type { SqliteDatabase } from "../types.ts";
export interface RecordRow {
    session_id: string;
    seq: number;
    id: string;
    lane: string;
    run_id: string | null;
    type: string;
    op_kind: string | null;
    timestamp: number;
    payload: string;
}
export interface NewRecordRow {
    seq: number;
    id: string;
    lane: string;
    runId?: string;
    type: string;
    opKind?: string;
    timestamp: number;
    payload: string;
}
export declare function appendRecordRow(db: SqliteDatabase, sessionId: string, record: NewRecordRow): void;
export declare function idExistsInRecords(db: SqliteDatabase, sessionId: string, id: string): boolean;
export declare function deleteRecordRows(db: SqliteDatabase, sessionId: string): void;
export declare function readRecordRows(db: SqliteDatabase, sessionId: string, query?: {
    lane?: string;
    type?: string;
    runId?: string;
    operationKind?: string;
    afterSeq?: number;
    order?: "newestFirst" | "oldestFirst";
    limit?: number;
}): RecordRow[];
export declare function readOpenOperationRows(db: SqliteDatabase, sessionId: string, lane: string, _options?: {
    limit?: number;
}): RecordRow[];
//# sourceMappingURL=records.d.ts.map