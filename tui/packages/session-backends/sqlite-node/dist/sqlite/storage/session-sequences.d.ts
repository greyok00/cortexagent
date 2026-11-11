import type { SqliteDatabase } from "../types.ts";
export declare function createSequence(db: SqliteDatabase, sessionId: string, nextSeq?: number): void;
export declare function getNextSequence(db: SqliteDatabase, sessionId: string): number;
export declare function setNextSequence(db: SqliteDatabase, sessionId: string, nextSeq: number): void;
export declare function advanceSequence(db: SqliteDatabase, sessionId: string, seq: number): void;
export declare function deleteSequence(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=session-sequences.d.ts.map