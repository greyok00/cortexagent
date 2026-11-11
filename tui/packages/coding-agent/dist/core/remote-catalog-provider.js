import { VERSION } from "../config.js";
import { getCortexUserAgent } from "../utils/cortex-user-agent.js";
import { fetchWithRetry } from "../utils/management-http.js";
const DEFAULT_CATALOG_BASE_URL = "http://127.0.0.1";
export const REMOTE_CATALOG_REFRESH_INTERVAL_MS = 4 * 60 * 60 * 1000;
function mergeModels(baseline, dynamic) {
    const merged = [...baseline];
    for (const model of dynamic) {
        const index = merged.findIndex((entry) => entry.id === model.id);
        if (index >= 0)
            merged[index] = model;
        else
            merged.push(model);
    }
    return merged;
}
function parseCatalog(providerId, value) {
    const entries = Array.isArray(value)
        ? value
        : typeof value === "object" && value !== null && "models" in value && Array.isArray(value.models)
            ? value.models
            : typeof value === "object" && value !== null
                ? Object.values(value)
                : undefined;
    if (!entries)
        throw new Error(`Invalid model catalog for provider "${providerId}"`);
    return entries
        .filter((entry) => typeof entry === "object" && entry !== null && "id" in entry)
        .map((model) => ({ ...model, provider: providerId }));
}
function remoteModels(entry, localGeneratedAt) {
    if (!entry)
        return [];
    if (localGeneratedAt !== undefined && (entry.lastModified === undefined || entry.lastModified <= localGeneratedAt)) {
        return [];
    }
    return entry.models;
}
export function withRemoteCatalog(provider, catalogBaseUrl = DEFAULT_CATALOG_BASE_URL, localGeneratedAt) {
    let dynamicModels = [];
    return {
        ...provider,
        getModels: () => mergeModels(provider.getModels(), dynamicModels),
        refreshModels: async (context) => {
            const stored = context.stored;
            const restored = remoteModels(stored, localGeneratedAt).filter((model) => model.provider === provider.id);
            if (!(await context.publish({
                update: () => {
                    dynamicModels = restored;
                },
            }))) {
                return;
            }
            if (!context.allowNetwork || context.signal.aborted)
                return;
            if (!context.force &&
                stored?.checkedAt !== undefined &&
                stored.lastModified !== undefined &&
                Date.now() - stored.checkedAt < REMOTE_CATALOG_REFRESH_INTERVAL_MS) {
                return;
            }
            const validator = stored?.models.length ? stored.etag : undefined;
            const url = new URL(`/api/models/providers/${encodeURIComponent(provider.id)}`, catalogBaseUrl);
            const response = await fetchWithRetry(url, {
                headers: {
                    accept: "application/json",
                    "User-Agent": getCortexUserAgent(VERSION),
                    ...(validator ? { "if-none-match": validator } : {}),
                },
                signal: context.signal,
            });
            if (context.signal.aborted)
                return;
            const checkedAt = Date.now();
            if (response.status === 304 && stored) {
                await context.publish({ persist: { ...stored, checkedAt } });
                return;
            }
            if (response.status === 404 || response.status === 501) {
                await context.publish({
                    persist: {
                        ...(stored ?? { models: [] }),
                        checkedAt,
                        lastModified: 0,
                        etag: undefined,
                    },
                });
                return;
            }
            if (!response.ok) {
                await context.publish({ persist: { ...(stored ?? { models: [] }), checkedAt } });
                throw new Error(`Model catalog request failed for ${provider.id}: ${response.status}`);
            }
            const refreshed = parseCatalog(provider.id, await response.json());
            const lastModified = Date.parse(response.headers.get("last-modified") ?? "");
            if (context.signal.aborted)
                return;
            const entry = {
                models: refreshed,
                checkedAt,
                lastModified: Number.isNaN(lastModified) ? 0 : lastModified,
                etag: response.headers.get("etag") ?? undefined,
            };
            const published = remoteModels(entry, localGeneratedAt);
            await context.publish({
                persist: entry,
                update: () => {
                    dynamicModels = published;
                },
            });
        },
    };
}
//# sourceMappingURL=remote-catalog-provider.js.map