import { DatabaseSync } from "node:sqlite";
import type { SqliteDatabase, SqliteDatabaseFactory } from "./sqlite/types.ts";
export declare function wrapNodeSqliteDatabase(db: DatabaseSync): SqliteDatabase;
export declare function createNodeSqliteFactory(): SqliteDatabaseFactory;
export * from "./sqlite/index.ts";
//# sourceMappingURL=index.d.ts.map