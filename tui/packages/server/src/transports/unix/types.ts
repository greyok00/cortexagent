import type { CortexServerOptions } from "../../types.ts";

export interface UnixListenerOptions {
	path: string;

	mode?: number;

	maxPendingBytes?: number;
	gracefulCloseTimeoutMs?: number;

	maxFrameLength?: number;
	onError?: (error: Error) => void;
}

export interface UnixServerOptions extends Omit<CortexServerOptions, "listeners">, UnixListenerOptions {}
