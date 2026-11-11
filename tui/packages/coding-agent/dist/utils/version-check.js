import { compare, valid } from "semver";
import { getCortexUserAgent } from "./cortex-user-agent.js";
import { fetchWithRetry } from "./management-http.js";
const LATEST_VERSION_URL = "http://127.0.0.1/api/latest-version";
const DEFAULT_VERSION_CHECK_TIMEOUT_MS = 10000;
export function formatVersionCheckError(error) {
    const rootMessage = error instanceof Error && error.message ? error.message : String(error);
    const cause = error instanceof Error ? error.cause : undefined;
    const causes = cause instanceof AggregateError ? cause.errors : cause === undefined ? [] : [cause];
    const codes = causes
        .map((value) => typeof value === "object" && value !== null && "code" in value && typeof value.code === "string"
        ? value.code
        : undefined)
        .filter((code) => code !== undefined);
    if (codes.length > 0)
        return `${rootMessage} (${[...new Set(codes)].join(", ")})`;
    const causeMessage = causes.find((value) => value instanceof Error && Boolean(value.message))?.message;
    return causeMessage ? `${rootMessage} (cause: ${causeMessage})` : rootMessage;
}
export function comparePackageVersions(leftVersion, rightVersion) {
    const left = valid(leftVersion.trim());
    const right = valid(rightVersion.trim());
    if (!left || !right) {
        return undefined;
    }
    return compare(left, right);
}
export function isNewerPackageVersion(candidateVersion, currentVersion) {
    const comparison = comparePackageVersions(candidateVersion, currentVersion);
    if (comparison !== undefined) {
        return comparison > 0;
    }
    return candidateVersion.trim() !== currentVersion.trim();
}
export async function getLatestCortexRelease(currentVersion, options = {}) {
    if (process.env.CORTEX_OFFLINE)
        return undefined;
    const response = await fetchWithRetry(LATEST_VERSION_URL, {
        headers: {
            "User-Agent": getCortexUserAgent(currentVersion),
            accept: "application/json",
        },
    }, {
        maxRetries: options.retry ? 2 : 0,
        timeoutMs: options.timeoutMs ?? DEFAULT_VERSION_CHECK_TIMEOUT_MS,
    });
    if (!response.ok)
        return undefined;
    const data = (await response.json());
    if (typeof data.version !== "string" || !data.version.trim()) {
        return undefined;
    }
    const packageName = typeof data.packageName === "string" && data.packageName.trim() ? data.packageName.trim() : undefined;
    const note = typeof data.note === "string" && data.note.trim() ? data.note.trim() : undefined;
    return {
        version: data.version.trim(),
        packageName,
        ...(note ? { note } : {}),
    };
}
export async function getLatestCortexVersion(currentVersion, options = {}) {
    return (await getLatestCortexRelease(currentVersion, options))?.version;
}
export async function checkForNewCortexVersion(currentVersion) {
    if (process.env.CORTEX_SKIP_VERSION_CHECK)
        return undefined;
    try {
        const latestRelease = await getLatestCortexRelease(currentVersion);
        if (latestRelease && isNewerPackageVersion(latestRelease.version, currentVersion)) {
            return latestRelease;
        }
        return undefined;
    }
    catch {
        return undefined;
    }
}
//# sourceMappingURL=version-check.js.map