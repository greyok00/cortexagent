import { fileURLToPath } from "node:url";
import { defineConfig, mergeConfig } from "vitest/config";
import baseConfig, { workspaceSourcePaths } from "../../vitest.base.ts";

export default mergeConfig(
	baseConfig,
	defineConfig({
		test: {
			globals: true,
			environment: "node",
			testTimeout: 30000,
			
			env: { CORTEX_OFFLINE: "1" },
			unstubEnvs: true,
			reporters: process.env.GITHUB_ACTIONS ? ["dot", "github-actions"] : ["dot"],
			silent: "passed-only",
			server: {
				deps: {
					external: [/@silvia-odwyer\/photon-node/],
				},
			},
		},
		resolve: {
			alias: [
				{
					find: /^@cortex\/client$/,
					replacement: fileURLToPath(new URL("../client/src/index.ts", import.meta.url)),
				},
				{
					find: /^@cortex\/protocol$/,
					replacement: fileURLToPath(new URL("../protocol/src/index.ts", import.meta.url)),
				},
				{ find: /^@cortex00\/cortex-ai$/, replacement: workspaceSourcePaths.aiIndex },
				{ find: /^@cortex00\/cortex-ai\/oauth$/, replacement: workspaceSourcePaths.aiOAuth },
				{ find: /^@cortex00\/cortex-agent-core$/, replacement: workspaceSourcePaths.agentIndex },
				{ find: /^@cortex00\/cortex-tui$/, replacement: workspaceSourcePaths.tuiIndex },
			],
		},
	}),
);
