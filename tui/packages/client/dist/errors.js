export class CortexServerError extends Error {
    code;
    details;
    constructor(error) {
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
    sessionId;
    constructor(sessionId, message) {
        super(message);
        this.name = "CortexSessionOwnershipError";
        this.sessionId = sessionId;
    }
}
export class CortexSessionDetachedError extends Error {
    sessionId;
    constructor(sessionId) {
        super(`Session ${sessionId} is not attached`);
        this.name = "CortexSessionDetachedError";
        this.sessionId = sessionId;
    }
}
export function toError(error) {
    return error instanceof Error ? error : new Error(String(error));
}
export function toDisconnectedError(error) {
    const cause = toError(error);
    return cause instanceof CortexDisconnectedError ? cause : new CortexDisconnectedError(cause.message);
}
//# sourceMappingURL=errors.js.map