import { DatabaseSync } from "node:sqlite";
import { sql } from "./sqlite/sql.js";
function isNamedParameters(value) {
    if (value === null || typeof value !== "object")
        return false;
    if (Array.isArray(value) || ArrayBuffer.isView(value))
        return false;
    return true;
}
function isAsyncResult(value) {
    return value !== null && (typeof value === "object" || typeof value === "function") && "then" in value;
}
class NodeSqliteStatement {
    statement;
    constructor(statement) {
        this.statement = statement;
    }
    run(...params) {
        const [first, ...rest] = params;
        const result = isNamedParameters(first)
            ? this.statement.run(first, ...rest)
            : this.statement.run(...params);
        return {
            changes: Number(result.changes),
            lastInsertRowid: result.lastInsertRowid === undefined ? undefined : Number(result.lastInsertRowid),
        };
    }
    get(...params) {
        const [first, ...rest] = params;
        return (isNamedParameters(first)
            ? this.statement.get(first, ...rest)
            : this.statement.get(...params));
    }
    all(...params) {
        const [first, ...rest] = params;
        return (isNamedParameters(first)
            ? this.statement.all(first, ...rest)
            : this.statement.all(...params));
    }
    iterate(...params) {
        const [first, ...rest] = params;
        return (isNamedParameters(first)
            ? this.statement.iterate(first, ...rest)
            : this.statement.iterate(...params));
    }
}
class NodeSqliteDatabase {
    db;
    constructor(db) {
        this.db = db;
    }
    exec(sql) {
        this.db.exec(sql);
    }
    prepare(sql) {
        return new NodeSqliteStatement(this.db.prepare(sql));
    }
    transaction(fn) {
        sql `BEGIN IMMEDIATE`.exec(this);
        try {
            const result = fn();
            if (isAsyncResult(result)) {
                throw new TypeError("SQLite transaction callbacks must be synchronous");
            }
            sql `COMMIT`.exec(this);
            return result;
        }
        catch (error) {
            try {
                sql `ROLLBACK`.exec(this);
            }
            catch {
                // Ignore rollback errors to rethrow original error.
            }
            throw error;
        }
    }
    close() {
        this.db.close();
    }
}
export function wrapNodeSqliteDatabase(db) {
    return new NodeSqliteDatabase(db);
}
export function createNodeSqliteFactory() {
    return {
        async open(path) {
            return new NodeSqliteDatabase(new DatabaseSync(path));
        },
    };
}
export * from "./sqlite/index.js";
//# sourceMappingURL=index.js.map