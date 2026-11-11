import { Box, type MarkdownTheme } from "@cortexagent/tui";
import type { BranchSummaryMessage } from "../../../core/messages.ts";
export declare class BranchSummaryMessageComponent extends Box {
    private expanded;
    private message;
    private markdownTheme;
    constructor(message: BranchSummaryMessage, markdownTheme?: MarkdownTheme);
    setExpanded(expanded: boolean): void;
    invalidate(): void;
    private updateDisplay;
}
//# sourceMappingURL=branch-summary-message.d.ts.map