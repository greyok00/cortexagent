import { operationSignal, raceWithAbortSignal } from "../utils/abort.js";
import { formatThrownValue } from "../utils/diagnostics.js";
export class ModelsError extends Error {
    code;
    constructor(code, message, options) {
        super(withCauseDetail(message, options?.cause), options);
        this.name = "ModelsError";
        this.code = code;
    }
}
function withCauseDetail(message, cause) {
    if (cause === undefined || cause === null)
        return message;
    const detail = formatThrownValue(cause).trim();
    if (!detail || message.includes(detail))
        return message;
    return `${message}: ${detail}`;
}
export function resolveProviderAuth(provider, credentials, authContext, overrides) {
    const signal = operationSignal(overrides?.signal);
    return raceWithAbortSignal(resolveProviderAuthWithSignal(provider, credentials, authContext, overrides, signal), signal);
}
async function resolveProviderAuthWithSignal(provider, credentials, authContext, overrides, signal) {
    signal.throwIfAborted();
    const requestAuthContext = overrides?.env ? overlayEnvAuthContext(authContext, overrides.env) : authContext;
    if (overrides?.apiKey !== undefined && provider.auth.apiKey) {
        return resolveApiKey(requestAuthContext, provider.auth.apiKey, provider.id, {
            type: "api_key",
            key: overrides.apiKey,
            env: overrides.env,
        }, signal);
    }
    const stored = await readCredential(credentials, provider.id, signal);
    if (stored) {
        if (stored.type === "oauth" && provider.auth.oauth) {
            return resolveStoredOAuth(credentials, provider.id, provider.auth.oauth, stored, signal, overrides?.minOAuthValidityMs);
        }
        if (stored.type === "api_key" && provider.auth.apiKey) {
            const credential = overrides?.env ? { ...stored, env: { ...stored.env, ...overrides.env } } : stored;
            return resolveApiKey(requestAuthContext, provider.auth.apiKey, provider.id, credential, signal);
        }
        return undefined;
    }
    return provider.auth.apiKey
        ? resolveApiKey(requestAuthContext, provider.auth.apiKey, provider.id, undefined, signal)
        : undefined;
}
function overlayEnvAuthContext(base, env) {
    return {
        env: async (name) => env[name] || (await base.env(name)),
        fileExists: (path) => base.fileExists(path),
    };
}
const DEFAULT_OAUTH_MINIMUM_VALIDITY_MS = 5 * 60 * 1000;
const DEFAULT_OAUTH_REFRESH_TIMEOUT_MS = 15_000;
async function resolveStoredOAuth(credentials, providerId, oauth, stored, signal, minOAuthValidityMs) {
    const minimumValidityMs = Math.max(DEFAULT_OAUTH_MINIMUM_VALIDITY_MS, minOAuthValidityMs ?? 0);
    const expiresSoon = (credential) => Date.now() + minimumValidityMs >= credential.expires;
    let credential = stored;
    if (expiresSoon(credential)) {
        let post;
        try {
            post = await credentials.modify(providerId, async (current) => {
                if (current?.type !== "oauth")
                    return undefined;
                if (!expiresSoon(current))
                    return undefined;
                try {
                    const refreshSignal = AbortSignal.any([
                        signal,
                        AbortSignal.timeout(DEFAULT_OAUTH_REFRESH_TIMEOUT_MS),
                    ]);
                    return await oauth.refresh(current, refreshSignal);
                }
                catch (error) {
                    throw new ModelsError("oauth", `OAuth refresh failed for ${providerId}`, { cause: error });
                }
            }, { signal });
        }
        catch (error) {
            if (error instanceof ModelsError)
                throw error;
            throw new ModelsError("auth", `Credential store modify failed for ${providerId}`, { cause: error });
        }
        if (post?.type !== "oauth")
            return undefined;
        credential = post;
        if (minOAuthValidityMs !== undefined && expiresSoon(credential)) {
            throw new ModelsError("oauth", `OAuth refresh returned a token that expires too soon for ${providerId}`);
        }
    }
    try {
        return { auth: await oauth.toAuth(credential), source: "OAuth" };
    }
    catch (error) {
        throw new ModelsError("oauth", `OAuth auth derivation failed for ${providerId}`, { cause: error });
    }
}
async function resolveApiKey(authContext, apiKey, providerId, credential, signal) {
    try {
        return await apiKey.resolve({ ctx: authContext, credential, signal });
    }
    catch (error) {
        throw new ModelsError("auth", `API key auth failed for provider ${providerId}`, { cause: error });
    }
}
async function readCredential(credentials, providerId, signal) {
    try {
        return await credentials.read(providerId, { signal });
    }
    catch (error) {
        throw new ModelsError("auth", `Credential store read failed for ${providerId}`, { cause: error });
    }
}
//# sourceMappingURL=resolve.js.map