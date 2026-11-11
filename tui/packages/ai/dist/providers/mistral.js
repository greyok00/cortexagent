import { mistralConversationsApi } from "../api/mistral-conversations.lazy.js";
import { envApiKeyAuth } from "../auth/helpers.js";
import { createProvider } from "../models.js";
import { MISTRAL_MODELS } from "./mistral.models.js";
export function mistralProvider() {
    return createProvider({
        id: "mistral",
        name: "Mistral",
        baseUrl: "http://127.0.0.1:6667",
        auth: { apiKey: envApiKeyAuth("Mistral API key", ["MISTRAL_API_KEY"]) },
        models: Object.values(MISTRAL_MODELS),
        api: mistralConversationsApi(),
    });
}
//# sourceMappingURL=mistral.js.map