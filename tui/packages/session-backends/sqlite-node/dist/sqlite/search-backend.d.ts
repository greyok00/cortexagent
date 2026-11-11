import type { SessionSearch, SessionSearchHit } from "@cortexagent/agent-core";
import type { SqliteDatabaseFactory, SqliteSessionMetadata, SqliteSessionRepositoryEnv } from "./types.ts";
export interface SqliteSessionSearchOptions {
    env: Pick<SqliteSessionRepositoryEnv, "absolutePath" | "createDir">;
    sqlite: SqliteDatabaseFactory;
    databasePath: string;
}
export interface SqliteSessionSearchHit extends SessionSearchHit {
    readonly metadata: SqliteSessionMetadata;
    readonly timestamp: number;
    readonly score: number;
}
export declare function createSqliteSessionSearch(options: SqliteSessionSearchOptions): SessionSearch<SqliteSessionSearchHit>;
//# sourceMappingURL=search-backend.d.ts.map