import { expect } from "vitest";
import { describeEval } from "vitest-evals";
import { createCortexCodingAgentHarness } from "./cortex-harness.ts";

const piCodingAgentHarness = createCortexCodingAgentHarness({ noTools: "all" });

describeEval("Cortex Coding Agent smoke", { harness: piCodingAgentHarness }, (it) => {
	it("runs a basic prompt end to end", async ({ run }) => {
		const result = await run("What's the capital of France? Respond with only the city name.");

		expect(result.output.trim()).toBe("Paris");
		expect(result.errors).toEqual([]);
		expect(result.usage.provider).toBe(process.env.CORTEX_PROVIDER);
		expect(result.usage.model).toBe(process.env.CORTEX_MODEL);
		expect(result.usage.totalTokens).toBeGreaterThan(0);
	});
});
