import type { Usage } from "@cortexagent/ai";
import type { Component } from "@cortexagent/tui";
import type { AgentSession } from "../../../core/agent-session.ts";
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
 * The CortexLLM telemetry capsule renders in exactly two terminal rows.
 * It reads from TelemetryData and adapts to terminal width.
 */
export declare class CortexLLMTelemetryComponent implements Component {
    private session;
    private data;
    private _cached?;
    private _metricsCache?;
    constructor(session: AgentSession);
    setData(data: TelemetryData): void;
    invalidate(): void;
    /**
     * Poll the slimtoken local-lane /metrics endpoint and fold speeds
     * into the telemetry data. Called by the interactive-mode render tick.
     */
    refresh(): Promise<void>;
    private applyMetrics;
    /**
     * Build the first row (model + mode + context meter + cache).
     */
    private buildHeaderRow;
    /**
     * Build the second row (IN/OUT speeds + input/output tokens).
     */
    private buildDetailRow;
    render(_width: number): string[];
}
//# sourceMappingURL=cortex-llm-telemetry-component.d.ts.map