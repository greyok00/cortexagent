import { CortexServer } from "../server.js";
import { TestServerService } from "./service.js";
export function createTestServer(options) {
    const service = options.service ?? new TestServerService();
    return {
        server: new CortexServer(service, {
            listeners: options.listeners,
            maxFrameLength: options.maxFrameLength,
            handshakeTimeoutMs: options.handshakeTimeoutMs,
            serverId: options.serverId,
            onError: options.onError,
        }),
        service,
    };
}
//# sourceMappingURL=server.js.map