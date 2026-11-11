import type { ThinkingLevel } from "@cortexagent/agent-core";
import { type Api, type AuthOperationOptions, type KnownProvider, type Model } from "@cortexagent/ai";
import type { ModelRuntime } from "./model-runtime.ts";
export declare const defaultModelPerProvider: Record<KnownProvider, string>;
export interface ScopedModel {
    model: Model<Api>;
    thinkingLevel?: ThinkingLevel;
}
export declare function findExactModelReferenceMatch(modelReference: string, availableModels: Model<Api>[]): Model<Api> | undefined;
export interface ParsedModelResult {
    model: Model<Api> | undefined;
    thinkingLevel?: ThinkingLevel;
    warning: string | undefined;
}
export declare function parseModelPattern(pattern: string, availableModels: Model<Api>[], options?: {
    allowInvalidThinkingLevelFallback?: boolean;
}): ParsedModelResult;
export interface ModelScopeDiagnostic {
    type: "warning";
    code: "no-match" | "invalid-thinking-level";
    message: string;
    pattern: string;
}
export interface ResolveModelScopeResult {
    scopedModels: ScopedModel[];
    diagnostics: ModelScopeDiagnostic[];
}
export declare function resolveModelScopeFromModels(patterns: string[], models: readonly Model<Api>[]): ResolveModelScopeResult;
export declare function resolveModelScopeWithDiagnostics(patterns: string[], modelRuntime: ModelRuntime, options?: AuthOperationOptions): Promise<ResolveModelScopeResult>;
export declare function resolveModelScope(patterns: string[], modelRuntime: ModelRuntime, options?: AuthOperationOptions): Promise<ScopedModel[]>;
export interface ResolveCliModelResult {
    model: Model<Api> | undefined;
    thinkingLevel?: ThinkingLevel;
    warning: string | undefined;
    error: string | undefined;
}
export declare function resolveCliModel(options: {
    cliProvider?: string;
    cliModel?: string;
    cliThinking?: ThinkingLevel;
    modelRuntime: ModelRuntime;
}): ResolveCliModelResult;
export interface InitialModelResult {
    model: Model<Api> | undefined;
    thinkingLevel: ThinkingLevel;
    fallbackMessage: string | undefined;
}
export declare function findInitialModel(options: {
    cliProvider?: string;
    cliModel?: string;
    scopedModels: ScopedModel[];
    isContinuing: boolean;
    defaultProvider?: string;
    defaultModelId?: string;
    defaultThinkingLevel?: ThinkingLevel;
    modelRuntime: ModelRuntime;
}): Promise<InitialModelResult>;
export declare function restoreModelFromSession(savedProvider: string, savedModelId: string, currentModel: Model<Api> | undefined, shouldPrintMessages: boolean, modelRuntime: ModelRuntime): Promise<{
    model: Model<Api> | undefined;
    fallbackMessage: string | undefined;
}>;
//# sourceMappingURL=model-resolver.d.ts.map