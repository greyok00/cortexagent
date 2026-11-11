import type { Api, Model } from "./types.ts";
export interface ModelsStoreEntry {
    models: readonly Model<Api>[];
    lastModified?: number;
    checkedAt?: number;
    etag?: string;
}
export interface ModelsStoreOperationOptions {
    signal?: AbortSignal;
}
export interface ModelsStore {
    read(providerId: string, options?: ModelsStoreOperationOptions): Promise<ModelsStoreEntry | undefined>;
    write(providerId: string, entry: ModelsStoreEntry, options?: ModelsStoreOperationOptions): Promise<void>;
    delete(providerId: string, options?: ModelsStoreOperationOptions): Promise<void>;
}
export declare class InMemoryModelsStore implements ModelsStore {
    private readonly entries;
    read(providerId: string, options?: ModelsStoreOperationOptions): Promise<ModelsStoreEntry | undefined>;
    write(providerId: string, entry: ModelsStoreEntry, options?: ModelsStoreOperationOptions): Promise<void>;
    delete(providerId: string, options?: ModelsStoreOperationOptions): Promise<void>;
}
//# sourceMappingURL=models-store.d.ts.map