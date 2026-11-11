import type { AuthOperationOptions, Credential, CredentialInfo, CredentialStore } from "./types.ts";
export declare class InMemoryCredentialStore implements CredentialStore {
    private credentials;
    private chains;
    private enqueue;
    read(providerId: string, options?: AuthOperationOptions): Promise<Credential | undefined>;
    list(options?: AuthOperationOptions): Promise<readonly CredentialInfo[]>;
    modify(providerId: string, fn: (current: Credential | undefined) => Promise<Credential | undefined>, options?: AuthOperationOptions): Promise<Credential | undefined>;
    delete(providerId: string, options?: AuthOperationOptions): Promise<void>;
}
//# sourceMappingURL=credential-store.d.ts.map