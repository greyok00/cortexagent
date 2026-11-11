import { registerBundledOAuthFlowLoaders } from "./auth/oauth/load.ts";
import { openaiCodexOAuth } from "./auth/oauth/openai-codex.ts";
import { openRouterOAuth } from "./auth/oauth/openrouter.ts";
import { createRadiusOAuth } from "./auth/oauth/radius.ts";

// Trimmed 2026-10-24 (hardened build): only flows whose providers survive the
// owner's data trim — anthropic/github-copilot/xai adapters and their data are
// gone, so their OAuth registrations are gone with them.
export function registerBunOAuthFlows(): void {
	registerBundledOAuthFlowLoaders({
		openaiCodex: () => openaiCodexOAuth,
		openrouter: () => openRouterOAuth,
		radius: createRadiusOAuth,
	});
}