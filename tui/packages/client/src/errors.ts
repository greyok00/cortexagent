import type { JsonValue, ProtocolError, ProtocolErrorCode } from "@cortexagent/protocol";

export class CortexServerError extends Error {
	readonly code: ProtocolErrorCode;
	readonly details: JsonValue | undefined;

	constructor(error: ProtocolError) {
		super(error.message);
		this.name = "CortexServerError";
		this.code = error.code;
		this.details = error.details;
	}
}

export class CortexDisconnectedError extends Error {
	constructor(message = "Cortex client is disconnected") {
		super(message);
		this.name = "CortexDisconnectedError";
	}
}

export class CortexClientDisposedError extends Error {
	constructor() {
		super("Cortex client is disposed");
		this.name = "CortexClientDisposedError";
	}
}

export class CortexSessionOwnershipError extends Error {
	readonly sessionId: string;

	constructor(sessionId: string, message: string) {
		super(message);
		this.name = "CortexSessionOwnershipError";
		this.sessionId = sessionId;
	}
}

export class CortexSessionDetachedError extends Error {
	readonly sessionId: string;

	constructor(sessionId: string) {
		super(`Session ${sessionId} is not attached`);
		this.name = "CortexSessionDetachedError";
		this.sessionId = sessionId;
	}
}

export function toError(error: unknown): Error {
	return error instanceof Error ? error : new Error(String(error));
}

export function toDisconnectedError(error: unknown): CortexDisconnectedError {
	const cause = toError(error);
	return cause instanceof CortexDisconnectedError ? cause : new CortexDisconnectedError(cause.message);
}
