export const INTERNAL_SERVER_ERROR_MESSAGE = "Internal server error";
export const NOT_IMPLEMENTED_MESSAGE = "Operation is not implemented";
export class CortexServerError extends Error {
    code;
    details;
    constructor(code, message, details) {
        super(message);
        this.name = "CortexServerError";
        this.code = code;
        this.details = details;
    }
}
export class SessionBusyError extends CortexServerError {
    constructor(message = "Session is busy", details) {
        super("busy", message, details);
        this.name = "SessionBusyError";
    }
}
export class SessionLockedError extends CortexServerError {
    constructor(message = "Session is locked", details) {
        super("session_locked", message, details);
        this.name = "SessionLockedError";
    }
}
export class SessionNotFoundError extends CortexServerError {
    constructor(message = "Session was not found", details) {
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
    constructor(cause) {
        super(INTERNAL_SERVER_ERROR_MESSAGE, { cause });
        this.name = "InternalServerError";
    }
}
//# sourceMappingURL=errors.js.map