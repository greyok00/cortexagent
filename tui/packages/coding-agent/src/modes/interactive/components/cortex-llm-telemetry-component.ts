import type { Usage } from "@cortexagent/ai";
import type { Component } from "@cortexagent/tui";
import { truncateToWidth, visibleWidth } from "@cortexagent/tui";
import type { AgentSession } from "../../../core/agent-session.ts";
import { theme } from "../theme/theme.ts";

// ── /metrics polling (slimtoken local lane) ──────────────────────────────────
// Hard-baked 2026-09-21 port map: 11436 = slimtoken local lane → ollama
// :11600. The old grammar proxy (:8081) was deleted 2026-09-22.
const METRICS_URL = "http://127.0.0.1:11436/metrics";
const METRICS_TTL = 1000;

interface MetricsPayload {
	current_in_tps?: number;
	current_out_tps?: number;
	current_tok_s?: number;
	avg_in_tps?: number;
	avg_out_tps?: number;
	avg_tok_s?: number;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// CORTEX LLM TELEMETRY CAPSULE
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// Compact 8-cell meter: ███░░░░░
const METER_FULL = "\u2588";
const METER_EMPTY = "\u2591";

export type PrefillState = "idle" | "prefill" | "generating" | "idle_no_speeds";

/**
 * Shared telemetry data consumed by the capsule.
 */
export interface TelemetryData {
	/** Resolved concrete backend model name (e.g. a local the engine model id). */
	resolvedModel?: string;
	/** Route / profile alias that was used (e.g. "cortex-big"). */
	routeAlias?: string;
	/** Provider label for the route. */
	providerLabel?: string;
	/** Runtime/router mode (e.g. "auto", "fast", "balanced"). */
	mode?: string;
	/** Context usage percentage (0–100). */
	contextPercent?: number;
	/** Context window capacity in tokens (e.g. 128000). */
	contextCapacity?: number;
	/** Cached-prompt reuse percentage (0–100). */
	reusePercent?: number;
	/** Cache hit percentage (0–100). */
	cachePercent?: number;
	/** Input (prefill) throughput in tokens/sec. */
	inputSpeed?: number;
	/** Output (decode) throughput in tokens/sec. */
	outputSpeed?: number;
	/** Explicit input token count for the current request. */
	inputTokens?: number;
	/** Explicit output token count for the current request. */
	outputTokens?: number;
	/** Current prefill/generation state. */
	prefillState?: PrefillState;
	/** Prefill token count (number of tokens in prefill phase). */
	prefillTokens?: number;
	/** Whether a real inference request is active. */
	isActive?: boolean;
	/** Last successful response usage snapshot (for fallback). */
	lastUsage?: Usage | null;
	/** Short error if the telemetry itself failed. */
	error?: string;
}

/**
 * Format a token count with compact units (k/M).
 */
function formatTokenCount(tokens: number | undefined): string {
	if (tokens === undefined || tokens === 0) return "0";
	if (tokens < 1000) return tokens.toString();
	if (tokens < 1000000) return `${(tokens / 1000).toFixed(tokens >= 10000 ? 0 : 1)}k`;
	return `${(tokens / 1000000).toFixed(1)}M`;
}

/**
 * Format a speed value with one decimal place.
 */
function formatSpeed(speed: number): string {
	if (speed >= 100) return speed.toFixed(0);
	if (speed >= 10) return speed.toFixed(1);
	return speed.toFixed(1);
}

/**
 * Build a context meter string: ███░░░░░ N%.
 */
function buildContextMeter(percent: number | undefined, width: number): string {
	if (percent === undefined) return "";
	const filled = Math.round((percent / 100) * Math.min(width, 8));
	const empty = Math.max(0, Math.min(width, 8) - filled);
	const meter = METER_FULL.repeat(Math.max(0, filled)) + METER_EMPTY.repeat(Math.max(0, empty));
	// Determine color based on percent
	const color: "accent" | "warning" | "error" | "dim" = percent < 70 ? "dim" : percent < 85 ? "warning" : "error";
	return `${theme.fg(color, meter)} ${Math.round(percent)}%`;
}

/**
 * Build the context meter with capacity: ███░░░░░ N%/128k
 */
function buildContextMeterWithCapacity(
	percent: number | undefined,
	capacity: number | undefined,
	width: number,
): string {
	if (percent === undefined) return "";
	const meter = buildContextMeter(percent, width);
	if (capacity !== undefined && capacity > 0 && width > 20) {
		return `${meter}/${formatTokenCount(capacity)}`;
	}
	return meter;
}

/**
 * The CortexLLM telemetry capsule renders in exactly two terminal rows.
 * It reads from TelemetryData and adapts to terminal width.
 */
export class CortexLLMTelemetryComponent implements Component {
	private session: AgentSession;
	private data: TelemetryData = {};
	private _cached?: { lines: string[]; width: number };
	private _metricsCache?: { at: number; payload: MetricsPayload };

