import { describe, expect, it } from "vitest";
import { getCortexUserAgent } from "../src/utils/cortex-user-agent.ts";

describe("getCortexUserAgent", () => {
	it("formats the user agent expected by cortex", () => {
		const runtime = process.versions.bun ? `bun/${process.versions.bun}` : `node/${process.version}`;
		const userAgent = getCortexUserAgent("1.2.3");

		expect(userAgent).toBe(`cortex/1.2.3 (${process.platform}; ${runtime}; ${process.arch})`);
		expect(userAgent).toMatch(/^cortex\/[^\s()]+ \([^;()]+;\s*[^;()]+;\s*[^()]+\)$/);
	});
});
