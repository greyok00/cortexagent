/**
 * Beautification utilities for the Pi.dev Cortex TUI
 *
 * Incorporates ideas from:
 * - Termaid (ASCII diagrams from Mermaid)
 * - Textcharts (terminal charts)
 * - Ripl charts
 * - Unicode Block Elements (U+2580-U+259F)
 * - SymbolFYI terminal/CLI symbols
 * - Chafa (ASCII art)
 * - Unicode precision patterns
 */
import { theme } from "../theme/theme.js";
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UNICODE BLOCK ELEMENTS & PRECISE PROGRESS BARS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/**
 * Unicode block elements (U+2580-U+259F) for sub-character precision
 * Full blocks for progress visualization
 */
export const BLOCK_CHARS = {
    FULL: "█", // █ U+2580 Full Block
    DARK: "▓", // ▓ U+2593 Dark Shade
    MEDIUM: "▒", // ▒ U+2592 Medium Shade
    LIGHT: "░", // ░ U+2591 Light Shade
    THREE_QUARTERS: "▄", // ▄ U+2584 Lower One Eighth Block
    THREE_QUARTERS_INV: "▀", // ▀ U+2580 Upper One Eighth Block
    HALF: "▌", // ▌ U+258C Left One Eighth Block
    HALF_INV: "▐", // ▐ U+2590 Right One Eighth Block
    QUARTER: "▖", // ▖ U+2596 Quadrant Lower Left
    QUARTER2: "▗", // ▗ U+2597 Quadrant Lower Right
    QUARTER3: "▘", // ▘ U+2598 Quadrant Upper Left
    QUARTER4: "▙", // ▙ U+2599 Quadrant Upper Right
};
/**
 * Terminal progress bar with Unicode block precision
 * Renders precise percentage with sub-character accuracy
 */
export function createProgressBar(percent, width, options) {
    const { filledChar = BLOCK_CHARS.FULL, emptyChar = BLOCK_CHARS.LIGHT, showPercent = true, color = "accent", } = options || {};
    const filledWidth = Math.round((percent / 100) * width);
    const emptyWidth = width - filledWidth;
    let bar = theme.fg(color, filledChar.repeat(Math.max(0, filledWidth)));
    bar += theme.fg("dim", emptyChar.repeat(Math.max(0, emptyWidth)));
    return showPercent ? `${bar} ${Math.round(percent)}%` : bar;
}
/**
 * Multi-segment progress bar for resource utilization
 */
export function createMultiSegmentBar(segments, width) {
    const totalPercent = segments.reduce((sum, seg) => sum + seg.percent, 0);
    const normalized = segments.map((seg) => ({
        ...seg,
        percent: totalPercent > 0 ? (seg.percent / totalPercent) * 100 : 0,
    }));
    let result = "";
    let usedWidth = 0;
    for (const segment of normalized) {
        const segWidth = Math.round((segment.percent / 100) * width);
        const actualWidth = usedWidth < width ? Math.max(1, segWidth) : 0;
        result += theme.fg(segment.color, BLOCK_CHARS.FULL.repeat(actualWidth));
        usedWidth += actualWidth;
        if (usedWidth >= width)
            break;
    }
    const remaining = Math.max(0, width - usedWidth);
    result += theme.fg("dim", BLOCK_CHARS.LIGHT.repeat(remaining));
    return result;
}
/**
 * Terminal chart using Unicode block elements (inspired by chafa/termaid)
 * Renders bar chart with labels
 */
