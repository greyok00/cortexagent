import { afterEach, describe, expect, it } from "vitest";
import { areExperimentalFeaturesEnabled } from "../src/core/experimental.ts";

describe("areExperimentalFeaturesEnabled", () => {
	const originalCortexExperimental = process.env.CORTEX_EXPERIMENTAL;

	afterEach(() => {
		if (originalCortexExperimental === undefined) {
			delete process.env.CORTEX_EXPERIMENTAL;
		} else {
			process.env.CORTEX_EXPERIMENTAL = originalCortexExperimental;
		}
	});

	it("returns false when CORTEX_EXPERIMENTAL is unset", () => {
		delete process.env.CORTEX_EXPERIMENTAL;

		expect(areExperimentalFeaturesEnabled()).toBe(false);
	});

	it("returns false when CORTEX_EXPERIMENTAL is empty", () => {
		process.env.CORTEX_EXPERIMENTAL = "";

		expect(areExperimentalFeaturesEnabled()).toBe(false);
	});

	it("returns true when CORTEX_EXPERIMENTAL is set to 1", () => {
		process.env.CORTEX_EXPERIMENTAL = "1";

		expect(areExperimentalFeaturesEnabled()).toBe(true);
	});

	it("returns false when CORTEX_EXPERIMENTAL is set to 0", () => {
		process.env.CORTEX_EXPERIMENTAL = "0";

		expect(areExperimentalFeaturesEnabled()).toBe(false);
	});

	it("returns false when CORTEX_EXPERIMENTAL is set to a non-1 value", () => {
		process.env.CORTEX_EXPERIMENTAL = "true";

		expect(areExperimentalFeaturesEnabled()).toBe(false);
	});
});
