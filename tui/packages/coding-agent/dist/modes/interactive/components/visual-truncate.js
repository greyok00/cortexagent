import { Text } from "@cortexagent/tui";
export function truncateToVisualLines(text, maxVisualLines, width, paddingX = 0) {
    if (!text) {
        return { visualLines: [], skippedCount: 0 };
    }
    const tempText = new Text(text, paddingX, 0);
    const allVisualLines = tempText.render(width);
    if (allVisualLines.length <= maxVisualLines) {
        return { visualLines: allVisualLines, skippedCount: 0 };
    }
    const truncatedLines = allVisualLines.slice(-maxVisualLines);
    const skippedCount = allVisualLines.length - maxVisualLines;
    return { visualLines: truncatedLines, skippedCount };
}
//# sourceMappingURL=visual-truncate.js.map