import type { ByteTransportFactory } from "./transport.ts";
export interface UnixTransportOptions {
    path: string;
    maxPendingBytes?: number;
}
export declare function createUnixTransportFactory(options: UnixTransportOptions): ByteTransportFactory;
//# sourceMappingURL=unix.d.ts.map