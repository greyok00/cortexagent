import { type AuthResolutionOverrides } from "./auth/resolve.ts";
import type { AuthResult, ProviderAuth } from "./auth/types.ts";
import type { CreateModelsOptions } from "./models.ts";
import type { AssistantImages, ImagesApi, ImagesContext, ImagesModel, ImagesOptions, ProviderImages } from "./types.ts";
export interface ImagesProvider {
    readonly id: string;
    readonly name: string;
    readonly auth: ProviderAuth;
    getModels(): readonly ImagesModel<ImagesApi>[];
    refreshModels?(): Promise<void>;
    generateImages(model: ImagesModel<ImagesApi>, context: ImagesContext, options?: ImagesOptions): Promise<AssistantImages>;
}
export interface ImagesModels {
    getProviders(): readonly ImagesProvider[];
    getProvider(id: string): ImagesProvider | undefined;
    getModels(provider?: string): readonly ImagesModel<ImagesApi>[];
    getModel(provider: string, id: string): ImagesModel<ImagesApi> | undefined;
    refresh(provider?: string): Promise<void>;
    getAuth(providerId: string, overrides?: AuthResolutionOverrides): Promise<AuthResult | undefined>;
    getAuth(model: ImagesModel<ImagesApi>, overrides?: AuthResolutionOverrides): Promise<AuthResult | undefined>;
    generateImages(model: ImagesModel<ImagesApi>, context: ImagesContext, options?: ImagesOptions): Promise<AssistantImages>;
}
export interface MutableImagesModels extends ImagesModels {
    setProvider(provider: ImagesProvider): void;
    deleteProvider(id: string): void;
    clearProviders(): void;
}
export declare function createImagesModels(options?: CreateModelsOptions): MutableImagesModels;
export interface CreateImagesProviderOptions {
    id: string;
    name?: string;
    auth: ProviderAuth;
    models: readonly ImagesModel<ImagesApi>[];
    refreshModels?: () => Promise<readonly ImagesModel<ImagesApi>[]>;
    api: ProviderImages;
}
export declare function createImagesProvider(input: CreateImagesProviderOptions): ImagesProvider;
//# sourceMappingURL=images-models.d.ts.map