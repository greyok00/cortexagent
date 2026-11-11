import Anthropic from "@anthropic-ai/sdk";
import type { SimpleStreamOptions, StreamFunction, StreamOptions } from "../types.ts";
export type AnthropicEffort = "low" | "medium" | "high" | "xhigh" | "max";
export type AnthropicThinkingDisplay = "summarized" | "omitted";
export interface AnthropicOptions extends StreamOptions {
    thinkingEnabled?: boolean;
    thinkingBudgetTokens?: number;
    effort?: AnthropicEffort;
    thinkingDisplay?: AnthropicThinkingDisplay;
    interleavedThinking?: boolean;
    toolChoice?: "auto" | "any" | "none" | {
        type: "tool";
        name: string;
    };
    client?: Anthropic;
}
export declare const stream: StreamFunction<"anthropic-messages", AnthropicOptions>;
export declare const streamSimple: StreamFunction<"anthropic-messages", SimpleStreamOptions>;
//# sourceMappingURL=anthropic-messages.d.ts.map