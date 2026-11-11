import type { Provider } from "../models.ts";
export interface RadiusProviderOptions {
    id?: string;
    name?: string;
    gateway?: string;
}
export declare function radiusProvider(options?: RadiusProviderOptions): Provider<"cortex-messages">;
//# sourceMappingURL=radius.d.ts.map