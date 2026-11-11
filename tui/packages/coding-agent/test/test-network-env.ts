import { vi } from "vitest";

export function allowNetwork(): void {
	vi.stubEnv("CORTEX_OFFLINE", undefined);
}
