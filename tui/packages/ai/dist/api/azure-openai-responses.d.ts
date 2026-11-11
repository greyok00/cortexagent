import type { SimpleStreamOptions, StreamFunction, StreamOptions } from "../types.ts";
export interface AzureOpenAIResponsesOptions extends StreamOptions {
    reasoningEffort?: "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
    reasoningSummary?: "auto" | "detailed" | "concise" | null;
    azureApiVersion?: string;
    azureResourceName?: string;
    azureBaseUrl?: string;
    azureDeploymentName?: string;
}
export declare const stream: StreamFunction<"azure-openai-responses", AzureOpenAIResponsesOptions>;
export declare const streamSimple: StreamFunction<"azure-openai-responses", SimpleStreamOptions>;
//# sourceMappingURL=azure-openai-responses.d.ts.map