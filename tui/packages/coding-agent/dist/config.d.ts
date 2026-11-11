export declare const isBunBinary: boolean;
export declare const isBunRuntime: boolean;
export type InstallMethod = "bun-binary" | "npm" | "pnpm" | "yarn" | "bun" | "unknown";
interface SelfUpdateCommandStep {
    command: string;
    args: string[];
    display: string;
}
export interface SelfUpdateCommand extends SelfUpdateCommandStep {
    steps?: SelfUpdateCommandStep[];
}
export type SelfUpdatePackageTarget = string | {
    packageName: string;
    installSpec?: string;
};
export declare function detectInstallMethod(): InstallMethod;
export declare function getSelfUpdateCommand(packageName: string, npmCommand?: string[], updatePackageTarget?: SelfUpdatePackageTarget): SelfUpdateCommand | undefined;
export declare function getSelfUpdateUnavailableInstruction(packageName: string, npmCommand?: string[], updatePackageTarget?: SelfUpdatePackageTarget): string;
export declare function getUpdateInstruction(packageName: string): string;
export declare function getPackageDir(): string;
export declare function getThemesDir(): string;
export declare function getExportTemplateDir(): string;
export declare function getPackageJsonPath(): string;
export declare function getExamplesPath(): string;
export declare function getInteractiveAssetsDir(): string;
export declare function getBundledInteractiveAssetPath(name: string): string;
export declare const PACKAGE_NAME: string;
export declare const APP_NAME: string;
export declare const APP_TITLE: string;
export declare const CONFIG_DIR_NAME: string;
export declare const VERSION: string;
export declare const ENV_AGENT_DIR: string;
export declare const ENV_SESSION_DIR: string;
export declare function expandTildePath(path: string): string;
export declare function getShareViewerUrl(gistId: string): string;
export declare function getAgentDir(): string;
export declare function getCustomThemesDir(): string;
export declare function getModelsPath(): string;
export declare function getAuthPath(): string;
export declare function getSettingsPath(): string;
export declare function getToolsDir(): string;
export declare function getBinDir(): string;
export declare function getPromptsDir(): string;
export declare function getSessionsDir(): string;
export declare function getDebugLogPath(): string;
export {};
//# sourceMappingURL=config.d.ts.map