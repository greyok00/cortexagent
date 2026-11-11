import type { SqliteDatabase, SqliteRunResult } from "./types.ts";
type SqlTemplateValue = unknown | SqlQuery;
export declare class SqlQuery {
    readonly queryText: string;
    readonly params: readonly unknown[];
    constructor(queryText: string, params?: readonly unknown[]);
    exec(db: SqliteDatabase): void;
    run(db: SqliteDatabase): SqliteRunResult;
    get<TRow extends object>(db: SqliteDatabase): TRow | undefined;
    all<TRow extends object>(db: SqliteDatabase): TRow[];
    iterate<TRow extends object>(db: SqliteDatabase): Iterable<TRow>;
}
export declare function sql(strings: TemplateStringsArray, ...values: SqlTemplateValue[]): SqlQuery;
export declare function joinSqlFragments(fragments: readonly SqlQuery[], separator: string): SqlQuery;
export {};
//# sourceMappingURL=sql.d.ts.map