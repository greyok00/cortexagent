import type {
	ApiKeyCredential,
	AuthContext,
	AuthResult,
	Model,
	Provider,
	ProviderStreamOptions,
	RefreshModelsContext,
} from "@cortexagent/ai";
import { stream, streamSimple } from "@cortexagent/ai/compat";
import { LlamaClient, type LlamaModelInfo, llamaInferenceUrl, normalizeLlamaServerUrl } from "./client.ts";

export const LLAMA_PROVIDER_ID = "the engine";
export const DEFAULT_ENGINE_BIN_URL = "http://127.0.0.1:8080";
function credentialServerUrl(credential: ApiKeyCredential | undefined): string | undefined {
	const value = credential?.env?.LLAMA_BASE_URL;
	return typeof value === "string" && value.trim() ? normalizeLlamaServerUrl(value) : undefined;
}

async function resolveServerUrl(
	ctx: AuthContext,
	credential: ApiKeyCredential | undefined,
): Promise<string | undefined> {
	const configured = credentialServerUrl(credential) ?? (await ctx.env("LLAMA_BASE_URL"))?.trim();
	return configured ? normalizeLlamaServerUrl(configured) : undefined;
}

function toCortexModel(model: LlamaModelInfo, serverUrl: string): Model<"openai-completions"> {
	// The runtime context window is whatever engine-server was started with
	// (--ctx-size). model.meta.n_ctx IS that number, so trust it — the old
	// hardcoded 262144 floor made the TUI believe it had ~10x the real window,
	// so compaction fired far too late and the engine threw
	// "Context size has been exceeded" mid-conversation (owner 2026-10-24).
	const reportedContextWindow = Number(model.meta?.n_ctx ?? model.meta?.n_ctx_train ?? 65536);
	const contextWindow = reportedContextWindow > 0 ? reportedContextWindow : 65536;
	return {
		id: model.id,
		name: model.id,
		api: "openai-completions",
		provider: LLAMA_PROVIDER_ID,
		baseUrl: llamaInferenceUrl(serverUrl),
		// 2026-09-21: the served model is an abliterated thinking model —
		// it always reasons. Declare it so the TUI shows the thinking selector
		// and streams reasoning_content, and pass chat-template kwargs
		// (enable_thinking / preserve_thinking) per request.
		reasoning: true,
		input: model.architecture?.input_modalities?.includes("image") ? ["text", "image"] : ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow,
		maxTokens: contextWindow,
		compat: {
			supportsStore: false,
			supportsDeveloperRole: false,
			supportsReasoningEffort: false,
			supportsUsageInStreaming: true,
			supportsStrictMode: false,
			maxTokensField: "max_tokens",
			thinkingFormat: "qwen-chat-template",
		},
	};
}

export interface LlamaProviderController {
	provider: Provider<"openai-completions">;
	setCatalog(models: readonly LlamaModelInfo[], serverUrl: string): void;
}

export function createLlamaProvider(): LlamaProviderController {
	let models: readonly Model<"openai-completions">[] = [];

	const setCatalog = (catalog: readonly LlamaModelInfo[], serverUrl: string): void => {
		models = catalog
			.filter((model) => model.status.value === "loaded")
			.map((model) => toCortexModel(model, serverUrl));
	};

	const provider: Provider<"openai-completions"> = {
		id: LLAMA_PROVIDER_ID,
		name: "the engine",
		baseUrl: llamaInferenceUrl(DEFAULT_ENGINE_BIN_URL),
		auth: {
			apiKey: {
				name: "the engine server",
				login: async (interaction): Promise<ApiKeyCredential> => {
					const enteredUrl = await interaction.prompt({
						type: "text",
						message: "the engine server URL",
						placeholder: process.env.LLAMA_BASE_URL ?? DEFAULT_ENGINE_BIN_URL,
					});
					const serverUrl = normalizeLlamaServerUrl(
						enteredUrl.trim() || process.env.LLAMA_BASE_URL || DEFAULT_ENGINE_BIN_URL,
					);
					const apiKey = (
						await interaction.prompt({
							type: "secret",
							message: "API key (optional)",
						})
					).trim();
					await new LlamaClient(serverUrl, apiKey || undefined).list({ signal: interaction.signal });
					return {
						type: "api_key",
						key: apiKey || undefined,
						env: { LLAMA_BASE_URL: serverUrl },
					};
				},
				check: async ({ ctx, credential }) => {
					const serverUrl = await resolveServerUrl(ctx, credential);
					return serverUrl
						? { type: "api_key", source: credential ? "stored credential" : "LLAMA_BASE_URL" }
						: undefined;
				},
				resolve: async ({ ctx, credential }): Promise<AuthResult | undefined> => {
					const serverUrl = await resolveServerUrl(ctx, credential);
					if (!serverUrl) return undefined;
					const apiKey = credential?.key ?? (await ctx.env("LLAMA_API_KEY")) ?? "local";
					return {
						auth: { apiKey, baseUrl: llamaInferenceUrl(serverUrl) },
						env: { ...credential?.env, LLAMA_BASE_URL: serverUrl },
						source: credential ? "stored credential" : "LLAMA_BASE_URL",
					};
				},
			},
		},
		getModels: () => models,
		refreshModels: async (context: RefreshModelsContext): Promise<void> => {
			if (context.stored) {
				const restored = context.stored.models.filter(
					(model): model is Model<"openai-completions"> =>
						model.provider === LLAMA_PROVIDER_ID && model.api === "openai-completions",
				);
				if (
					!(await context.publish({
						update: () => {
							models = restored;
						},
					}))
				) {
					return;
				}
			}

			if (!context.allowNetwork || context.signal.aborted || context.credential?.type !== "api_key") return;
			const serverUrl = credentialServerUrl(context.credential);
			if (!serverUrl) return;
			const catalog = await new LlamaClient(serverUrl, context.credential.key).list({ signal: context.signal });
			if (context.signal.aborted) return;
			const refreshed = catalog
				.filter((model) => model.status.value === "loaded")
				.map((model) => toCortexModel(model, serverUrl));
			await context.publish({
				persist: { models: refreshed, checkedAt: Date.now() },
				update: () => {
					models = refreshed;
				},
			});
		},
		stream: (model, context, options) => stream(model, context, options as ProviderStreamOptions | undefined),
		streamSimple: (model, context, options) => streamSimple(model, context, options),
	};

	return { provider, setCatalog };
}
