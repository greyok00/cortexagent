import type { ModelsStore, ModelsStoreEntry, ModelsStoreOperationOptions } from "@cortexagent/ai";
export declare class InMemoryCodingAgentModelsStore implements ModelsStore {
    private readonly entries;
    read(providerId: string, options?: ModelsStoreOperationOptions): Promise<ModelsStoreEntry | undefined>;
    write(providerId: string, entry: ModelsStoreEntry, options?: ModelsStoreOperationOptions): Promise<void>;
    delete(providerId: string, options?: ModelsStoreOperationOptions): Promise<void>;
}
export declare class FileModelsStore implements ModelsStore {
    private readonly storage;
    private readonly path;
    private readonly readState;
    constructor(path?: string);
    private parse;
    private updateReadState;
    private reloadFromStorage;
    private readLatest;
    read(providerId: string, options?: ModelsStoreOperationOptions): Promise<ModelsStoreEntry | undefined>;
    write(providerId: string, entry: ModelsStoreEntry, options?: ModelsStoreOperationOptions): Promise<void>;
    delete(providerId: string, options?: ModelsStoreOperationOptions): Promise<void>;
}
//# sourceMappingURL=models-store.d.ts.map