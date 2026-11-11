import { type Socket } from "node:net";
import type { ByteConnection } from "../../connection.ts";
import type { CortexServerListener } from "../../listener.ts";
import type { UnixListenerOptions } from "./types.ts";
export declare function validateUnixSocketPath(path: string, description?: string): void;
export declare class UnixByteConnection implements ByteConnection {
    private readonly socket;
    private readonly gracefulCloseTimeoutMs;
    private readonly maxPendingBytes;
    private pendingBytes;
    private closedValue;
    private closing;
    private writeTail;
    private closePromise?;
    private resolveClose?;
    constructor(socket: Socket, gracefulCloseTimeoutMs: number, maxPendingBytes: number);
    get closed(): boolean;
    send(chunk: Uint8Array): Promise<void>;
    close(finalChunk?: Uint8Array): Promise<void>;
    markClosed(): void;
    private write;
}
export declare function createUnixListener(options: UnixListenerOptions): CortexServerListener;
//# sourceMappingURL=listener.d.ts.map