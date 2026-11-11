import type { JsonValue, ProtocolErrorCode } from "@cortexagent/protocol";
export type CortexServerOperationErrorCode = Extract<ProtocolErrorCode, "busy" | "session_locked" | "not_found" | "invalid_request" | "not_implemented">;
export declare const INTERNAL_SERVER_ERROR_MESSAGE = "Internal server error";
export declare const NOT_IMPLEMENTED_MESSAGE = "Operation is not implemented";
export declare class CortexServerError extends Error {
    readonly code: CortexServerOperationErrorCode;
    readonly details: JsonValue | undefined;
    constructor(code: CortexServerOperationErrorCode, message: string, details?: JsonValue);
}
export declare class SessionBusyError extends CortexServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class SessionLockedError extends CortexServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class SessionNotFoundError extends CortexServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class NotImplementedError extends CortexServerError {
    constructor();
}
export declare class InternalServerError extends Error {
    constructor(cause: unknown);
}
//# sourceMappingURL=errors.d.ts.map