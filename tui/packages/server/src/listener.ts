import type { ByteConnectionAcceptor } from "./connection.ts";

export interface CortexServerListener {
	readonly address?: string;

	start(accept: ByteConnectionAcceptor): Promise<void>;
	close(): Promise<void>;
}
