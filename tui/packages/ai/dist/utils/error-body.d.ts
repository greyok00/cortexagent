export declare const MAX_PROVIDER_ERROR_BODY_CHARS = 4000;
export interface NormalizedProviderError {
    status?: number;
    body?: string;
    message: string;
    messageCarriesBody: boolean;
}
export declare function normalizeProviderError(error: unknown): NormalizedProviderError;
export declare function formatProviderError(norm: NormalizedProviderError, prefix?: string): string;
export declare function truncateErrorText(text: string, maxChars: number): string;
export declare function safeJsonStringify(value: unknown): string;
//# sourceMappingURL=error-body.d.ts.map