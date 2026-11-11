import type { ImageContent, TextContent, ThinkingContent, ToolCall } from "../types.ts";
type Content = TextContent | ImageContent | ThinkingContent | ToolCall;
export declare function contentText(content: string | readonly Content[], separator?: string): string;
export {};
//# sourceMappingURL=text.d.ts.map