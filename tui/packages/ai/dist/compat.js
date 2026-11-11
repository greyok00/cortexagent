export * from "./api/anthropic-messages.lazy.js";
export * from "./api/azure-openai-responses.lazy.js";
export * from "./api/bedrock-converse-stream.lazy.js";
export * from "./api/cortex-messages.lazy.js";
export * from "./api/google-generative-ai.lazy.js";
export * from "./api/google-vertex.lazy.js";
export * from "./api/mistral-conversations.lazy.js";
export * from "./api/openai-codex-responses.lazy.js";
export * from "./api/openai-completions.lazy.js";
export * from "./api/openai-responses.lazy.js";
export * from "./env-api-keys.js";
export * from "./image-models.js";
export * from "./images.js";
export * from "./images-api-registry.js";
export * from "./index.js";
export * from "./legacy-api-aliases.js";
export * from "./providers/images/register-builtins.js";
import { anthropicMessagesApi } from "./api/anthropic-messages.lazy.js";
import { azureOpenAIResponsesApi } from "./api/azure-openai-responses.lazy.js";
import { bedrockConverseStreamApi } from "./api/bedrock-converse-stream.lazy.js";
import { piMessagesApi } from "./api/cortex-messages.lazy.js";
import { googleGenerativeAIApi } from "./api/google-generative-ai.lazy.js";
import { googleVertexApi } from "./api/google-vertex.lazy.js";
import { mistralConversationsApi } from "./api/mistral-conversations.lazy.js";
import { openAICodexResponsesApi } from "./api/openai-codex-responses.lazy.js";
import { openAICompletionsApi } from "./api/openai-completions.lazy.js";
import { openAIResponsesApi } from "./api/openai-responses.lazy.js";
import { getEnvApiKey } from "./env-api-keys.js";
import { builtinModels, getBuiltinModel, getBuiltinModels, getBuiltinProviders } from "./providers/all.js";
import { createFauxCore } from "./providers/faux.js";
export const getModel = getBuiltinModel;
export const getModels = getBuiltinModels;
export const getProviders = getBuiltinProviders;
const apiProviderRegistry = new Map();
function wrapStream(api, stream) {
    return (model, context, options) => {
        if (model.api !== api) {
            throw new Error(`Mismatched api: ${model.api} expected ${api}`);
        }
        return stream(model, context, options);
    };
}
function wrapStreamSimple(api, streamSimple) {
    return (model, context, options) => {
        if (model.api !== api) {
            throw new Error(`Mismatched api: ${model.api} expected ${api}`);
        }
        return streamSimple(model, context, options);
    };
}
export function registerApiProvider(provider, sourceId) {
    apiProviderRegistry.set(provider.api, {
        provider: {
            api: provider.api,
            stream: wrapStream(provider.api, provider.stream),
            streamSimple: wrapStreamSimple(provider.api, provider.streamSimple),
        },
        sourceId,
    });
}
export function getApiProvider(api) {
    return apiProviderRegistry.get(api)?.provider;
}
export function getApiProviders() {
    return Array.from(apiProviderRegistry.values(), (entry) => entry.provider);
}
export function unregisterApiProviders(sourceId) {
    for (const [api, entry] of apiProviderRegistry.entries()) {
        if (entry.sourceId === sourceId) {
            apiProviderRegistry.delete(api);
        }
    }
}
function clearApiProviders() {
    apiProviderRegistry.clear();
}
export function registerFauxProvider(options = {}) {
    const core = createFauxCore(options);
    const sourceId = `faux-provider-${Math.random().toString(36).slice(2, 10)}`;
    registerApiProvider({ api: core.api, stream: core.stream, streamSimple: core.streamSimple }, sourceId);
    return {
        api: core.api,
        models: core.models,
        getModel: core.getModel,
        state: core.state,
        setResponses: core.setResponses,
        appendResponses: core.appendResponses,
        getPendingResponseCount: core.getPendingResponseCount,
        unregister() {
            unregisterApiProviders(sourceId);
        },
    };
}
const BUILTIN_APIS = [
    ["anthropic-messages", anthropicMessagesApi()],
    ["openai-completions", openAICompletionsApi()],
    ["openai-responses", openAIResponsesApi()],
    ["openai-codex-responses", openAICodexResponsesApi()],
    ["azure-openai-responses", azureOpenAIResponsesApi()],
    ["google-generative-ai", googleGenerativeAIApi()],
    ["google-vertex", googleVertexApi()],
    ["mistral-conversations", mistralConversationsApi()],
    ["bedrock-converse-stream", bedrockConverseStreamApi()],
    ["cortex-messages", piMessagesApi()],
];
const builtinApiProviderInstances = new Map();
export function registerBuiltInApiProviders() {
    for (const [api, streams] of BUILTIN_APIS) {
        if (!getApiProvider(api)) {
            registerApiProvider({ api, stream: streams.stream, streamSimple: streams.streamSimple });
        }
        builtinApiProviderInstances.set(api, getApiProvider(api));
    }
}
export function resetApiProviders() {
    clearApiProviders();
    builtinApiProviderInstances.clear();
    registerBuiltInApiProviders();
}
registerBuiltInApiProviders();
const compatModels = builtinModels();
const AMBIENT_AUTH_MARKER = "<authenticated>";
function hasExplicitApiKey(apiKey) {
    return typeof apiKey === "string" && apiKey.trim().length > 0;
}
function withEnvApiKey(model, options) {
    if (hasExplicitApiKey(options?.apiKey))
        return options;
    const apiKey = getEnvApiKey(model.provider, options?.env);
    if (!apiKey || apiKey === AMBIENT_AUTH_MARKER)
        return options;
    return { ...options, apiKey };
}
function hasResolvedCloudflareAuth(options) {
    return hasExplicitApiKey(options?.apiKey) || typeof options?.headers?.["cf-aig-authorization"] === "string";
}
function getBuiltinProviderForModel(model) {
    if (getApiProvider(model.api) !== builtinApiProviderInstances.get(model.api))
        return undefined;
    const provider = compatModels.getProvider(model.provider);
    return provider?.getModels().some((candidate) => candidate.api === model.api) ? provider : undefined;
}
function resolveApiProvider(api) {
    const provider = getApiProvider(api);
    if (!provider) {
        throw new Error(`No API provider registered for api: ${api}`);
    }
    return provider;
}
export function stream(model, context, options) {
    const builtinProvider = getBuiltinProviderForModel(model);
    if (builtinProvider) {
        if (model.provider.startsWith("cloudflare-") && !hasResolvedCloudflareAuth(options)) {
            return compatModels.stream(model, context, options);
        }
        return builtinProvider.stream(model, context, withEnvApiKey(model, options));
    }
    const provider = resolveApiProvider(model.api);
    return provider.stream(model, context, withEnvApiKey(model, options));
}
export async function complete(model, context, options) {
    const s = stream(model, context, options);
    return s.result();
}
export function streamSimple(model, context, options) {
    const builtinProvider = getBuiltinProviderForModel(model);
    if (builtinProvider) {
        if (model.provider.startsWith("cloudflare-") && !hasResolvedCloudflareAuth(options)) {
            return compatModels.streamSimple(model, context, options);
        }
        return builtinProvider.streamSimple(model, context, withEnvApiKey(model, options));
    }
    const provider = resolveApiProvider(model.api);
    return provider.streamSimple(model, context, withEnvApiKey(model, options));
}
export async function completeSimple(model, context, options) {
    const s = streamSimple(model, context, options);
    return s.result();
}
//# sourceMappingURL=compat.js.map