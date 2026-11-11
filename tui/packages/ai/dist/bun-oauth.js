import { registerBundledOAuthFlowLoaders } from "./auth/oauth/load.js";
import { openaiCodexOAuth } from "./auth/oauth/openai-codex.js";
import { openRouterOAuth } from "./auth/oauth/openrouter.js";
import { createRadiusOAuth } from "./auth/oauth/radius.js";
// Trimmed 2026-10-24 (hardened build): only flows whose providers survive the
// owner's data trim — anthropic/github-copilot/xai adapters and their data are
// gone, so their OAuth registrations are gone with them.
export function registerBunOAuthFlows() {
    registerBundledOAuthFlowLoaders({
        openaiCodex: () => openaiCodexOAuth,
        openrouter: () => openRouterOAuth,
        radius: createRadiusOAuth,
    });
}
//# sourceMappingURL=bun-oauth.js.map