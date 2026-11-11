import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const telemetryIndex = fileURLToPath(new URL("../../telemetry/src/index.ts", import.meta.url));
const aiIndex = fileURLToPath(new URL("../../ai/src/index.ts", import.meta.url));
const agentIndex = fileURLToPath(new URL("../../agent/src/index.ts", import.meta.url));
const agentNode = fileURLToPath(new URL("../../agent/src/node.ts", import.meta.url));
const agentSessionTesting = fileURLToPath(new URL("../../agent/src/harness/session/testing/index.ts", import.meta.url));

export default defineConfig({
	test: {
		globals: true,
		environment: "node",
		reporters: process.env.GITHUB_ACTIONS ? ["dot", "github-actions"] : ["dot"],
		coverage: {
			provider: "v8",
			all: true,
			include: ["src/**/*.ts"],
			exclude: ["src/**/*.d.ts"],
			reporter: ["text", "html", "lcov"],
			reportsDirectory: "coverage",
		},
	},
	resolve: {
		alias: [
			{ find: /^@cortex\/telemetry$/, replacement: telemetryIndex },
			{ find: /^@cortex\/agent-core\/session\/testing$/, replacement: agentSessionTesting },
			{ find: /^@cortex\/agent-core\/node$/, replacement: agentNode },
			{ find: /^@cortex\/agent-core$/, replacement: agentIndex },
			{ find: /^@cortex\/ai$/, replacement: aiIndex },
		],
	},
});
