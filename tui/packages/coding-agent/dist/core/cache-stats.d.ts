import type { AssistantMessage } from "@cortexagent/ai";
import type { SessionEntry } from "./session-manager.ts";
export declare const CACHE_TTL_MS: number;
export interface CacheMiss {
    missedTokens: number;
    missedCost: number;
    idleMs: number;
    modelChanged: boolean;
}
export interface CacheWasteTotals {
    missedTokens: number;
    missedCost: number;
    missCount: number;
}
export interface ModelPriceSource {
    getModel(provider: string, modelId: string): {
        cost: {
            cacheRead: number;
        };
    } | undefined;
}
export declare function computeCacheWaste(entries: SessionEntry[], models: ModelPriceSource): CacheWasteTotals;
export declare function collectCacheMisses(entries: SessionEntry[], models: ModelPriceSource): Map<AssistantMessage, CacheMiss>;
export declare function detectCacheMiss(entries: SessionEntry[], message: AssistantMessage, models: ModelPriceSource): CacheMiss | undefined;
//# sourceMappingURL=cache-stats.d.ts.map