import { createImagesModels } from "../images-models.js";
import { MODELS } from "../models.generated.js";
import { createModels } from "../models.js";
import { azureOpenAIResponsesProvider } from "./azure-openai-responses.js";
import modelDataManifest from "./data/.manifest.json" with { type: "json" };
import { mistralProvider } from "./mistral.js";
import { openaiProvider } from "./openai.js";
import { openaiCodexProvider } from "./openai-codex.js";
import { openrouterProvider } from "./openrouter.js";
import { openrouterImagesProvider } from "./openrouter-images.js";
import { radiusProvider } from "./radius.js";
export { radiusProvider };
export function getBuiltinModel(provider, modelId) {
    const models = MODELS[provider];
    return models?.[modelId];
}
export function getBuiltinProviders() {
    return Object.keys(MODELS);
}
export function getBuiltinModelDataGeneratedAt() {
    const generatedAt = Date.parse(modelDataManifest.generatedAt);
    return Number.isNaN(generatedAt) ? undefined : generatedAt;
}
export function getBuiltinModels(provider) {
    const models = MODELS[provider];
    return models
        ? Object.values(models)
        : [];
}
export function builtinProviders() {
    return [
        azureOpenAIResponsesProvider(),
        mistralProvider(),
        openaiProvider(),
        openaiCodexProvider(),
        openrouterProvider(),
        radiusProvider(),
    ];
}
export function builtinModels(options) {
    const models = createModels(options);
    for (const provider of builtinProviders()) {
        models.setProvider(provider);
    }
    return models;
}
export function builtinImagesProviders() {
    return [openrouterImagesProvider()];
}
export function builtinImagesModels(options) {
    const models = createImagesModels(options);
    for (const provider of builtinImagesProviders()) {
        models.setProvider(provider);
    }
    return models;
}
//# sourceMappingURL=all.js.map