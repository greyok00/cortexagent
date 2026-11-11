import { InteractiveMode } from "../../../src/modes/interactive/interactive-mode.ts";

// 2026-10-13 (owner order, ported from cloud fork): /model is DISABLED in
// CortexAgent — findExactModelMatch was removed with the command lockdown.
// This regression file pins the removal (the underlying matching logic still
// serves the model catalog elsewhere).
describe("issue #7443 /model cached match (fork pin)", () => {
	it("has NO findExactModelMatch (/model disabled in CortexAgent)", () => {
		const proto = (InteractiveMode as unknown as { prototype: Record<string, unknown> }).prototype;
		expect(proto.findExactModelMatch).toBeUndefined();
		expect(proto.handleModelCommand).toBeUndefined();
	});
});