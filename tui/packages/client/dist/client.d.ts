import { type ServerEvent, type ServerSnapshot, type SessionMetadata } from "@cortexagent/protocol";
import { type AcquireSessionOptions, type CortexSessionHandle } from "./session-handle.ts";
import type { ConnectionState, ConnectionStateChange, CortexClientOptions, CreateSessionOptions, Unsubscribe } from "./types.ts";
export declare class CortexClient {
    #private;
    constructor(options: CortexClientOptions);
    get disposed(): boolean;
    get connectionState(): ConnectionState;
    get connected(): boolean;
    get snapshot(): ServerSnapshot | undefined;
    static connect(options: CortexClientOptions): Promise<CortexClient>;
    connect(): Promise<ServerSnapshot>;
    reconnect(): Promise<ServerSnapshot>;
    disconnect(reason?: string): void;
    subscribe(listener: (snapshot: ServerSnapshot) => void): Unsubscribe;
    onEvent(listener: (event: ServerEvent) => void): Unsubscribe;
    onConnectionStateChange(listener: (change: ConnectionStateChange) => void): Unsubscribe;
    listSessions(): Promise<readonly SessionMetadata[]>;
    createSession(options?: CreateSessionOptions): Promise<CortexSessionHandle>;
    attachSession(sessionId: string): Promise<CortexSessionHandle>;
    acquireSession(sessionId: string, options: AcquireSessionOptions): Promise<CortexSessionHandle>;
    dispose(): Promise<void>;
    [Symbol.asyncDispose](): Promise<void>;
}
//# sourceMappingURL=client.d.ts.map