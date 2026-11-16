import type { FileSystem, SessionCreateOptions, SessionMetadata } from "@cortexagent/agent-core";

export interface SqliteRunResult {
	changes: number;

	lastInsertRowid?: number;
}

export interface SqliteStatement {
	run(...params: unknown[]): SqliteRunResult;
	get<TRow extends object>(...params: unknown[]): TRow | undefined;
	all<TRow extends object>(...params: unknown[]): TRow[];
	iterate<TRow extends object>(...params: unknown[]): Iterable<TRow>;
}

export interface SqliteDatabase {
	exec(sql: string): void;
	prepare(sql: string): SqliteStatement;

	transaction<T>(fn: () => T): T;
	close(): void;
}

export interface SqliteDatabaseFactory {
	open(path: string): Promise<SqliteDatabase>;
}

export interface SqliteSessionMetadata extends SessionMetadata {
	cwd: string;
	path: string;
	parentSessionId?: string;

	name?: string;

	metadata?: Record<string, unknown>;
}

export interface SqliteSessionCreateOptions extends SessionCreateOptions {
	cwd: string;
	parentSessionId?: string;
	metadata?: Record<string, unknown>;
}

export interface SqliteSessionListOptions {
	cwd?: string;
}

export type SqliteSessionRepositoryEnv = Pick<FileSystem, "absolutePath" | "createDir" | "exists">;
