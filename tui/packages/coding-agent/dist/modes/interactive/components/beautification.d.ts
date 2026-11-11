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
import type { ThemeColor } from "../theme/theme.ts";
/**
 * Unicode block elements (U+2580-U+259F) for sub-character precision
 * Full blocks for progress visualization
 */
export declare const BLOCK_CHARS: {
    FULL: string;
    DARK: string;
    MEDIUM: string;
    LIGHT: string;
    THREE_QUARTERS: string;
    THREE_QUARTERS_INV: string;
    HALF: string;
    HALF_INV: string;
    QUARTER: string;
    QUARTER2: string;
    QUARTER3: string;
    QUARTER4: string;
};
/**
 * Terminal progress bar with Unicode block precision
 * Renders precise percentage with sub-character accuracy
 */
export declare function createProgressBar(percent: number, width: number, options?: {
    filledChar?: string;
    emptyChar?: string;
    showPercent?: boolean;
    color?: ThemeColor;
}): string;
/**
 * Multi-segment progress bar for resource utilization
 */
export declare function createMultiSegmentBar(segments: {
    label: string;
    percent: number;
    color: ThemeColor;
}[], width: number): string;
/**
 * Terminal chart using Unicode block elements (inspired by chafa/termaid)
 * Renders bar chart with labels
 */
export declare function createTerminalChart(data: {
    label: string;
    value: number;
    color?: ThemeColor;
}[], options?: {
    width?: number;
    maxHeight?: number;
    showLabels?: boolean;
    maxValue?: number;
    labelWidth?: number;
}): string[];
/**
 * Decorative box characters
 */
export declare const BOX_CHARS: {
    TOP_LEFT: string;
    TOP_RIGHT: string;
    BOTTOM_LEFT: string;
    BOTTOM_RIGHT: string;
    HORIZONTAL: string;
    VERTICAL: string;
    CROSS: string;
    LEFT_T: string;
    RIGHT_T: string;
    TOP_T: string;
    BOTTOM_T: string;
    DOUBLE_TOP_LEFT: string;
    DOUBLE_TOP_RIGHT: string;
    DOUBLE_BOTTOM_LEFT: string;
    DOUBLE_BOTTOM_RIGHT: string;
    DOUBLE_HORIZONTAL: string;
    DOUBLE_VERTICAL: string;
    DOUBLE_CROSS: string;
};
/**
 * Create a bordered box with content
 */
export declare function createBox(content: string | string[], options?: {
    title?: string;
    width?: number;
    style?: "single" | "double" | "rounded" | "minimal";
    borderColor?: ThemeColor;
}): string[];
/**
 * Decorative ASCII art header/banner
 */
export declare function createAsciiBanner(title: string, options?: {
    style?: "block" | "thin" | "outline";
    color?: ThemeColor;
}): string[];
/**
 * Animated spinner characters
 */
export declare const SPINNER_CHARS: {
    dots: string[];
    lines: string[];
    arrows: string[];
    blocks: string[];
};
/**
 * Create a status indicator with spinner
 */
export declare function createStatusIndicator(message: string, spinnerIndex: number, options?: {
    spinner?: keyof typeof SPINNER_CHARS;
    color?: ThemeColor;
    icon?: string;
}): string;
/**
 * Create a compact status line with unicode precision
 */
export declare function createCompactStatus(label: string, value: string, options?: {
    separator?: string;
    color?: ThemeColor;
    prefix?: string;
}): string;
/**
 * Create a status badge with pill shape
 */
export declare function createStatusBadge(text: string, color: ThemeColor, options?: {
    filled?: boolean;
    bordered?: boolean;
    icon?: string;
}): string;
/**
 * Simple ASCII diagram generator inspired by Termaid
 * Renders flow charts and sequence diagrams
 */
export declare function createSimpleDiagram(type: "flow" | "sequence", data: any): string[];
/**
 * Create a visual separator with style
 */
export declare function createSeparator(style?: "line" | "double" | "dots" | "thick"): string;
/**
 * Create a visual divider with text
 */
export declare function createDivider(text?: string, options?: {
    style?: "line" | "double" | "dots";
    padding?: number;
}): string;
/**
 * Create a compact visual indicator (like git branch indicator)
 */
export declare function createVisualIndicator(status: "success" | "error" | "warning" | "info" | "loading", message?: string): string;
/**
 * Create a terminal header with decorative border
 */
export declare function createTerminalHeader(title: string, options?: {
    subtitle?: string;
    color?: ThemeColor;
}): string[];
//# sourceMappingURL=beautification.d.ts.map