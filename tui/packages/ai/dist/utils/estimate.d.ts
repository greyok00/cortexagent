import type { Context, ImageContent, Message, TextContent, Usage } from "../types.ts";
export interface ContextUsageEstimate {
    tokens: number;
    usageTokens: number;
    trailingTokens: number;
    lastUsageIndex: number | null;
}
export declare function calculateContextTokens(usage: Usage): number;
export declare function estimateTextTokens(text: string): number;
export declare function estimateTextAndImageContentTokens(content: string | Array<TextContent | ImageContent>): number;
export declare function estimateMessageTokens(message: Message): number;
export declare function estimateContextTokens(context: Context | readonly Message[]): ContextUsageEstimate;
//# sourceMappingURL=estimate.d.ts.map