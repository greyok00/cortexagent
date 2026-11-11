import type { AssistantMessage } from "@cortexagent/ai";
import { Container, type MarkdownTheme } from "@cortexagent/tui";
import type { MarkdownTransformer } from "../../../core/extensions/types.ts";
export declare class AssistantMessageComponent extends Container {
    private contentContainer;
    private hideThinkingBlock;
    private collapseCodeBlocksEnabled;
    private markdownTheme;
    private hiddenThinkingLabel;
    private outputPad;
    private markdownTransformers;
    private lastMessage?;
    private hasToolCalls;
    private isStreaming;
    constructor(message?: AssistantMessage, hideThinkingBlock?: boolean, markdownTheme?: MarkdownTheme, hiddenThinkingLabel?: string, outputPad?: number, markdownTransformers?: readonly MarkdownTransformer[], collapseCodeBlocks?: boolean);
    invalidate(): void;
    setHideThinkingBlock(hide: boolean): void;
    setCollapseCodeBlocks(collapse: boolean): void;
    setHiddenThinkingLabel(label: string): void;
    setOutputPad(padding: number): void;
    render(width: number): string[];
    updateContent(message: AssistantMessage, isStreaming?: boolean): void;
}
//# sourceMappingURL=assistant-message.d.ts.map