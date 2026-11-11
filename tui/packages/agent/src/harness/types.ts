import type { SimpleStreamOptions, Transport } from "@cortexagent/ai";
import type { Static, TSchema } from "typebox";
import type { AgentTool, AgentToolResult, AgentToolUpdateCallback } from "../types.ts";

export type Result<TValue, TError> = { ok: true; value: TValue } | { ok: false; error: TError };

export function ok<TValue, TError>(value: TValue): Result<TValue, TError> {
	return { ok: true, value };
}

export function err<TValue, TError>(error: TError): Result<TValue, TError> {
	return { ok: false, error };
}

export function getOrThrow<TValue, TError>(result: Result<TValue, TError>): TValue {
	if (!result.ok) throw result.error;
	return result.value;
}

export function getOrUndefined<TValue extends object, TError>(result: Result<TValue, TError>): TValue | undefined {
	return result.ok ? result.value : undefined;
}

export function toError(error: unknown): Error {
	if (error instanceof Error) return error;
	if (typeof error === "string") return new Error(error);
	try {
		return new Error(JSON.stringify(error));
	} catch {
		return new Error(String(error));
	}
}

export interface Skill {
	name: string;

	description: string;

	content: string;

	filePath: string;

	disableModelInvocation?: boolean;
}

export interface PromptTemplate {
	name: string;

	description?: string;

	content: string;
}

export interface AgentHarnessResources<
	TSkill extends Skill = Skill,
	TPromptTemplate extends PromptTemplate = PromptTemplate,
> {
	promptTemplates?: TPromptTemplate[];

	skills?: TSkill[];
}

export type AgentHarnessTool<
	TContext extends object | undefined,
	TParameters extends TSchema = TSchema,
	TDetails = unknown,
> = Omit<AgentTool<TParameters, TDetails>, "execute"> & {
	execute(
		toolCallId: string,
		params: Static<TParameters>,
		signal: AbortSignal | undefined,
		onUpdate: AgentToolUpdateCallback<TDetails> | undefined,
		context: TContext,
	): Promise<AgentToolResult<TDetails>>;
};

export type AgentHarnessToolContextSource<TContext extends object | undefined> =
	| TContext
	| (() => TContext | Promise<TContext>);

export interface AgentHarnessStreamOptions {
	transport?: Transport;

	timeoutMs?: number;

	maxRetries?: number;

	maxRetryDelayMs?: number;

	headers?: Record<string, string>;

	metadata?: SimpleStreamOptions["metadata"];

	cacheRetention?: SimpleStreamOptions["cacheRetention"];
}

export interface AgentHarnessStreamOptionsPatch
	extends Omit<Partial<AgentHarnessStreamOptions>, "headers" | "metadata"> {
	headers?: Record<string, string | undefined>;

	metadata?: Record<string, unknown | undefined>;
}

export type FileKind = "file" | "directory" | "symlink";

export type FileErrorCode =
	| "aborted"
	| "not_found"
	| "permission_denied"
	| "not_directory"
	| "is_directory"
	| "invalid"
	| "not_supported"
	| "unknown";

export class FileError extends Error {
	public code: FileErrorCode;

	public path?: string;

	constructor(code: FileErrorCode, message: string, path?: string, cause?: Error) {
		super(message, cause === undefined ? undefined : { cause });
		this.name = "FileError";
		this.code = code;
		this.path = path;
	}
}

export type ExecutionErrorCode =
	| "aborted"
	| "timeout"
	| "shell_unavailable"
	| "spawn_error"
	| "callback_error"
	| "unknown";

export class ExecutionError extends Error {
	public code: ExecutionErrorCode;

	constructor(code: ExecutionErrorCode, message: string, cause?: Error) {
		super(message, cause === undefined ? undefined : { cause });
		this.name = "ExecutionError";
		this.code = code;
	}
}

export type CompactionErrorCode = "aborted" | "summarization_failed";

export class CompactionError extends Error {
	public code: CompactionErrorCode;

	constructor(code: CompactionErrorCode, message: string, cause?: Error) {
		super(message, cause === undefined ? undefined : { cause });
		this.name = "CompactionError";
		this.code = code;
	}
}

export type BranchSummaryErrorCode = "aborted" | "summarization_failed";

export class BranchSummaryError extends Error {
	public code: BranchSummaryErrorCode;

	constructor(code: BranchSummaryErrorCode, message: string, cause?: Error) {
		super(message, cause === undefined ? undefined : { cause });
		this.name = "BranchSummaryError";
		this.code = code;
	}
}

export interface FileInfo {
	name: string;

	path: string;

	kind: FileKind;

	size: number;

	mtimeMs: number;
}

export interface FileSystem {
	cwd: string;

	absolutePath(path: string, abortSignal?: AbortSignal): Promise<Result<string, FileError>>;

	joinPath(parts: string[], abortSignal?: AbortSignal): Promise<Result<string, FileError>>;

	readTextFile(path: string, abortSignal?: AbortSignal): Promise<Result<string, FileError>>;

	readTextLines(
		path: string,
		options?: { maxLines?: number; abortSignal?: AbortSignal },
	): Promise<Result<string[], FileError>>;

	readBinaryFile(path: string, abortSignal?: AbortSignal): Promise<Result<Uint8Array, FileError>>;

	writeFile(path: string, content: string | Uint8Array, abortSignal?: AbortSignal): Promise<Result<void, FileError>>;

	appendFile(path: string, content: string | Uint8Array, abortSignal?: AbortSignal): Promise<Result<void, FileError>>;

	renameFile(sourcePath: string, destinationPath: string, abortSignal?: AbortSignal): Promise<Result<void, FileError>>;

	fileInfo(path: string, abortSignal?: AbortSignal): Promise<Result<FileInfo, FileError>>;

	listDir(path: string, abortSignal?: AbortSignal): Promise<Result<FileInfo[], FileError>>;

	canonicalPath(path: string, abortSignal?: AbortSignal): Promise<Result<string, FileError>>;

	exists(path: string, abortSignal?: AbortSignal): Promise<Result<boolean, FileError>>;

	createDir(
		path: string,
		options?: { recursive?: boolean; abortSignal?: AbortSignal },
	): Promise<Result<void, FileError>>;

	remove(
		path: string,
		options?: { recursive?: boolean; force?: boolean; abortSignal?: AbortSignal },
	): Promise<Result<void, FileError>>;

	createTempDir(prefix?: string, abortSignal?: AbortSignal): Promise<Result<string, FileError>>;

	createTempFile(options?: {
		prefix?: string;
		suffix?: string;
		abortSignal?: AbortSignal;
	}): Promise<Result<string, FileError>>;

	cleanup(): Promise<void>;
}

export interface ShellExecOptions {
	cwd?: string;

	env?: Record<string, string>;

	inheritEnv?: boolean;

	timeout?: number;

	abortSignal?: AbortSignal;

	onStdout?: (chunk: string) => void;

	onStderr?: (chunk: string) => void;
}

export interface Shell {
	exec(
		command: string,
		options?: ShellExecOptions,
	): Promise<Result<{ stdout: string; stderr: string; exitCode: number }, ExecutionError>>;

	cleanup(): Promise<void>;
}

export interface ExecutionEnv extends FileSystem, Shell {}
