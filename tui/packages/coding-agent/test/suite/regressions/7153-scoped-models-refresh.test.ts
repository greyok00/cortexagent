import { InteractiveMode } from "../../../src/modes/interactive/interactive-mode.ts";

// 2026-10-13 (owner order): the scoped-models selector flow is DISABLED in
// CortexAgent-Cloud (/scoped-models arm removed, showModelsSelector deleted).
// These regression tests pinned behavior of the interactive flow; they now
// pin the removal itself.
describe("issue #7153 scoped models refresh (fork pin)", () => {
	it("has NO showModelsSelector (scoped-models flow disabled in this fork)", () => {
		const proto = (InteractiveMode as unknown as { prototype: Record<string, unknown> }).prototype;
		expect(proto.showModelsSelector).toBeUndefined();
	});
});