export function createTerminalChart(data, options) {
    const { width = 50, maxHeight = 8, showLabels = true, maxValue = Math.max(...data.map((d) => d.value), 1), labelWidth = 15, } = options || {};
    const chartWidth = Math.min(width, Math.max(10, width - labelWidth - 2));
    const lines = [];
    // Header
    if (showLabels) {
        lines.push(theme.bold(theme.fg("accent", "┌" + "─".repeat(chartWidth + 2) + "┐")));
    }
    // Chart body
    for (let row = maxHeight - 1; row >= 0; row--) {
        let line = showLabels ? "│" : " ";
        const threshold = ((row + 1) / maxHeight) * maxValue;
        for (const item of data) {
            const barWidth = Math.max(1, Math.round((item.value / maxValue) * (chartWidth / data.length)));
            const color = item.color || "accent";
            if (item.value >= threshold) {
                line += theme.fg("text", BLOCK_CHARS.FULL.repeat(barWidth));
            }
            else {
                line += theme.fg("dim", BLOCK_CHARS.LIGHT.repeat(barWidth));
            }
        }
        line += showLabels ? " │" : " ";
        lines.push(line);
    }
    // Bottom border
    if (showLabels) {
        lines.push(theme.bold(theme.fg("accent", "└" + "─".repeat(chartWidth + 2) + "┘")));
    }
    // Labels
    if (showLabels) {
        const labelLine = showLabels ? " " : "";
        const labels = data.map((d) => d.label.length > labelWidth ? d.label.substring(0, labelWidth - 1) + "…" : d.label);
        const joined = labels.join(" ".repeat(Math.max(0, Math.floor(chartWidth / data.length) - labelWidth)));
        lines.push(labelLine + joined);
    }
    return lines;
}
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ASCII ART & DECORATIVE BORDERS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/**
 * Decorative box characters
 */
export const BOX_CHARS = {
    TOP_LEFT: "╭",
    TOP_RIGHT: "╮",
    BOTTOM_LEFT: "╰",
    BOTTOM_RIGHT: "╯",
    HORIZONTAL: "─",
    VERTICAL: "│",
    CROSS: "┼",
    LEFT_T: "├",
    RIGHT_T: "┤",
    TOP_T: "┬",
    BOTTOM_T: "┴",
    // Double borders
    DOUBLE_TOP_LEFT: "┌",
    DOUBLE_TOP_RIGHT: "┐",
    DOUBLE_BOTTOM_LEFT: "└",
    DOUBLE_BOTTOM_RIGHT: "┘",
    DOUBLE_HORIZONTAL: "─",
    DOUBLE_VERTICAL: "│",
    DOUBLE_CROSS: "┼",
};
/**
 * Create a bordered box with content
 */
export function createBox(content, options) {
    const { width = 60, style = "single", borderColor = "accent" } = options || {};
    const lines = typeof content === "string" ? content.split("\n") : content;
    const maxContentWidth = Math.max(...lines.map((l) => l.length), 0);
    const boxWidth = Math.max(width, maxContentWidth + 4);
    // Border styles
    const borders = {
        single: {
            topLeft: BOX_CHARS.TOP_LEFT,
            topRight: BOX_CHARS.TOP_RIGHT,
            bottomLeft: BOX_CHARS.BOTTOM_LEFT,
            bottomRight: BOX_CHARS.BOTTOM_RIGHT,
            horizontal: BOX_CHARS.HORIZONTAL,
            vertical: BOX_CHARS.VERTICAL,
        },
        double: {
            topLeft: BOX_CHARS.DOUBLE_TOP_LEFT,
            topRight: BOX_CHARS.DOUBLE_TOP_RIGHT,
            bottomLeft: BOX_CHARS.DOUBLE_BOTTOM_LEFT,
            bottomRight: BOX_CHARS.DOUBLE_BOTTOM_RIGHT,
            horizontal: BOX_CHARS.DOUBLE_HORIZONTAL,
            vertical: BOX_CHARS.DOUBLE_VERTICAL,
        },
        rounded: {
            topLeft: "╭",
            topRight: "╮",
            bottomLeft: "╭",
            bottomRight: "╮",
            horizontal: "─",
            vertical: "│",
        },
        minimal: {
            topLeft: "",
            topRight: "",
            bottomLeft: "",
            bottomRight: "",
            horizontal: " ",
            vertical: "│",
        },
    }[style];
    const result = [];
    // Title row
    if (options?.title) {
        const titlePadding = Math.max(2, boxWidth - options.title.length - 4);
        const titleLine = `${borders.topLeft}${borders.horizontal.repeat(Math.floor(titlePadding / 2))} ${options.title} ${borders.horizontal.repeat(Math.max(0, titlePadding - Math.floor(titlePadding / 2) - 2))}${borders.topRight}`;
        result.push(theme.bold(theme.fg(borderColor, titleLine)));
    }
    // Content rows
    for (const line of lines) {
        const paddedLine = line.padEnd(boxWidth - 2);
        result.push(theme.fg(borderColor, borders.vertical) +
            theme.fg("text", paddedLine) +
            theme.fg(borderColor, borders.vertical));
    }
    // Bottom row
    const bottomLine = `${borders.bottomLeft}${borders.horizontal.repeat(boxWidth - 2)}${borders.bottomRight}`;
    result.push(theme.bold(theme.fg(borderColor, bottomLine)));
    return result;
}
/**
 * Decorative ASCII art header/banner
 */