	constructor(session: AgentSession) {
		this.session = session;
	}

	setData(data: TelemetryData): void {
		this.data = data;
		this._cached = undefined;
	}

	invalidate(): void {
		this._cached = undefined;
	}

	/**
	 * Poll the slimtoken local-lane /metrics endpoint and fold speeds
	 * into the telemetry data. Called by the interactive-mode render tick.
	 */
	async refresh(): Promise<void> {
		const now = Date.now();
		if (this._metricsCache && now - this._metricsCache.at < METRICS_TTL) {
			this.applyMetrics(this._metricsCache.payload);
			return;
		}
		try {
			const res = await fetch(METRICS_URL, { signal: AbortSignal.timeout(1500) });
			if (!res.ok) return;
			const payload = (await res.json()) as MetricsPayload;
			this._metricsCache = { at: now, payload };
			this.applyMetrics(payload);
		} catch {
			// proxy unreachable — keep last data, mark stale
			this.data.error = "stale";
		}
	}

	private applyMetrics(p: MetricsPayload): void {
		const next: TelemetryData = {
			...this.data,
			inputSpeed: p.current_in_tps ?? p.avg_in_tps,
			outputSpeed: p.current_out_tps ?? p.avg_out_tps ?? p.current_tok_s ?? p.avg_tok_s,
		};
		this.setData(next);
	}

	/**
	 * Build the first row (model + mode + context meter + cache).
	 */
	private buildHeaderRow(width: number): string {
		const d = this.data;
		const parts: string[] = [];

		// 1. Model name
		const modelName = d.resolvedModel || "model unknown";
		let modelDisplay: string;
		const maxModelWidth = Math.max(4, Math.floor(width / 3));
		const truncatedModel = truncateToWidth(modelName, maxModelWidth, "…");
		modelDisplay = theme.bold(theme.fg("accent", truncatedModel));

		// 2. Route alias (via cortex-big)
		if (d.routeAlias && d.resolvedModel && visibleWidth(modelName) < width * 0.5) {
			modelDisplay += ` · via ${d.routeAlias}`;
		}

		parts.push(modelDisplay);

		// 3. Mode
		if (d.mode && d.resolvedModel) {
			parts.push(`${theme.fg("muted", "·")} ${theme.fg("muted", d.mode)}`);
		}

		// 4. Context meter
		if (d.contextPercent !== undefined && d.contextPercent !== null) {
			const hasCapacity = d.contextCapacity !== undefined && d.contextCapacity > 0 && width > 40;
			const meterStr = hasCapacity
				? buildContextMeterWithCapacity(d.contextPercent, d.contextCapacity, width)
				: buildContextMeter(d.contextPercent, 8);
			parts.push(` · ${theme.fg("dim", "ctx")} ${meterStr}`);
		}

		// 5. Cache
		if (d.cachePercent !== undefined && d.cachePercent > 0 && width > 35) {
			parts.push(` · ${theme.fg("muted", "cache")} ${Math.round(d.cachePercent)}%`);
		}

		// 6. Reuse
		if (d.reusePercent !== undefined && d.reusePercent > 0 && width > 35) {
			parts.push(` · ${theme.fg("muted", "reused")} ${Math.round(d.reusePercent)}%`);
		}

		let header = parts.join(" ");
		// Truncate to panel width
		header = truncateToWidth(header, width - 1, "…");
		return header;
	}

