export interface ShellConfig {
    shell: string;
    args: string[];
    commandTransport?: "argv" | "stdin";
}
export declare function getShellConfig(customShellPath?: string): ShellConfig;
export declare function getShellEnv(): NodeJS.ProcessEnv;
export declare function sanitizeBinaryOutput(str: string): string;
export declare function trackDetachedChildPid(pid: number): void;
export declare function untrackDetachedChildPid(pid: number): void;
export declare function killTrackedDetachedChildren(): void;
export declare function killProcessTree(pid: number): void;
//# sourceMappingURL=shell.d.ts.map