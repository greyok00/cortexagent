import type { SessionRepo } from "../types.ts";

export interface SessionBackendFixture extends AsyncDisposable {
	readonly repository: SessionRepo;
}

export type SessionBackendFixtureFactory = () => Promise<SessionBackendFixture>;

export interface SessionBackendConformanceCase {
	readonly group: string;
	readonly name: string;
	run(): Promise<void>;
}
