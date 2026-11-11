import type { OAuthAuth } from "../types.ts";
type OAuthFlowLoaders = {
    openaiCodex: () => OAuthAuth | Promise<OAuthAuth>;
    openrouter: () => OAuthAuth | Promise<OAuthAuth>;
    radius: (options: {
        name: string;
        gateway: string;
    }) => OAuthAuth | Promise<OAuthAuth>;
};
export declare function registerBundledOAuthFlowLoaders(loaders: OAuthFlowLoaders): void;
export declare const loadOpenAICodexOAuth: () => Promise<OAuthAuth>;
export declare const loadOpenRouterOAuth: () => Promise<OAuthAuth>;
export declare const loadRadiusOAuth: (options: {
    name: string;
    gateway: string;
}) => Promise<OAuthAuth>;
export {};
//# sourceMappingURL=load.d.ts.map