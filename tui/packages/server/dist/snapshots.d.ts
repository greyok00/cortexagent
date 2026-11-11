import { type EventEnvelope, type ModelMetadata, type ServerSnapshot, type SessionMetadata } from "@cortexagent/protocol";
import type { ConnectionState } from "./connection.ts";
import type { CortexServerService } from "./types.ts";
interface ServerSnapshotPublisherOptions {
    serverId: string;
    service: CortexServerService;
    connections: Set<ConnectionState>;
    isClosing: () => boolean;
    listSessions: () => Promise<SessionMetadata[]>;
    sendMessage: (connection: ConnectionState, message: EventEnvelope) => Promise<boolean>;
    reportError: (error: unknown) => void;
}
export declare class ServerSnapshotPublisher {
    private readonly options;
    private revision;
    private broadcastQueue;
    constructor(options: ServerSnapshotPublisherOptions);
    get currentRevision(): number;
    get(models?: ModelMetadata[]): Promise<ServerSnapshot>;
    broadcast(): Promise<void>;
    private performBroadcast;
}
export {};
//# sourceMappingURL=snapshots.d.ts.map