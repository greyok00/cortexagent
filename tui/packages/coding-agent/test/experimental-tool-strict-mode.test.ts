import { afterEach, describe, expect, it } from "vitest";
import {
	createBashToolDefinition,
	createEditToolDefinition,
	createReadToolDefinition,
	createWriteToolDefinition,
} from "../src/core/tools/index.ts";

function createBuiltInTools() {
	return [
		createReadToolDefinition(process.cwd()),
		createBashToolDefinition(process.cwd()),
		createEditToolDefinition(process.cwd()),
		createWriteToolDefinition(process.cwd()),
	];
}

describe("experimental strict built-in tools", () => {
	const originalCortexExperimental = process.env.CORTEX_EXPERIMENTAL;

	afterEach(() => {
		if (originalCortexExperimental === undefined) delete process.env.CORTEX_EXPERIMENTAL;
		else process.env.CORTEX_EXPERIMENTAL = originalCortexExperimental;
	});

	it("only enables strict-prefer sampling in experimental mode", () => {
		delete process.env.CORTEX_EXPERIMENTAL;
		const normalTools = createBuiltInTools();
		process.env.CORTEX_EXPERIMENTAL = "1";
		const experimentalTools = createBuiltInTools();

		for (const [index, tool] of experimentalTools.entries()) {
			expect(tool.constrainedSampling).toEqual({ type: "json_schema", strict: "prefer" });
			expect(tool.parameters).toEqual(normalTools[index]?.parameters);
			expect(normalTools[index]?.constrainedSampling).toBeUndefined();
		}
	});
});
