import { CortexServer } from "../server.ts";
import type { CortexServerOptions, CortexServerService } from "../types.ts";
import { TestServerService } from "./service.ts";

export interface TestServerOptions extends CortexServerOptions {
	service?: CortexServerService;
}

export interface TestServer {
	server: CortexServer;
	service: CortexServerService;
}

export function createTestServer(options: TestServerOptions): TestServer {
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
