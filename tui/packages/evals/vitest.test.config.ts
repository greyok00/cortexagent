import { defineConfig, mergeConfig } from "vitest/config";
import baseConfig, { workspaceSourcePaths } from "../../vitest.base.ts";

export default mergeConfig(
	baseConfig,
	defineConfig({
		test: {
			include: ["test/**/*.test.ts"],
		},
		resolve: {
			alias: [{ find: /^@cortex\/coding-agent$/, replacement: workspaceSourcePaths.codingAgentIndex }],
		},
	}),
);
