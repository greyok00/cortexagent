import { isAbsolute, relative, resolve, sep } from "node:path";
import { truncateToWidth } from "@cortexagent/tui";
import { areExperimentalFeaturesEnabled } from "../../../core/experimental.js";
import { theme } from "../theme/theme.js";
// Import beautification utilities
import { BLOCK_CHARS, createStatusBadge, } from "./beautification.js";
import { compressionCapsule } from "./status-panels.js";
// ═══════════════════════════════════════════════════════════════════════════════
// TABLE-BASED FOOTER DESIGN
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * Create a prettier table row for the footer
 */
function createTableRow(label, value, options) {
    const { labelColor = "dim", valueColor = "text", prefix = "" } = options || {};
    const labelPart = theme.fg(labelColor, `${label}:`);
    const valuePart = theme.fg(valueColor, value);
    return `${prefix ? prefix + " " : ""}${labelPart.padEnd(12)} ${valuePart}`;
}
/**
 * Create a section header for the footer
 */
function createSectionHeader(title) {
    const dash = "─";
    const padLen = Math.max(0, 40 - title.length - 4);
    const padded = "─" + dash.repeat(padLen) + "─";
    return theme.bold(theme.fg("accent", `╭─ ${title} ─${padded}─╮`));
}
/**
 * Create a section divider
 */
function createSectionDivider() {
    return theme.fg("dim", "│" + "─".repeat(78) + "│");
}
/**
 * Create a section footer
 */
function createSectionFooter() {
    return theme.bold(theme.fg("accent", "╰" + "─".repeat(80) + "╯"));
}
/**
 * Create a compact table row with proper spacing
 */
function createCompactRow(label, value) {
    return theme.fg("dim", `${label.padEnd(16)}`) + theme.fg("text", value);
}
function sanitizeStatusText(text) {
    return text
        .replace(/[\r\n\t]/g, " ")
        .replace(/ +/g, " ")
        .trim();
}
export function formatTokens(count) {
    if (count < 1000)
        return count.toString();
    if (count < 10000)
        return `${(count / 1000).toFixed(1)}k`;
    if (count < 1000000)
        return `${Math.round(count / 1000)}k`;
    if (count < 10000000)
        return `${(count / 1000000).toFixed(1)}M`;
    return `${Math.round(count / 1000000)}M`;
}
/**
 * Format tokens with a tiny Unicode block chart
 */
export function formatTokensWithChart(count, maxCount) {
    const base = formatTokens(count);
    if (maxCount === 0)
        return base;
    const percent = Math.min(100, (count / maxCount) * 100);
    const blocks = Math.round((percent / 100) * 4);
    return `${base} ${BLOCK_CHARS.FULL.repeat(Math.max(1, blocks))}${BLOCK_CHARS.LIGHT.repeat(Math.max(0, 4 - blocks))}`;
}
export function formatCwdForFooter(cwd, home) {
    if (!home)
        return cwd;
    const resolvedCwd = resolve(cwd);
    const resolvedHome = resolve(home);
    const relativeToHome = relative(resolvedHome, resolvedCwd);
    const isInsideHome = relativeToHome === "" ||
        (relativeToHome !== ".." && !relativeToHome.startsWith(`..${sep}`) && !isAbsolute(relativeToHome));
    if (!isInsideHome)
        return cwd;
    return relativeToHome === "" ? "~" : `~${sep}${relativeToHome}`;
}
// ═══════════════════════════════════════════════════════════════════════════════
// PIPELINE STATUS INDICATORS
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * Pipeline stages as defined in OBSERVABILITY_IMPLEMENTATION.md and OBSERVATION_COMPLETE.md
 * Flow: User Input → Memory → Intent → Routing → Framing → Model → Beautify → Output → UI
 */
const PIPELINE_STAGES = [
    { id: "memory", label: "📝", name: "memory", tooltip: "Memory append" },
    { id: "intent", label: "🎯", name: "intent", tooltip: "Intent classification" },
    { id: "routing", label: "🔀", name: "routing", tooltip: "Routing decision" },
    { id: "framing", label: "📐", name: "framing", tooltip: "Prompt framing" },
    { id: "model", label: "🤖", name: "model", tooltip: "Model inference" },
    { id: "beautify", label: "🎨", name: "beautify", tooltip: "Output beautification" },
    { id: "output", label: "📤", name: "output", tooltip: "Output formatting" },
];
/**
 * Pipeline status colors
 */
const PIPELINE_COLORS = {
    pending: "muted",
    active: "accent",
    complete: "success",
    error: "error",
    skipped: "dim",
};
/**
 * Create pipeline status indicator
 */
function createPipelineIndicator(stage, status) {
    const color = PIPELINE_COLORS[status] || "muted";
    const icon = PIPELINE_STAGES.find((s) => s.id === stage)?.label || "•";
    return theme.fg(color, `${icon} `) + status;
}
/**
 * Get pipeline status from session state
 */
