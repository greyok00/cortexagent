import type { Provider } from "@cortexagent/ai";
import { type LlamaModelInfo } from "./client.ts";
export declare const LLAMA_PROVIDER_ID = "the engine";
export declare const DEFAULT_ENGINE_BIN_URL = "http://127.0.0.1:8080";
export interface LlamaProviderController {
    provider: Provider<"openai-completions">;
    setCatalog(models: readonly LlamaModelInfo[], serverUrl: string): void;
}
export declare function createLlamaProvider(): LlamaProviderController;
//# sourceMappingURL=provider.d.ts.map