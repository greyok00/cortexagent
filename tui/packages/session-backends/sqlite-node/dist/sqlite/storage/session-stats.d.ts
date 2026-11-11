import { type SessionStats } from "@cortexagent/agent-core";
import type { Usage } from "@cortexagent/ai";
import type { SqliteDatabase } from "../types.ts";
export interface SessionStatsRow {
    session_id: string;
    message_count: number;
    cached_tokens: number;
    uncached_tokens: number;
    total_tokens: number;
    cost_total: number;
}
export declare function createStats(db: SqliteDatabase, sessionId: string, messageCount?: number): void;
export declare function readStats(db: SqliteDatabase, sessionId: string): SessionStats;
export declare function incrementMessageCount(db: SqliteDatabase, sessionId: string): void;
export declare function addUsageToStats(db: SqliteDatabase, sessionId: string, usage: Usage): void;
export declare function deleteStats(db: SqliteDatabase, sessionId: string): void;
//# sourceMappingURL=session-stats.d.ts.map