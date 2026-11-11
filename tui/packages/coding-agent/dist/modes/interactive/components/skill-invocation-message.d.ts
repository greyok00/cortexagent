import { Box, type MarkdownTheme } from "@cortexagent/tui";
import type { ParsedSkillBlock } from "../../../core/agent-session.ts";
export declare class SkillInvocationMessageComponent extends Box {
    private expanded;
    private skillBlock;
    private markdownTheme;
    constructor(skillBlock: ParsedSkillBlock, markdownTheme?: MarkdownTheme);
    setExpanded(expanded: boolean): void;
    invalidate(): void;
    private updateDisplay;
}
//# sourceMappingURL=skill-invocation-message.d.ts.map