interface ProviderRetryOptions {
    maxRetries?: number;
    maxRetryDelayMs?: number;
    signal?: AbortSignal;
}
export declare function retryProviderRequest<T>(request: () => Promise<T>, options?: ProviderRetryOptions): Promise<T>;
export {};
//# sourceMappingURL=provider-retry.d.ts.map