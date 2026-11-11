import type { ProviderEnv } from "../types.ts";
import type { AuthContext, AuthResult, CredentialStore, ProviderAuth } from "./types.ts";
export type ModelsErrorCode = "model_source" | "model_validation" | "provider" | "stream" | "auth" | "oauth";
export interface AuthResolutionOverrides {
    apiKey?: string;
    env?: ProviderEnv;
    minOAuthValidityMs?: number;
    signal?: AbortSignal;
}
export declare class ModelsError extends Error {
    readonly code: ModelsErrorCode;
    constructor(code: ModelsErrorCode, message: string, options?: {
        cause?: unknown;
    });
}
export declare function resolveProviderAuth(provider: {
    id: string;
    auth: ProviderAuth;
}, credentials: CredentialStore, authContext: AuthContext, overrides?: AuthResolutionOverrides): Promise<AuthResult | undefined>;
//# sourceMappingURL=resolve.d.ts.map