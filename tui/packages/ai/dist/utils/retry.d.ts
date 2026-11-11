import type { AssistantMessage } from "../types.ts";
export interface RetryPolicy {
    enabled: boolean;
    maxRetries: number;
    baseDelayMs: number;
}
export interface RetryCallbacks {
    onRetryScheduled?: (attempt: number, maxAttempts: number, delayMs: number, errorMessage: string) => void | Promise<void>;
    onRetryAttemptStart?: () => void | Promise<void>;
    onRetryFinished?: (success: boolean, attempt: number, finalError?: string) => void | Promise<void>;
}
export declare function retryAssistantCall(produce: () => Promise<AssistantMessage>, policy: RetryPolicy | undefined, signal: AbortSignal | undefined, callbacks?: RetryCallbacks): Promise<AssistantMessage>;
export declare function isRetryableAssistantError(message: AssistantMessage): boolean;
//# sourceMappingURL=retry.d.ts.map