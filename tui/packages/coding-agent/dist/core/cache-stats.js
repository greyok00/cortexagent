export const CACHE_TTL_MS = 5 * 60 * 1000;
const NOISE_FLOOR_TOKENS = 1024;
function detectMiss(prev, message, models) {
    const usage = message.usage;
    const promptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
    if (!prev || promptTokens <= 0 || (usage.cacheRead + usage.cacheWrite === 0 && !prev.reportedCache)) {
        return undefined;
    }
    const missedTokens = Math.min(prev.promptTokens, promptTokens) - usage.cacheRead;
    if (missedTokens <= NOISE_FLOOR_TOKENS)
        return undefined;
    const paidTokens = usage.input + usage.cacheWrite;
    const paidPerToken = paidTokens > 0 ? (usage.cost.input + usage.cost.cacheWrite) / paidTokens : 0;
    const readPerToken = usage.cacheRead > 0
        ? usage.cost.cacheRead / usage.cacheRead
        : (models.getModel(message.provider, message.model)?.cost.cacheRead ?? 0) / 1_000_000;
    return {
        missedTokens,
        missedCost: missedTokens * Math.max(0, paidPerToken - readPerToken),
        idleMs: Math.max(0, message.timestamp - prev.timestamp),
        modelChanged: `${message.provider}/${message.model}` !== prev.modelKey,
    };
}
function asPreviousRequest(message, reportedCache) {
    const usage = message.usage;
    const promptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
    if (promptTokens <= 0)
        return undefined;
    return {
        promptTokens,
        modelKey: `${message.provider}/${message.model}`,
        timestamp: message.timestamp,
        reportedCache: reportedCache || usage.cacheRead + usage.cacheWrite > 0,
    };
}
function scan(entries, models) {
    let prev;
    const totals = { missedTokens: 0, missedCost: 0, missCount: 0 };
    const misses = new Map();
    for (const entry of entries) {
        if (entry.type === "compaction" || entry.type === "branch_summary") {
            prev = undefined;
            continue;
        }
        if (entry.type === "message" && entry.message.role === "assistant") {
            const miss = detectMiss(prev, entry.message, models);
            if (miss) {
                totals.missedTokens += miss.missedTokens;
                totals.missedCost += miss.missedCost;
                totals.missCount += 1;
                misses.set(entry.message, miss);
            }
            prev = asPreviousRequest(entry.message, prev?.reportedCache ?? false) ?? prev;
        }
    }
    return { prev, totals, misses };
}
export function computeCacheWaste(entries, models) {
    return scan(entries, models).totals;
}
export function collectCacheMisses(entries, models) {
    return scan(entries, models).misses;
}
export function detectCacheMiss(entries, message, models) {
    return detectMiss(scan(entries, models).prev, message, models);
}
//# sourceMappingURL=cache-stats.js.map