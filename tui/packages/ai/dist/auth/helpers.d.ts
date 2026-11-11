import type { ApiKeyAuth, OAuthAuth } from "./types.ts";
export declare function envApiKeyAuth(name: string, envVars: readonly string[]): ApiKeyAuth;
export declare function lazyOAuth(input: {
    name: string;
    isSubscription?: boolean;
    loginLabel?: string;
    load: () => Promise<OAuthAuth>;
}): OAuthAuth;
//# sourceMappingURL=helpers.d.ts.map