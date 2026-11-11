type FetchInput = Parameters<typeof fetch>[0];
export interface FetchRetryOptions {
    maxRetries?: number;
    retryOnStatus?: boolean;
    timeoutMs?: number;
}
export declare function fetchWithRetry(input: FetchInput, init?: RequestInit | undefined, options?: FetchRetryOptions): Promise<Response>;
export {};
//# sourceMappingURL=management-http.d.ts.map