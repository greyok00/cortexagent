import type { JsonValue, ProtocolErrorCode } from "@cortexagent/protocol";

export type CortexServerOperationErrorCode = Extract<
	ProtocolErrorCode,
	"busy" | "session_locked" | "not_found" | "invalid_request" | "not_implemented"
>;

export const INTERNAL_SERVER_ERROR_MESSAGE = "Internal server error";
export const NOT_IMPLEMENTED_MESSAGE = "Operation is not implemented";

export class CortexServerError extends Error {
	readonly code: CortexServerOperationErrorCode;
	readonly details: JsonValue | undefined;

	constructor(code: CortexServerOperationErrorCode, message: string, details?: JsonValue) {
		super(message);
		this.name = "CortexServerError";
		this.code = code;
		this.details = details;
	}
}

export class SessionBusyError extends CortexServerError {
	constructor(message = "Session is busy", details?: JsonValue) {
		super("busy", message, details);
		this.name = "SessionBusyError";
	}
}

export class SessionLockedError extends CortexServerError {
	constructor(message = "Session is locked", details?: JsonValue) {
		super("session_locked", message, details);
		this.name = "SessionLockedError";
	}
}

export class SessionNotFoundError extends CortexServerError {
	constructor(message = "Session was not found", details?: JsonValue) {
		super("not_found", message, details);
		this.name = "SessionNotFoundError";
	}
}

export class NotImplementedError extends CortexServerError {
	constructor() {
		super("not_implemented", NOT_IMPLEMENTED_MESSAGE);
		this.name = "NotImplementedError";
	}
}

export class InternalServerError extends Error {
	constructor(cause: unknown) {
		super(INTERNAL_SERVER_ERROR_MESSAGE, { cause });
		this.name = "InternalServerError";
	}
}
