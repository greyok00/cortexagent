import { type ForkOptions, Session, type SessionRepo as SessionRepository } from "@cortexagent/agent-core";
import type { SqliteDatabaseFactory, SqliteSessionCreateOptions, SqliteSessionListOptions, SqliteSessionMetadata, SqliteSessionRepositoryEnv } from "./types.ts";
export interface SqliteWriterLeaseOptions {
    ttlMs?: number;
    heartbeatIntervalMs?: number;
}
export interface SqliteSessionRepositoryOptions {
    env: SqliteSessionRepositoryEnv;
    sqlite: SqliteDatabaseFactory;
    databasePath: string;
    writerLease?: SqliteWriterLeaseOptions;
}
export declare class SqliteSessionRepository implements SessionRepository<SqliteSessionMetadata, SqliteSessionCreateOptions, SqliteSessionListOptions>, AsyncDisposable {
    private databasePath;
    private database;
    private databasePromise;
    private readonly operations;
    private readonly activeStorages;
    private readonly options;
    private readonly leaseOptions;
    constructor(options: SqliteSessionRepositoryOptions);
    private releaseStoragesForSession;
    private sessionFromLease;
    private claimSession;
    create(options: SqliteSessionCreateOptions): Promise<Session<SqliteSessionMetadata>>;
    open(metadata: SqliteSessionMetadata): Promise<Session<SqliteSessionMetadata>>;
    repairBranchCache(metadata: SqliteSessionMetadata): Promise<void>;
    list(options?: SqliteSessionListOptions): Promise<SqliteSessionMetadata[]>;
    delete(metadata: SqliteSessionMetadata): Promise<void>;
    fork(source: SqliteSessionMetadata, options: ForkOptions & SqliteSessionCreateOptions): Promise<Session<SqliteSessionMetadata>>;
    close(): Promise<void>;
    [Symbol.asyncDispose](): Promise<void>;
    private getDatabasePath;
    private getDatabase;
    private openDatabase;
}
//# sourceMappingURL=repo.d.ts.map