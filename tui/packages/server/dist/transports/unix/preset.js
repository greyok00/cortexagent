import { CortexServer } from "../../server.js";
import { createUnixListener } from "./listener.js";
export function createUnixServer(service, options) {
    const listener = createUnixListener({
        path: options.path,
        mode: options.mode,
        maxFrameLength: options.maxFrameLength,
        maxPendingBytes: options.maxPendingBytes,
        gracefulCloseTimeoutMs: options.gracefulCloseTimeoutMs,
        onError: options.onError,
    });
    return new CortexServer(service, {
        listeners: [listener],
        maxFrameLength: options.maxFrameLength,
        handshakeTimeoutMs: options.handshakeTimeoutMs,
        serverId: options.serverId,
        onError: options.onError,
    });
}
//# sourceMappingURL=preset.js.map