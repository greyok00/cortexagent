import type {
	Api,
	Context,
	Model,
	SimpleStreamOptions,
	StreamOptions,
	ThinkingBudgets,
	ThinkingLevel,
} from "../types.ts";
import { estimateContextTokens } from "../utils/estimate.ts";

const CONTEXT_SAFETY_TOKENS = 4096;

// 2026-11-09 (auto-continue storm, 6633eef4-class): the old floor of 1 let this
// clamp return max_tokens=1 once usage crossed (window - 4096), and every
// reply then hit stopReason "length" immediately; the auto-continue nudge added
// ~170-250 tokens per retry and the request re-clamped to 1, 12 times deep
// (lane.log 34767in->1out ... 35781in->1out) until compaction fired. Floor at
// MIN_ANSWER_TOKENS (the same constant openai-completions.ts reserves when
// budgeting thinking): long contexts must compact, not produce 1-token turns.
export function clampMaxTokensToContext(model: Model<Api>, context: Context, maxTokens: number): number {
	if (model.contextWindow <= 0) return Math.max(MIN_ANSWER_TOKENS, maxTokens);

	const safety = Math.min(CONTEXT_SAFETY_TOKENS, Math.floor(model.contextWindow / 2));
	const available = model.contextWindow - estimateContextTokens(context).tokens - safety;
	return Math.min(maxTokens, Math.max(MIN_ANSWER_TOKENS, available));
}

export function buildBaseOptions(
	model: Model<Api>,
	context: Context,
	options?: SimpleStreamOptions,
	apiKey?: string,
): StreamOptions {
	const samplingParams =
		model.samplingParams || options?.samplingParams
			? { ...model.samplingParams, ...options?.samplingParams }
			: undefined;
	return {
		temperature: options?.temperature,
		samplingParams,
		maxTokens: clampMaxTokensToContext(model, context, options?.maxTokens ?? model.maxTokens),
		signal: options?.signal,
		telemetryContext: options?.telemetryContext,
		apiKey: apiKey || options?.apiKey,
		fetch: options?.fetch,
		transport: options?.transport,
		cacheRetention: options?.cacheRetention,
		sessionId: options?.sessionId,
		headers: options?.headers,
		onPayload: options?.onPayload,
		onResponse: options?.onResponse,
		timeoutMs: options?.timeoutMs,
		websocketConnectTimeoutMs: options?.websocketConnectTimeoutMs,
		maxRetries: options?.maxRetries,
		maxRetryDelayMs: options?.maxRetryDelayMs,
		metadata: options?.metadata,
		env: options?.env,
	};
}

export const MIN_ANSWER_TOKENS = 1024;

export function clampReasoning(effort: ThinkingLevel | undefined): Exclude<ThinkingLevel, "xhigh" | "max"> | undefined {
	return effort === "xhigh" || effort === "max" ? "high" : effort;
}

export function adjustMaxTokensForThinking(
	baseMaxTokens: number | undefined,
	modelMaxTokens: number,
	reasoningLevel: ThinkingLevel,
	customBudgets?: ThinkingBudgets,
): { maxTokens: number; thinkingBudget: number } {
	// 2026-11-09 owner ("as reasoning as possible"): high doubles with the
	// model.maxTokens bump (16384 -> 32768) so deep task chains keep a
	// thinking budget that fits the new ceiling.
	const defaultBudgets: ThinkingBudgets = {
		minimal: 1024,
		low: 2048,
		medium: 16384,
		high: 32768,
	};
	const budgets = { ...defaultBudgets, ...customBudgets };

	const level = clampReasoning(reasoningLevel)!;
	let thinkingBudget = budgets[level]!;
	const maxTokens =
		baseMaxTokens === undefined ? modelMaxTokens : Math.min(baseMaxTokens + thinkingBudget, modelMaxTokens);

	if (maxTokens <= thinkingBudget) {
		thinkingBudget = Math.max(0, maxTokens - MIN_ANSWER_TOKENS);
	}

	return { maxTokens, thinkingBudget };
}
