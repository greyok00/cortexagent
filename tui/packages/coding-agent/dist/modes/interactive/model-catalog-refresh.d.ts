import type { ModelsRefreshResult } from "@cortexagent/ai";
import type { ModelRuntime } from "../../core/model-runtime.ts";
type ModelCatalogRuntime = Pick<ModelRuntime, "refresh">;
export declare function refreshModelCatalogs(modelRuntime: ModelCatalogRuntime, signal: AbortSignal): Promise<ModelsRefreshResult>;
export {};
//# sourceMappingURL=model-catalog-refresh.d.ts.map