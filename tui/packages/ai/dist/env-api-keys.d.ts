import type { KnownProvider, ProviderEnv } from "./types.ts";
export declare const ANTHROPIC_AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN";
export declare const ANTHROPIC_OAUTH_TOKEN_ENV = "ANTHROPIC_OAUTH_TOKEN";
export declare const ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY";
export declare function findEnvKeys(provider: KnownProvider, env?: ProviderEnv): string[] | undefined;
export declare function findEnvKeys(provider: string, env?: ProviderEnv): string[] | undefined;
export declare function getEnvApiKey(provider: KnownProvider, env?: ProviderEnv): string | undefined;
export declare function getEnvApiKey(provider: string, env?: ProviderEnv): string | undefined;
//# sourceMappingURL=env-api-keys.d.ts.map