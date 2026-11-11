import type { SqliteDatabase } from "./types.ts";
export interface SqliteMigration {
    id: string;
    order: number;
    sql: string;
}
export declare function loadMigrations(): Promise<SqliteMigration[]>;
export declare function applyMigrations(db: SqliteDatabase): Promise<void>;
//# sourceMappingURL=migrations.d.ts.map