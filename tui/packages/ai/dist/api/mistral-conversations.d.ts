import type { SimpleStreamOptions, StreamFunction, StreamOptions } from "../types.ts";
type MistralReasoningEffort = "none" | "high";
export interface MistralOptions extends StreamOptions {
    toolChoice?: "auto" | "none" | "any" | "required" | {
        type: "function";
        function: {
            name: string;
        };
    };
    promptMode?: "reasoning";
    reasoningEffort?: MistralReasoningEffort;
}
export declare const stream: StreamFunction<"mistral-conversations", MistralOptions>;
export declare const streamSimple: StreamFunction<"mistral-conversations", SimpleStreamOptions>;
export {};
//# sourceMappingURL=mistral-conversations.d.ts.map