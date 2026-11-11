import { truncateToWidth, visibleWidth } from "@cortexagent/tui";
import { theme } from "../theme/theme.js";
// ── /metrics polling (slimtoken local lane) ──────────────────────────────────
// Hard-baked 2026-09-21 port map: 11436 = slimtoken local lane → ollama
// :11600. The old grammar proxy (:8081) was deleted 2026-09-22.
const METRICS_URL = "http://127.0.0.1:11436/metrics";
const METRICS_TTL = 1000;
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// CORTEX LLM TELEMETRY CAPSULE
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Compact 8-cell meter: ███░░░░░
const METER_FULL = "\u2588";
const METER_EMPTY = "\u2591";
/**
 * Format a token count with compact units (k/M).
 */
function formatTokenCount(tokens) {
    if (tokens === undefined || tokens === 0)
        return "0";
    if (tokens < 1000)
        return tokens.toString();
    if (tokens < 1000000)
        return `${(tokens / 1000).toFixed(tokens >= 10000 ? 0 : 1)}k`;
    return `${(tokens / 1000000).toFixed(1)}M`;
}
/**
 * Format a speed value with one decimal place.
 */
function formatSpeed(speed) {
    if (speed >= 100)
        return speed.toFixed(0);
    if (speed >= 10)
        return speed.toFixed(1);
    return speed.toFixed(1);
}
/**
 * Build a context meter string: ███░░░░░ N%.
 */
function buildContextMeter(percent, width) {
    if (percent === undefined)
        return "";
    const filled = Math.round((percent / 100) * Math.min(width, 8));
    const empty = Math.max(0, Math.min(width, 8) - filled);
    const meter = METER_FULL.repeat(Math.max(0, filled)) + METER_EMPTY.repeat(Math.max(0, empty));
    // Determine color based on percent
    const color = percent < 70 ? "dim" : percent < 85 ? "warning" : "error";
    return `${theme.fg(color, meter)} ${Math.round(percent)}%`;
}
/**
 * Build the context meter with capacity: ███░░░░░ N%/128k
 */
function buildContextMeterWithCapacity(percent, capacity, width) {
    if (percent === undefined)
        return "";
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
export class CortexLLMTelemetryComponent {
    session;
    data = {};
    _cached;
    _metricsCache;
    constructor(session) {
        this.session = session;
    }
    setData(data) {
        this.data = data;
        this._cached = undefined;
    }
    invalidate() {
        this._cached = undefined;
    }
    /**
     * Poll the slimtoken local-lane /metrics endpoint and fold speeds
     * into the telemetry data. Called by the interactive-mode render tick.
     */
    async refresh() {
        const now = Date.now();
        if (this._metricsCache && now - this._metricsCache.at < METRICS_TTL) {
            this.applyMetrics(this._metricsCache.payload);
            return;
        }
        try {
            const res = await fetch(METRICS_URL, { signal: AbortSignal.timeout(1500) });
            if (!res.ok)
                return;
            const payload = (await res.json());
            this._metricsCache = { at: now, payload };
            this.applyMetrics(payload);
        }
        catch {
            // proxy unreachable — keep last data, mark stale
            this.data.error = "stale";
        }
    }
    applyMetrics(p) {
        const next = {
            ...this.data,
            inputSpeed: p.current_in_tps ?? p.avg_in_tps,
            outputSpeed: p.current_out_tps ?? p.avg_out_tps ?? p.current_tok_s ?? p.avg_tok_s,
        };
        this.setData(next);
    }
    /**
     * Build the first row (model + mode + context meter + cache).
     */
    buildHeaderRow(width) {
        const d = this.data;
        const parts = [];
        // 1. Model name
        const modelName = d.resolvedModel || "model unknown";
        let modelDisplay;
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
    buildDetailRow(width) {
        const d = this.data;
        const parts = [];
        const isPrefill = d.prefillState === "prefill";
        const isActive = d.isActive !== false;
        const hasSpeeds = (d.inputSpeed !== undefined && d.inputSpeed > 0) || (d.outputSpeed !== undefined && d.outputSpeed > 0);
        // Prefill state indicator
        if (isPrefill) {
            parts.push(`${theme.fg("warning", "◌")} ${theme.fg("warning", "PREFILL")} ${d.prefillTokens !== undefined && d.prefillTokens > 0 ? `${formatTokenCount(d.prefillTokens)} ` : ""}${theme.fg("dim", "IN")} ${formatSpeed(d.inputSpeed ?? 0)}/s`);
        }
        else if ((d.inputSpeed !== undefined && d.inputSpeed > 0) ||
            (d.outputSpeed !== undefined && d.outputSpeed > 0)) {
            // Normal speeds
            const inSpeed = d.inputSpeed !== undefined && d.inputSpeed > 0
                ? `${theme.fg("dim", "IN")} ${formatSpeed(d.inputSpeed)}/s`
                : `${theme.fg("dim", "IN")} —/s`;
            const outSpeed = d.outputSpeed !== undefined && d.outputSpeed > 0
                ? `${theme.fg("dim", "OUT")} ${formatSpeed(d.outputSpeed)}/s`
                : `${theme.fg("dim", "OUT")} —/s`;
            parts.push(`${inSpeed} · ${outSpeed}`);
        }
        else {
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
    render(_width) {
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
        let inputSpeed;
        let outputSpeed;
        let inputTokens;
        let outputTokens;
        let prefillState = "idle";
        let prefillTokens;
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
            }
            else if (state.isStreaming) {
                // Check if we're still in prefill (no output tokens yet)
                if (outputTokens === undefined || outputTokens === 0) {
                    prefillState = "prefill";
                    prefillTokens = inputTokens;
                }
                else {
                    prefillState = "generating";
                }
            }
        }
        const data = {
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
        if (this.data.resolvedModel !== data.resolvedModel ||
            this.data.contextPercent !== data.contextPercent ||
            this.data.isActive !== data.isActive) {
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
//# sourceMappingURL=cortex-llm-telemetry-component.js.map