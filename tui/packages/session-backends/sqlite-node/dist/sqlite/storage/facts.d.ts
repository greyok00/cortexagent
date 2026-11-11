import type { SqliteDatabase } from "../types.ts";
export interface FactRow {
    session_id: string;
    seq: number;
    kind: string;
    key: string | null;
    value: string | null;
}
export declare function appendFact(db: SqliteDatabase, sessionId: string, seq: number, kind: string, key: string | null, value: string | null): void;
export declare function readLatestFact(db: SqliteDatabase, sessionId: string, kind: string, key: string | null): FactRow | undefined;
export declare function readLatestLabelFacts(db: SqliteDatabase, sessionId: string): {
    key: string;
    value: string;
}[];
export declare function readFactRows(db: SqliteDatabase, sessionId: string, options?: {
    afterSeq?: number;
    limit?: number;
}): FactRow[];
export declare function deleteFactRows(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=facts.d.ts.map