export function createAsciiBanner(title, options) {
    const { style = "block", color = "accent" } = options || {};
    const chars = {
        C: ["▓▓▓▓▓", "▓    ", "▓    ", "▓    ", "▓    ", "▓▓▓▓▓"],
        O: [" ▓▓▓▓ ", "▓    ▓", "▓    ▓", "▓    ▓", "▓    ▓", " ▓▓▓▓ "],
        R: ["▓▓▓▓ ", "▓   ▓", "▓▓▓▓ ", "▓   ▓", "▓   ▓▓", "▓    ▓"],
        T: ["▓▓▓▓▓", "    ▓", "    ▓", "    ▓", "    ▓", "    ▓"],
        E: ["▓▓▓▓▓", "▓    ", "▓▓▓▓ ", "▓    ", "▓    ", "▓▓▓▓▓"],
        X: ["▓   ▓", " ▓ ▓ ", "  ▓  ", "  ▓  ", " ▓ ▓ ", "▓   ▓"],
        S: ["▓▓▓▓▓", "▓    ", "▓▓▓▓ ", "    ▓", "    ▓", "▓▓▓▓▓"],
        A: [" ▓  ", "▓▓▓▓", "▓  ▓", "▓   ▓", "▓   ▓", "▓   ▓"],
    };
    const letterWidth = chars["A"]?.length || 6;
    const letterSpacing = 1;
    const totalWidth = title.length * (letterWidth + letterSpacing) - letterSpacing;
    const result = [];
    for (let i = 0; i < letterWidth; i++) {
        let line = "";
        for (const char of title) {
            const upperChar = char.toUpperCase();
            const letter = chars[upperChar];
            if (letter) {
                line += letter[i] || " ";
                line += letterWidth < totalWidth ? " " : "";
            }
        }
        result.push(line);
    }
    return result.map((line) => theme.bold(theme.fg(color, line)));
}
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// TERMINAL STATUS INDICATORS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/**
 * Animated spinner characters
 */
export const SPINNER_CHARS = {
    dots: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧"],
    lines: ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"],
    arrows: ["◜", "◠", "◝", "◞", "◡", "◟", "◜", "◠"],
    blocks: ["░", "▒", "▓", "█", "▓", "▒", "░", "▒"],
};
/**
 * Create a status indicator with spinner
 */
export function createStatusIndicator(message, spinnerIndex, options) {
    const { spinner = "dots", color = "accent", icon = "▹" } = options || {};
    const spinnerChar = SPINNER_CHARS[spinner][spinnerIndex % SPINNER_CHARS[spinner].length];
    const coloredSpinner = theme.fg(color, spinnerChar);
    return `${coloredSpinner} ${icon} ${message}`;
}
/**
 * Create a compact status line with unicode precision
 */
export function createCompactStatus(label, value, options) {
    const { separator = "·", color = "dim", prefix = "▹" } = options || {};
    const prefixChar = theme.fg("dim", prefix);
    const sep = theme.fg(color, separator);
    return `${prefixChar} ${label} ${sep} ${theme.fg(color, value)}`;
}
/**
 * Create a status badge with pill shape
 */
