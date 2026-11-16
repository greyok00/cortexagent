import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const telemetrySrcIndex = fileURLToPath(new URL("../telemetry/src/index.ts", import.meta.url));

export default defineConfig({
	test: {
		globals: true,
		environment: "node",
		testTimeout: 30000, // 30 seconds for API calls
		reporters: process.env.GITHUB_ACTIONS ? ["dot", "github-actions"] : ["dot"],
		silent: "passed-only",
		// Hermetic tests: ambient ANTHROPIC_BASE_URL (set by local gateway tooling)
		// would reroute every anthropic-messages test harness away from its own
		// loopback server; empty string is treated as unset by `|| model.baseUrl`.
		env: { ANTHROPIC_BASE_URL: "" },
	},
	resolve: {
		alias: [{ find: /^@cortex\/telemetry$/, replacement: telemetrySrcIndex }],
	},
});