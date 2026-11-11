import type { SqliteDatabase } from "../types.ts";
export interface WriterLease {
    ownerId: string;
    fence: number;
    expiresAtMs: number;
}
export declare function acquireWriterLease(db: SqliteDatabase, sessionId: string, ownerId: string, now: number, expiresAtMs: number): {
    ownerId: string;
    fence: number;
    expiresAtMs: number;
} | undefined;
export declare function renewWriterLease(db: SqliteDatabase, sessionId: string, lease: WriterLease, now: number, expiresAtMs: number): boolean;
export declare function releaseWriterLease(db: SqliteDatabase, sessionId: string, lease: WriterLease): void;
export declare function deleteWriterLease(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=writer-leases.d.ts.map