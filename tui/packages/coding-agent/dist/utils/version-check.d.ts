export interface LatestCortexRelease {
    version: string;
    packageName?: string;
    note?: string;
}
export declare function formatVersionCheckError(error: unknown): string;
export declare function comparePackageVersions(leftVersion: string, rightVersion: string): number | undefined;
export declare function isNewerPackageVersion(candidateVersion: string, currentVersion: string): boolean;
export declare function getLatestCortexRelease(currentVersion: string, options?: {
    timeoutMs?: number;
    retry?: boolean;
}): Promise<LatestCortexRelease | undefined>;
export declare function getLatestCortexVersion(currentVersion: string, options?: {
    timeoutMs?: number;
    retry?: boolean;
}): Promise<string | undefined>;
export declare function checkForNewCortexVersion(currentVersion: string): Promise<LatestCortexRelease | undefined>;
//# sourceMappingURL=version-check.d.ts.map