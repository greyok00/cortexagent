import { CortexServer } from "../server.ts";
import type { CortexServerOptions, CortexServerService } from "../types.ts";
export interface TestServerOptions extends CortexServerOptions {
    service?: CortexServerService;
}
export interface TestServer {
    server: CortexServer;
    service: CortexServerService;
}
export declare function createTestServer(options: TestServerOptions): TestServer;
//# sourceMappingURL=server.d.ts.map