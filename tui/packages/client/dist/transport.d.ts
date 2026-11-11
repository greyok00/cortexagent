export interface ByteTransport {
    send(chunk: Uint8Array): Promise<void>;
    close(): void;
}
export interface ByteTransportHandlers {
    onData(chunk: Uint8Array): void;
    onClose(): void;
    onError(error: Error): void;
}
export type ByteTransportFactory = (handlers: ByteTransportHandlers) => ByteTransport | Promise<ByteTransport>;
//# sourceMappingURL=transport.d.ts.map