import type { OAuthCredential } from "../auth/types.ts";
import type { Model, ThinkingLevelMap } from "../types.ts";
export declare const DEFAULT_RADIUS_GATEWAY = "http://127.0.0.1:8080";
export type RadiusGatewayModel = {
    id: string;
    name: string;
    reasoning: boolean;
    thinkingLevelMap?: ThinkingLevelMap;
    input: ("text" | "image")[];
    cost: Model<"cortex-messages">["cost"];
    contextWindow: number;
    maxTokens: number;
};
export type RadiusGatewayConfig = {
    baseUrl: string;
    models: RadiusGatewayModel[];
};
export type RadiusOAuthCredential = OAuthCredential & {
    gatewayConfig?: RadiusGatewayConfig;
};
export declare function normalizeRadiusGatewayUrl(value: string): string;
export declare function getRadiusCredentialConfig(credential: OAuthCredential | undefined): RadiusGatewayConfig | undefined;
export declare function getRadiusModelsFromConfig(providerId: string, config: RadiusGatewayConfig): Model<"cortex-messages">[];
export declare function getRadiusModels(providerId: string, credential: OAuthCredential | undefined): Model<"cortex-messages">[];
export declare function loadRadiusGatewayConfig(gateway: string, apiKey?: string, signal?: AbortSignal): Promise<RadiusGatewayConfig>;
//# sourceMappingURL=radius-config.d.ts.map