function getPipelineStatus(session) {
    const state = session.state;
    const status = {};
    // Default: all pending
    PIPELINE_STAGES.forEach((s) => {
        status[s.id] = "pending";
    });
    // If streaming, model is active
    if (state.isStreaming) {
        status["model"] = "active";
        status["framing"] = "complete";
        status["routing"] = "complete";
        status["intent"] = "complete";
        status["memory"] = "complete";
    }
    // If streaming message exists, beautify/output may be active
    if (state.streamingMessage) {
        status["model"] = "complete";
        status["beautify"] = "active";
        status["output"] = "active";
    }
    // If error, mark as error
    if (state.errorMessage) {
        status["model"] = "error";
    }
    // If no pending tool calls, model is complete
    if (!state.isStreaming && !state.streamingMessage && !state.errorMessage) {
        status["model"] = "complete";
        status["beautify"] = "complete";
        status["output"] = "complete";
    }
    return status;
}
/**
 * Render pipeline status bar
 */
function renderPipelineBar(status, width) {
    // Filter to fit width
    const maxStages = Math.floor(width / 12);
    const stages = PIPELINE_STAGES.slice(0, maxStages);
    const parts = stages.map((s) => createPipelineIndicator(s.id, status[s.id] || "pending"));
    // Join with arrows
    let result = parts.join(" ");
    // Add ellipsis if truncated
    if (stages.length < PIPELINE_STAGES.length) {
        result += ` ${theme.fg("dim", "…")} (${PIPELINE_STAGES.length - stages.length} more)`;
    }
    return result;
}
/**
 * Create settings/toggles section
 */
function renderSettingsToggles(session, footerData, width) {
    const state = session.state;
    const toggles = [];
    // Thinking level toggle
    const thinkingLevel = state.thinkingLevel || "off";
    const thinkingBadge = createStatusBadge(thinkingLevel, "accent", { filled: true });
    toggles.push(`🧠 ${thinkingBadge}`);
    // Model provider toggle
    if (footerData.getAvailableProviderCount() > 1 && state.model) {
        const providerBadge = createStatusBadge(state.model.provider, "accent", { filled: true });
        toggles.push(`🏢 ${providerBadge}`);
    }
    // Auto-compaction toggle
    const autoIndicator = "auto";
    const autoBadge = createStatusBadge(autoIndicator, "warning", { filled: true });
    toggles.push(`🔄 ${autoBadge}`);
    // Experimental features toggle
    if (areExperimentalFeaturesEnabled()) {
        const xpBadge = createStatusBadge("xp", "warning", { filled: true });
        toggles.push(`🧪 ${xpBadge}`);
    }
    // Code block toggle (hidden by default)
    const codeToggle = createStatusBadge("👁", "muted", { filled: true });
    toggles.push(codeToggle);
    return toggles.join(" ");
}
// ═══════════════════════════════════════════════════════════════════════════════
// FOOTER COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════
export class FooterComponent {
    autoCompactEnabled = true;
    session;
    footerData;
    constructor(session, footerData) {
        this.session = session;
        this.footerData = footerData;
    }
    setSession(session) {
        this.session = session;
    }
    setAutoCompactEnabled(enabled) {
        this.autoCompactEnabled = enabled;
    }
    invalidate() {
        // No-op: git branch is cached/invalidated by provider
    }
    dispose() {
        // Git watcher cleanup handled by provider
    }
    render(width) {
        const state = this.session.state;
        const contextUsage = this.session.getContextUsage();
        const contextWindow = contextUsage?.contextWindow ?? state.model?.contextWindow ?? 0;
        const contextPercentValue = contextUsage?.percent ?? 0;
        const contextPercent = contextUsage?.percent !== null ? contextPercentValue.toFixed(1) : "?";
        // Session name removed — redundant with the settings/telemetry capsules.
        let pwd = formatCwdForFooter(this.session.sessionManager.getCwd(), process.env.HOME || process.env.USERPROFILE);
        const branch = this.footerData.getGitBranch();
        if (branch) {
            pwd = `${pwd} (${branch})`;
        }
        // ═══════════════════════════════════════════════════════════════════════════
        // COMPACT 2-LINE FOOTER
        // Line 1: cwd (+ git branch). Line 2: context bar + compression % + auto-compress.
        // ═══════════════════════════════════════════════════════════════════════════
        const lines = [];
        // Line 1: Path (session name removed — redundant with settings/telemetry)
        const pwdLine = truncateToWidth(theme.fg("dim", pwd), width, theme.fg("dim", "..."));
        lines.push(pwdLine);
        // Line 2: Context bar + compression % + auto-compress toggle.
        const parts = [];
        // Context window bar.
        const ctxPct = Math.max(0, Math.min(100, contextPercentValue));
        const barWidth = 12;
        const filled = Math.round((ctxPct / 100) * barWidth);
        const ctxBar = theme.fg("accent", "█".repeat(filled)) + theme.fg("dim", "░".repeat(Math.max(0, barWidth - filled)));
        parts.push(`${theme.fg("dim", "ctx")} ${ctxBar} ${theme.fg("text", contextPercent)}%`);
        // Compression % — the same reader the panel uses, so the two can never
        // disagree. It is only a percentage while traffic is being compressed;
        // otherwise "off", because a frozen figure is not a status.
        const comp = compressionCapsule();
        if (comp) {
            parts.push(comp.live ? `${theme.fg("success", "⚡")} ${comp.text}` : `${theme.fg("muted", "⚡ off")}`);
        }
        // Auto-compress toggle.
        parts.push(this.autoCompactEnabled ? theme.fg("accent", "🔄 auto") : theme.fg("muted", "⏸ manual"));
        lines.push(parts.join("  "));
        return lines;
    }
}
//# sourceMappingURL=footer.js.map