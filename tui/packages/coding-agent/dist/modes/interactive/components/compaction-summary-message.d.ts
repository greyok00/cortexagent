import { Box, type MarkdownTheme } from "@cortexagent/tui";
import type { CompactionSummaryMessage } from "../../../core/messages.ts";
export declare class CompactionSummaryMessageComponent extends Box {
    private expanded;
    private message;
    private markdownTheme;
    constructor(message: CompactionSummaryMessage, markdownTheme?: MarkdownTheme);
    setExpanded(expanded: boolean): void;
    invalidate(): void;
    private updateDisplay;
}
//# sourceMappingURL=compaction-summary-message.d.ts.map