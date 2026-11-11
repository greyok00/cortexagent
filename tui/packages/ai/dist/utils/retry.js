function buildProviderErrorPattern(patterns) {
    return new RegExp(patterns.join("|"), "i");
}
const NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN = buildProviderErrorPattern([
    "GoUsageLimitError",
    "FreeUsageLimitError",
    "Monthly usage limit reached",
    "available balance",
    "insufficient_quota",
    "out of budget",
    "quota exceeded",
    "billing",
]);
const RETRYABLE_PROVIDER_ERROR_PATTERN = buildProviderErrorPattern([
    "overloaded",
    "rate.?limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "524",
    "service.?unavailable",
    "server.?error",
    "internal.?error",
    "provider.?returned.?error",
    "exceeded request buffer limit while retrying upstream",
    "network.?error",
    "connection.?error",
    "connection.?refused",
    "connection.?lost",
    "other side closed",
    "fetch failed",
    "getaddrinfo",
    "ENOTFOUND",
    "EAI_AGAIN",
    "upstream.?connect",
    "reset before headers",
    "socket hang up",
    "socket connection was closed",
    "timed? out",
    "timeout",
    "terminated",
    "websocket.?closed",
    "websocket.?error",
    "ended without",
    "stream ended before message_stop",
    "stream ended before a terminal response event",
    "http2 request did not get a response",
    "retry delay",
    "you can retry your request",
    "try your request again",
    "please retry your request",
    "ResourceExhausted",
]);
class RetrySleepAbortError extends Error {
    constructor() {
        super("Aborted");
    }
}
function sleep(ms, signal) {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) {
            reject(new RetrySleepAbortError());
            return;
        }
        const timeout = setTimeout(resolve, ms);
        signal?.addEventListener("abort", () => {
            clearTimeout(timeout);
            reject(new RetrySleepAbortError());
        }, { once: true });
    });
}
export async function retryAssistantCall(produce, policy, signal, callbacks) {
    const maxAttempts = policy?.enabled ? policy.maxRetries : 0;
    let attempt = 0;
    let lastRetry;
    for (;;) {
        const response = await produce();
        if (response.stopReason === "aborted") {
            if (lastRetry)
                await callbacks?.onRetryFinished?.(false, lastRetry.attempt);
            return response;
        }
        if (response.stopReason !== "error") {
            if (lastRetry)
                await callbacks?.onRetryFinished?.(true, lastRetry.attempt);
            return response;
        }
        if (attempt >= maxAttempts || !isRetryableAssistantError(response)) {
            if (lastRetry)
                await callbacks?.onRetryFinished?.(false, lastRetry.attempt, response.errorMessage);
            return response;
        }
        attempt++;
        lastRetry = { attempt, errorMessage: response.errorMessage || "Unknown error" };
        const delayMs = policy.baseDelayMs * 2 ** (attempt - 1);
        await callbacks?.onRetryScheduled?.(attempt, maxAttempts, delayMs, lastRetry.errorMessage);
        try {
            await sleep(delayMs, signal);
        }
        catch (error) {
            await callbacks?.onRetryFinished?.(false, attempt, lastRetry.errorMessage);
            if (error instanceof RetrySleepAbortError) {
                return { ...response, stopReason: "aborted", errorMessage: undefined };
            }
            throw error;
        }
        await callbacks?.onRetryAttemptStart?.();
    }
}
export function isRetryableAssistantError(message) {
    if (message.stopReason !== "error" || !message.errorMessage)
        return false;
    const errorMessage = message.errorMessage;
    if (NON_RETRYABLE_PROVIDER_LIMIT_ERROR_PATTERN.test(errorMessage))
        return false;
    return RETRYABLE_PROVIDER_ERROR_PATTERN.test(errorMessage);
}
//# sourceMappingURL=retry.js.map