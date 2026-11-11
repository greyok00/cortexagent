import { type ClientMessage, type Command, type ResponseEnvelope, type ServerMessage } from "@cortexagent/protocol";
export interface WireChannel {
    send(chunk: Uint8Array): Promise<void>;
    sendFragmented(chunk: Uint8Array, splitAt: number): Promise<void>;
    close(): Promise<void>;
}
export declare class ProtocolTestClient {
    readonly messages: ServerMessage[];
    private readonly channel;
    private readonly decoder;
    private readonly waiters;
    private readonly closedDeferred;
    private requestSequence;
    private closedValue;
    constructor(channel: WireChannel);
    get closed(): boolean;
    hello(version?: number): Promise<ServerMessage>;
    request(command: Command, id?: string): Promise<ResponseEnvelope>;
    sendMessage(message: ClientMessage): Promise<void>;
    sendBytes(chunk: Uint8Array): Promise<void>;
    sendFragmentedMessage(message: ClientMessage, splitAt: number): Promise<void>;
    next(predicate: (message: ServerMessage) => boolean): Promise<ServerMessage>;
    nextFrom(index: number, predicate: (message: ServerMessage) => boolean): Promise<ServerMessage>;
    waitForClose(): Promise<void>;
    close(): Promise<void>;
    receive(chunk: Uint8Array): void;
    markClosed(): void;
    fail(error: Error): void;
}
export declare function connectUnixTestClient(path: string): Promise<ProtocolTestClient>;
//# sourceMappingURL=client.d.ts.map