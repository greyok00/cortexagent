import { existsSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fauxAssistantMessage, registerFauxProvider } from "@cortexagent/ai/compat";
import { afterEach, describe, expect, it } from "vitest";
import {
	type CreateAgentSessionRuntimeFactory,
	createAgentSessionFromServices,
	createAgentSessionRuntime,
	createAgentSessionServices,
} from "../src/core/agent-session-runtime.ts";
import { AuthStorage } from "../src/core/auth-storage.ts";
import { ModelRuntime } from "../src/core/model-runtime.ts";
import { SessionManager } from "../src/core/session-manager.ts";

// 2026-10-26 owner order: the agent must never sit idle after a truncated
// turn. Before this, a `length` stop whose compact-and-retry recovery did not
// land ended the run and waited for a typed CONTINUE (299 min and 62 min of
// dead time on 2026-10-25). With recovery unavailable here, the harness must
// re-prompt itself and actually issue the next model request.
describe("AgentSession auto-continue after a truncated turn", () => {
	const cleanups: Array<() => Promise<void> | void> = [];

	afterEach(async () => {
		while (cleanups.length > 0) {
			await cleanups.pop()?.();
		}
	});

	async function createSession() {
		const tempDir = join(tmpdir(), `cortex-auto-continue-${Date.now()}-${Math.random().toString(36).slice(2)}`);
		mkdirSync(tempDir, { recursive: true });

		const faux = registerFauxProvider();
		faux.setResponses([
			fauxAssistantMessage("partial work", { stopReason: "length" }),
			fauxAssistantMessage("finished the task", { stopReason: "stop" }),
		]);

		const authStorage = AuthStorage.inMemory();
		await authStorage.modify(faux.getModel().provider, async () => ({ type: "api_key", key: "faux-key" }));
		const modelRuntime = await ModelRuntime.create({
			credentials: authStorage,
			modelsPath: join(tempDir, "models.json"),
		});
		const model = faux.getModel();
		modelRuntime.registerProvider(model.provider, {
			baseUrl: model.baseUrl,
			api: model.api,
			models: [
				{
					id: model.id,
					name: model.name,
					api: model.api,
					reasoning: model.reasoning,
					input: model.input,
					cost: model.cost,
					contextWindow: model.contextWindow,
					maxTokens: model.maxTokens,
					baseUrl: model.baseUrl,
				},
			],
		});

		const createRuntime: CreateAgentSessionRuntimeFactory = async ({ cwd, sessionManager, sessionStartEvent }) => {
			const services = await createAgentSessionServices({
				agentDir: tempDir,
				modelRuntime,
				model,
				resourceLoaderOptions: {
					extensionFactories: [],
					noSkills: true,
					noPromptTemplates: true,
					noThemes: true,
				},
				cwd,
			});
			return {
				...(await createAgentSessionFromServices({
					services,
					sessionManager,
					sessionStartEvent,
					model,
				})),
				services,
				diagnostics: services.diagnostics,
			};
		};

		const runtimeHost = await createAgentSessionRuntime(createRuntime, {
			cwd: tempDir,
			agentDir: tempDir,
			sessionManager: SessionManager.create(tempDir),
		});
		await runtimeHost.session.bindExtensions({});
		// Recovery unavailable: this is the exact shape of the stalled runs,
		// where compaction did not land and the harness then waited forever.
		runtimeHost.session.setAutoCompactionEnabled(false);

		cleanups.push(async () => {
			await runtimeHost.dispose();
			faux.unregister();
			if (existsSync(tempDir)) {
				rmSync(tempDir, { recursive: true, force: true });
			}
		});

		return { runtimeHost, faux };
	}

	it("issues another model request on its own after a length stop", async () => {
		const { runtimeHost, faux } = await createSession();

		await runtimeHost.session.prompt("do the work");

		expect(faux.state.callCount).toBeGreaterThanOrEqual(2);

		const messages = runtimeHost.session.messages;
		const autoMessages = messages.filter(
			(m) =>
				m.role === "user" &&
				typeof m.content !== "string" &&
				m.content.some((part) => part.type === "text" && part.text.includes("[auto-continue 1/")),
		);
		expect(autoMessages).toHaveLength(1);
	});
});
