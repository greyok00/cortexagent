import { type Content, FinishReason, FunctionCallingConfigMode, type Part } from "@google/genai";
import type { Context, Model, StopReason, StreamOptions, Tool } from "../types.ts";
type GoogleApiType = "google-generative-ai" | "google-vertex";
export type GoogleThinkingLevel = "THINKING_LEVEL_UNSPECIFIED" | "MINIMAL" | "LOW" | "MEDIUM" | "HIGH";
export declare function isThinkingPart(part: Pick<Part, "thought" | "thoughtSignature">): boolean;
export declare function retainThoughtSignature(existing: string | undefined, incoming: string | undefined): string | undefined;
export declare function requiresToolCallId(modelId: string): boolean;
export declare function convertMessages<T extends GoogleApiType>(model: Model<T>, context: Context): Content[];
export declare function convertTools(tools: Tool[], useParameters?: boolean, supportsStrictMode?: boolean): {
    functionDeclarations: Record<string, unknown>[];
}[] | undefined;
export declare function supportsGoogleStrictToolSampling(modelId: string): boolean;
export declare function mapToolChoice(choice: string): FunctionCallingConfigMode;
export declare function resolveGoogleFunctionCallingMode(tools: Tool[], toolChoice: string | undefined, supportsStrictMode: boolean): FunctionCallingConfigMode | undefined;
export declare function mapStopReason(reason: FinishReason): StopReason;
export declare function mapStopReasonString(reason: string): StopReason;
export declare function retryGoogleRequest<T>(request: () => Promise<T>, options?: Pick<StreamOptions, "maxRetries" | "maxRetryDelayMs" | "signal">): Promise<T>;
export {};
//# sourceMappingURL=google-shared.d.ts.map