import { Container, type MarkdownTheme } from "@cortexagent/tui";
import type { MessageRenderer } from "../../../core/extensions/types.ts";
import type { CustomMessage } from "../../../core/messages.ts";
export declare class CustomMessageComponent extends Container {
    private message;
    private customRenderer?;
    private box;
    private customComponent?;
    private markdownTheme;
    private _expanded;
    private outputPad;
    constructor(message: CustomMessage<unknown>, customRenderer?: MessageRenderer, markdownTheme?: MarkdownTheme, outputPad?: number);
    setExpanded(expanded: boolean): void;
    setOutputPad(outputPad: number): void;
    invalidate(): void;
    private rebuild;
}
//# sourceMappingURL=custom-message.d.ts.map