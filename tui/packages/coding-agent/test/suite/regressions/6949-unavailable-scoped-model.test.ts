import { InteractiveMode } from "../../../src/modes/interactive/interactive-mode.ts";

// 2026-10-13 (owner order): /model, /scoped-models and their selectors are
// DISABLED in CortexAgent-Cloud — showModelsSelector and the interactive
// scoped-model flow were removed with the command lockdown. This regression
// file pins the removal (the selector component itself still exists for the
// settings-driven path, but nothing interactive opens it anymore).
describe("issue #6949 unavailable scoped models (fork pin)", () => {
	it("has NO showModelsSelector (scoped-models flow disabled in this fork)", () => {
		const proto = (InteractiveMode as unknown as { prototype: Record<string, unknown> }).prototype;
		expect(proto.showModelsSelector).toBeUndefined();
	});
});