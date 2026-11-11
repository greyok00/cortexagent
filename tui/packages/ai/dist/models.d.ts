import { type AuthResolutionOverrides } from "./auth/resolve.ts";
import type { AuthCheck, AuthContext, AuthInteraction, AuthOperationOptions, AuthResult, AuthType, Credential, CredentialStore, ProviderAuth } from "./auth/types.ts";
import { type ModelsStore, type ModelsStoreEntry } from "./models-store.ts";
import type { Api, ApiStreamOptions, AssistantMessage, AssistantMessageEventStream, Context, DeferredCancelOptions, DeferredFetchOptions, DeferredHandle, Model, ModelThinkingLevel, ProviderHeaders, ProviderStreams, SimpleStreamOptions, Usage } from "./types.ts";
export { ModelsError, type ModelsErrorCode } from "./auth/resolve.ts";
export interface ModelsPublication {
    persist?: ModelsStoreEntry | null;
    update?: () => void;
}
export interface RefreshModelsContext {
    credential?: Credential;
    stored?: Readonly<ModelsStoreEntry>;
    publish(publication: ModelsPublication): Promise<boolean>;
    allowNetwork: boolean;
    force?: boolean;
    signal: AbortSignal;
}
export interface ModelsRefreshOptions {
    allowNetwork?: boolean;
    providers?: readonly string[];
    force?: boolean;
    signal?: AbortSignal;
}
export interface ModelsRefreshResult {
    aborted: boolean;
    errors: ReadonlyMap<string, Error>;
}
export interface ModelsRequestTransforms {
    transformHeaders?: (headers: ProviderHeaders) => ProviderHeaders | Promise<ProviderHeaders>;
}
export type ModelsApiStreamOptions<TApi extends Api> = ApiStreamOptions<TApi> & ModelsRequestTransforms;
export type ModelsSimpleStreamOptions = SimpleStreamOptions & ModelsRequestTransforms;
export type ModelsDeferredFetchOptions = DeferredFetchOptions & ModelsRequestTransforms;
export type ModelsDeferredCancelOptions = DeferredCancelOptions & ModelsRequestTransforms;
export interface Provider<TApi extends Api = Api> {
    readonly id: string;
    readonly name: string;
    readonly baseUrl?: string;
    readonly headers?: ProviderHeaders;
    readonly auth: ProviderAuth;
    getModels(): readonly Model<TApi>[];
    refreshModels?(context: RefreshModelsContext): Promise<void>;
    filterModels?(models: readonly Model<TApi>[], credential: Credential | undefined): readonly Model<TApi>[];
    stream<T extends TApi>(model: Model<T>, context: Context, options?: ApiStreamOptions<T>): AssistantMessageEventStream;
    streamSimple(model: Model<TApi>, context: Context, options?: SimpleStreamOptions): AssistantMessageEventStream;
    fetchDeferred?(model: Model<TApi>, handle: DeferredHandle, options?: DeferredFetchOptions): AssistantMessageEventStream;
    cancelDeferred?(model: Model<TApi>, handle: DeferredHandle, options?: DeferredCancelOptions): Promise<void>;
}
export interface Models {
    getProviders(): readonly Provider[];
    getProvider(id: string): Provider | undefined;
    getModels(provider?: string): readonly Model<Api>[];
    getModel(provider: string, id: string): Model<Api> | undefined;
    refresh(options?: ModelsRefreshOptions): Promise<ModelsRefreshResult>;
    checkAuth(providerId: string, options?: AuthOperationOptions): Promise<AuthCheck | undefined>;
    getAvailable(providerId?: string, options?: AuthOperationOptions): Promise<readonly Model<Api>[]>;
    getAuth(providerId: string, overrides?: AuthResolutionOverrides): Promise<AuthResult | undefined>;
    getAuth(model: Model<Api>, overrides?: AuthResolutionOverrides): Promise<AuthResult | undefined>;
    login(providerId: string, type: AuthType, interaction: AuthInteraction): Promise<Credential>;
    logout(providerId: string, options?: AuthOperationOptions): Promise<void>;
    stream<TApi extends Api>(model: Model<TApi>, context: Context, options?: ModelsApiStreamOptions<TApi>): AssistantMessageEventStream;
    complete<TApi extends Api>(model: Model<TApi>, context: Context, options?: ModelsApiStreamOptions<TApi>): Promise<AssistantMessage>;
    streamSimple(model: Model<Api>, context: Context, options?: ModelsSimpleStreamOptions): AssistantMessageEventStream;
    completeSimple(model: Model<Api>, context: Context, options?: ModelsSimpleStreamOptions): Promise<AssistantMessage>;
    fetchDeferred(model: Model<Api>, handle: DeferredHandle, options?: ModelsDeferredFetchOptions): Promise<AssistantMessage>;
    cancelDeferred(model: Model<Api>, handle: DeferredHandle, options?: ModelsDeferredCancelOptions): Promise<void>;
}
export interface MutableModels extends Models {
    setProvider(provider: Provider): void;
    deleteProvider(id: string): void;
    clearProviders(): void;
}
export interface CreateModelsOptions {
    credentials?: CredentialStore;
    modelsStore?: ModelsStore;
    authContext?: AuthContext;
}
export declare function createModels(options?: CreateModelsOptions): MutableModels;
export interface CreateProviderOptions<TApi extends Api = Api> {
    id: string;
    name?: string;
    baseUrl?: string;
    headers?: ProviderHeaders;
    auth: ProviderAuth;
    models: readonly Model<TApi>[];
    fetchModels?: (context: RefreshModelsContext) => Promise<readonly Model<TApi>[]>;
    filterModels?: (models: readonly Model<TApi>[], credential: Credential | undefined) => readonly Model<TApi>[];
    api: ProviderStreams | Partial<Record<TApi, ProviderStreams>>;
}
export declare function createProvider<TApi extends Api = Api>(input: CreateProviderOptions<TApi>): Provider<TApi>;
export declare function hasApi<TApi extends Api>(model: Model<Api>, api: TApi): model is Model<TApi>;
export declare function calculateCost<TApi extends Api>(model: Model<TApi>, usage: Usage): Usage["cost"];
export declare function getSupportedThinkingLevels<TApi extends Api>(model: Model<TApi>): ModelThinkingLevel[];
export declare function clampThinkingLevel<TApi extends Api>(model: Model<TApi>, level: ModelThinkingLevel): ModelThinkingLevel;
export declare function modelsAreEqual<TApi extends Api>(a: Model<TApi> | null | undefined, b: Model<TApi> | null | undefined): boolean;
//# sourceMappingURL=models.d.ts.map