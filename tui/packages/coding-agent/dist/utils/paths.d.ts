export interface PathInputOptions {
    trim?: boolean;
    expandTilde?: boolean;
    homeDir?: string;
    stripAtPrefix?: boolean;
    normalizeUnicodeSpaces?: boolean;
}
export declare function canonicalizePath(path: string): string;
export declare function getFileRevision(path: string): string | undefined;
export declare function isLocalPath(value: string): boolean;
export declare function normalizeWindowsShellPath(filePath: string): string;
export declare function normalizePath(input: string, options?: PathInputOptions): string;
export declare function resolvePath(input: string, baseDir?: string, options?: PathInputOptions): string;
export declare function getCwdRelativePath(filePath: string, cwd: string): string | undefined;
export declare function formatPathRelativeToCwdOrAbsolute(filePath: string, cwd: string): string;
export declare function markPathIgnoredByCloudSync(path: string): void;
//# sourceMappingURL=paths.d.ts.map