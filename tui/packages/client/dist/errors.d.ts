import type { JsonValue, ProtocolError, ProtocolErrorCode } from "@cortexagent/protocol";
export declare class CortexServerError extends Error {
    readonly code: ProtocolErrorCode;
    readonly details: JsonValue | undefined;
    constructor(error: ProtocolError);
}
export declare class CortexDisconnectedError extends Error {
    constructor(message?: string);
}
export declare class CortexClientDisposedError extends Error {
    constructor();
}
export declare class CortexSessionOwnershipError extends Error {
    readonly sessionId: string;
    constructor(sessionId: string, message: string);
}
export declare class CortexSessionDetachedError extends Error {
    readonly sessionId: string;
    constructor(sessionId: string);
}
export declare function toError(error: unknown): Error;
export declare function toDisconnectedError(error: unknown): CortexDisconnectedError;
//# sourceMappingURL=errors.d.ts.map