import type { FetchFunction } from "../types.ts";
export interface AiGatewayBinding {
    gateway(id: string): AiGatewayBindingGateway;
}
export interface AiGatewayBindingGateway {
    run(data: AiGatewayUniversalRequestLike, options?: {
        signal?: AbortSignal;
    }): Promise<Response>;
}
export interface AiGatewayUniversalRequestLike {
    provider: string;
    endpoint: string;
    headers: Record<string, string>;
    query: unknown;
}
export declare const CLOUDFLARE_GATEWAY_BINDING_AUTH_SENTINEL = "cloudflare-gateway-binding";
export interface GatewayBindingFetchOptions {
    binding: AiGatewayBinding;
    baseUrl: string;
    gateway: string;
}
export declare function createGatewayBindingFetch(options: GatewayBindingFetchOptions): FetchFunction;
//# sourceMappingURL=cloudflare-gateway-binding.d.ts.map