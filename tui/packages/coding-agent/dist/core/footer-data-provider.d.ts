export type GitPaths = {
    repoDir: string;
    commonGitDir: string;
    headPath: string;
};
export declare function findGitPaths(cwd: string): GitPaths | null;
export declare class FooterDataProvider {
    private cwd;
    private static readonly WATCH_DEBOUNCE_MS;
    private extensionStatuses;
    private cachedBranch;
    private gitPaths;
    private headWatcher;
    private headWatchFilePath;
    private headWatchFileListener;
    private reftableWatcher;
    private reftableTablesListWatcher;
    private reftableTablesListPath;
    private branchChangeCallbacks;
    private availableProviderCount;
    private refreshTimer;
    private gitWatcherRetryTimer;
    private refreshInFlight;
    private refreshPending;
    private disposed;
    constructor(cwd: string);
    getGitBranch(): string | null;
    getExtensionStatuses(): ReadonlyMap<string, string>;
    onBranchChange(callback: () => void): () => void;
    setExtensionStatus(key: string, text: string | undefined): void;
    clearExtensionStatuses(): void;
    getAvailableProviderCount(): number;
    setAvailableProviderCount(count: number): void;
    setCwd(cwd: string): void;
    dispose(): void;
    private notifyBranchChange;
    private scheduleRefresh;
    private refreshGitBranchAsync;
    private resolveGitBranchSync;
    private resolveGitBranchAsync;
    private clearGitWatchers;
    private scheduleGitWatcherRetry;
    private handleGitWatcherError;
    private setupGitWatcher;
}
export type ReadonlyFooterDataProvider = Pick<FooterDataProvider, "getGitBranch" | "getExtensionStatuses" | "getAvailableProviderCount" | "onBranchChange">;
//# sourceMappingURL=footer-data-provider.d.ts.map