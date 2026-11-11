const RETRYABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);
export async function fetchWithRetry(input, init = undefined, options = {}) {
    const maxRetries = options.maxRetries === undefined || !Number.isFinite(options.maxRetries)
        ? 2
        : Math.max(0, Math.floor(options.maxRetries));
    const retryOnStatus = options.retryOnStatus ?? true;
    const parentSignal = init?.signal;
    const timeoutSignal = options.timeoutMs !== undefined && options.timeoutMs > 0 ? AbortSignal.timeout(options.timeoutMs) : undefined;
    const signal = timeoutSignal
        ? parentSignal
            ? AbortSignal.any([parentSignal, timeoutSignal])
            : timeoutSignal
        : parentSignal;
    for (let attempt = 0;; attempt++) {
        signal?.throwIfAborted();
        try {
            const response = await fetch(input, signal ? { ...init, signal } : init);
            const shouldRetry = retryOnStatus && RETRYABLE_STATUS_CODES.has(response.status) && attempt < maxRetries;
            if (!shouldRetry)
                return response;
            try {
                await response.body?.cancel();
            }
            catch {
                // The response is being discarded before a retry. There is nothing useful to
                // do if cancelling its body also fails.
            }
        }
        catch (error) {
            if (parentSignal?.aborted ||
                timeoutSignal?.aborted ||
                (error instanceof Error && error.name === "AbortError" && timeoutSignal === undefined) ||
                attempt >= maxRetries) {
                throw error;
            }
        }
    }
}
//# sourceMappingURL=management-http.js.map