export function createStatusBadge(text, color, options) {
    const { filled = true, bordered = false, icon } = options || {};
    const innerText = icon ? `${icon} ${text}` : text;
    const width = innerText.length + 2;
    if (filled) {
        const badge = theme.bg("selectedBg", theme.fg(color, innerText));
        return `[${badge}]`;
    }
    if (bordered) {
        const badge = theme.fg(color, innerText);
        return `(${badge})`;
    }
    return innerText;
}
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MERMAID-INSPIRED DIAGRAMS (Termaid integration)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/**
 * Simple ASCII diagram generator inspired by Termaid
 * Renders flow charts and sequence diagrams
 */
export function createSimpleDiagram(type, data) {
    const lines = [];
    if (type === "flow") {
        // Flow chart with nodes and arrows
        const nodes = data.nodes || [];
        for (const node of nodes) {
            const box = createBox(node.label || "Node", {
                width: node.width || 20,
                style: "minimal",
                borderColor: "accent",
            });
            lines.push(...box);
            lines.push("");
        }
    }
    if (type === "sequence") {
        // Sequence diagram
        const participants = data.participants || [];
        const messages = data.messages || [];
        // Header
        const header = participants.map((p) => p.padEnd(20)).join(" ");
        lines.push(header);
        lines.push("".padEnd(header.length, "─"));
        // Messages
        for (const msg of messages) {
            const arrow = msg.direction === "to" ? "────" : "────";
            const line = msg.from < msg.to ? arrow : "──┤";
            lines.push(`${msg.from.padEnd(20)}${line}→ ${msg.text}`);
        }
    }
    return lines;
}
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UTILITY FUNCTIONS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/**
 * Create a visual separator with style
 */
export function createSeparator(style = "line") {
    const separators = {
        line: "─".repeat(50),
        double: "═".repeat(50),
        dots: "·".repeat(50),
        thick: "█".repeat(50),
    };
    return theme.fg("muted", separators[style]);
}
/**
 * Create a visual divider with text
 */
export function createDivider(text, options) {
    const { style = "line", padding = 2 } = options || {};
    const textPart = text ? ` ${text} ` : "";
    const dividerWidth = Math.max(textPart.length + padding * 2, 40);
    const parts = {
        line: "─",
        double: "═",
        dots: "·",
    }[style];
    const leftPadding = " ".repeat(Math.max(0, Math.floor((dividerWidth - textPart.length) / 2) - padding));
    const rightPadding = " ".repeat(Math.max(0, Math.ceil((dividerWidth - textPart.length) / 2) - padding));
    if (text) {
        return `${leftPadding}${parts.repeat(3)}${textPart}${parts.repeat(3)}${rightPadding}`;
    }
    return parts.repeat(dividerWidth);
}
/**
 * Create a compact visual indicator (like git branch indicator)
 */
export function createVisualIndicator(status, message) {
    const icons = {
        success: "✓",
        error: "✗",
        warning: "⚠",
        info: "ℹ",
        loading: "⟳",
    };
    const colors = {
        success: "success",
        error: "error",
        warning: "warning",
        info: "accent",
        loading: "accent",
    };
    const icon = theme.fg(colors[status], icons[status]);
    return message ? `${icon} ${message}` : icon;
}
/**
 * Create a terminal header with decorative border
 */
export function createTerminalHeader(title, options) {
    const { subtitle, color = "accent" } = options || {};
    const lines = [];
    lines.push(theme.bold(theme.fg(color, "╭" + "─".repeat(title.length + 2) + "╮")));
    lines.push(theme.fg(color, "│") + theme.fg("text", ` ${title} `) + theme.fg(color, "│"));
    if (subtitle) {
        lines.push(theme.fg(color, "│") + theme.fg("dim", ` ${subtitle} `) + theme.fg(color, "│"));
    }
    lines.push(theme.bold(theme.fg(color, "╰" + "─".repeat(title.length + 2) + "╯")));
    return lines;
}
//# sourceMappingURL=beautification.js.map