import type { SimpleStreamOptions, StreamFunction, StreamOptions, ThinkingBudgets, ThinkingLevel } from "../types.ts";
export type BedrockThinkingDisplay = "summarized" | "omitted";
export interface BedrockOptions extends StreamOptions {
    region?: string;
    profile?: string;
    toolChoice?: "auto" | "any" | "none" | {
        type: "tool";
        name: string;
    };
    reasoning?: ThinkingLevel;
    thinkingBudgets?: ThinkingBudgets;
    interleavedThinking?: boolean;
    thinkingDisplay?: BedrockThinkingDisplay;
    requestMetadata?: Record<string, string>;
    bearerToken?: string;
}
export declare const stream: StreamFunction<"bedrock-converse-stream", BedrockOptions>;
export declare const streamSimple: StreamFunction<"bedrock-converse-stream", SimpleStreamOptions>;
//# sourceMappingURL=bedrock-converse-stream.d.ts.map