import { type ImagesProvider, type MutableImagesModels } from "../images-models.ts";
import { MODELS } from "../models.generated.ts";
import { type CreateModelsOptions, type MutableModels, type Provider } from "../models.ts";
import type { Api, Model } from "../types.ts";
import { radiusProvider } from "./radius.ts";
export { radiusProvider };
export type BuiltinProvider = keyof typeof MODELS;
type BuiltinModelApi<TProvider extends BuiltinProvider, TModelId extends keyof (typeof MODELS)[TProvider]> = (typeof MODELS)[TProvider][TModelId] extends {
    api: infer TApi;
} ? (TApi extends Api ? TApi : never) : never;
export declare function getBuiltinModel<TProvider extends BuiltinProvider, TModelId extends keyof (typeof MODELS)[TProvider]>(provider: TProvider, modelId: TModelId): Model<BuiltinModelApi<TProvider, TModelId>>;
export declare function getBuiltinProviders(): BuiltinProvider[];
export declare function getBuiltinModelDataGeneratedAt(): number | undefined;
export declare function getBuiltinModels<TProvider extends BuiltinProvider>(provider: TProvider): Model<BuiltinModelApi<TProvider, keyof (typeof MODELS)[TProvider]>>[];
export declare function builtinProviders(): Provider[];
export declare function builtinModels(options?: CreateModelsOptions): MutableModels;
export declare function builtinImagesProviders(): ImagesProvider[];
export declare function builtinImagesModels(options?: CreateModelsOptions): MutableImagesModels;
//# sourceMappingURL=all.d.ts.map