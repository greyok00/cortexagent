import { setKeybindings } from "@cortexagent/tui";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { KeybindingsManager } from "../src/core/keybindings.ts";
import { OAuthSelectorComponent } from "../src/modes/interactive/components/oauth-selector.ts";
import { InteractiveMode } from "../src/modes/interactive/interactive-mode.ts";
import { initTheme } from "../src/modes/interactive/theme/theme.ts";
import { stripAnsi } from "../src/utils/ansi.ts";

describe("OAuthSelectorComponent", () => {
	beforeAll(() => {
		initTheme("dark");
	});

	beforeEach(() => {
		setKeybindings(new KeybindingsManager());
	});

	// 2026-10-13 (owner order): /login and /logout are DISABLED in
	// CortexAgent-Cloud — the getLoginProviderOptions projection was removed
	// with the whole orphaned login flow. This test pins the removal.
	it("has NO getLoginProviderOptions (login flow removed in this fork)", () => {
		const proto = (InteractiveMode as unknown as { prototype: Record<string, unknown> }).prototype;
		expect(proto.getLoginProviderOptions).toBeUndefined();
		expect(proto.handleLoginCommand).toBeUndefined();
		expect(proto.showOAuthSelector).toBeUndefined();
	});

	it("renders an option without compiled auth status as unconfigured", () => {
		const selector = new OAuthSelectorComponent(
			"login",
			[{ id: "google", name: "Google", authType: "api_key", status: undefined }],
			() => {},
			() => {},
		);
		const output = stripAnsi(selector.render(80).join("\n"));
		expect(output).toContain("Google");
		expect(output).toContain("unconfigured");
	});
});