	/**
	 * Build the second row (IN/OUT speeds + input/output tokens).
	 */
	private buildDetailRow(width: number): string {
		const d = this.data;
		const parts: string[] = [];

		const isPrefill = d.prefillState === "prefill";
		const isActive = d.isActive !== false;
		const hasSpeeds =
			(d.inputSpeed !== undefined && d.inputSpeed > 0) || (d.outputSpeed !== undefined && d.outputSpeed > 0);

		// Prefill state indicator
		if (isPrefill) {
			parts.push(
				`${theme.fg("warning", "◌")} ${theme.fg("warning", "PREFILL")} ${d.prefillTokens !== undefined && d.prefillTokens > 0 ? `${formatTokenCount(d.prefillTokens)} ` : ""}${theme.fg("dim", "IN")} ${formatSpeed(d.inputSpeed ?? 0)}/s`,
			);
		} else if (
			(d.inputSpeed !== undefined && d.inputSpeed > 0) ||
			(d.outputSpeed !== undefined && d.outputSpeed > 0)
		) {
			// Normal speeds
			const inSpeed =
				d.inputSpeed !== undefined && d.inputSpeed > 0
					? `${theme.fg("dim", "IN")} ${formatSpeed(d.inputSpeed)}/s`
					: `${theme.fg("dim", "IN")} —/s`;
			const outSpeed =
				d.outputSpeed !== undefined && d.outputSpeed > 0
					? `${theme.fg("dim", "OUT")} ${formatSpeed(d.outputSpeed)}/s`
					: `${theme.fg("dim", "OUT")} —/s`;
			parts.push(`${inSpeed} · ${outSpeed}`);
		} else {
			// No active inference speeds
			parts.push(`${theme.fg("dim", "IN")} —/s · ${theme.fg("dim", "OUT")} —/s`);
		}

		// Input/output totals
		if (d.inputTokens !== undefined && d.inputTokens > 0) {
			parts.push(` · ${theme.fg("muted", "input")} ${formatTokenCount(d.inputTokens)}`);
		}
		if (d.outputTokens !== undefined && d.outputTokens > 0) {
			parts.push(` · ${theme.fg("muted", "output")} ${formatTokenCount(d.outputTokens)}`);
		}

		let detail = parts.join(" ");
		detail = truncateToWidth(detail, width - 1, "…");
		return detail;
	}

	render(_width: number): string[] {
		const d = this.data;
		const state = this.session.state;

		// Gather live data from session
		const ctxUsage = this.session.getContextUsage();
		const model = state.model;

		const resolvedModel = d.resolvedModel || model?.id || "model unknown";
		const contextPercent = ctxUsage?.percent ?? undefined;
		const contextCapacity = model?.contextWindow;

		// Check for active inference data
		let hasActiveInference = false;
		let inputSpeed: number | undefined;
		let outputSpeed: number | undefined;
		let inputTokens: number | undefined;
		let outputTokens: number | undefined;
		let prefillState: PrefillState = "idle";
		let prefillTokens: number | undefined;

		// streamingMessage is an AgentMessage union — narrow to assistant messages
		const streaming = state.streamingMessage;
		if (streaming && streaming.role === "assistant") {
			hasActiveInference = true;
			const usage = streaming.usage;
			if (usage) {
				inputTokens = usage.input || undefined;
				outputTokens = usage.output || undefined;
			}
			// Determine prefill state from stopReason or content
			if (streaming.stopReason === "toolUse" || streaming.content?.some((c) => c.type === "toolCall")) {
				prefillState = "idle";
			} else if (state.isStreaming) {
				// Check if we're still in prefill (no output tokens yet)
				if (outputTokens === undefined || outputTokens === 0) {
					prefillState = "prefill";
					prefillTokens = inputTokens;
				} else {
					prefillState = "generating";
				}
			}
		}

		const data: TelemetryData = {
			resolvedModel,
			routeAlias: d.routeAlias,
			mode: d.mode,
			contextPercent,
			contextCapacity,
			reusePercent: d.reusePercent,
			cachePercent: d.cachePercent,
			inputSpeed: d.inputSpeed,
			outputSpeed: d.outputSpeed,
			inputTokens,
			outputTokens,
			prefillState,
			prefillTokens,
			isActive: hasActiveInference,
			lastUsage: d.lastUsage,
		};

		// Update data if changed
		if (
			this.data.resolvedModel !== data.resolvedModel ||
			this.data.contextPercent !== data.contextPercent ||
			this.data.isActive !== data.isActive
		) {
			this.setData(data);
		}

		const header = this.buildHeaderRow(_width);
		const detail = this.buildDetailRow(_width);

		this._cached = {
			lines: [`  ◈ CORTEX │ ${header}`, `           ↳ ${detail}`],
			width: _width,
		};

		return [`  ◈ CORTEX │ ${header}`, `           ↳ ${detail}`];
	}
}
