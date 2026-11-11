import type { SettingsManager } from "../core/settings-manager.ts";
import { type ScopedResolvedPaths } from "../modes/interactive/components/config-selector.ts";
export interface ConfigSelectorOptions {
    resolvedPaths: ScopedResolvedPaths;
    settingsManager: SettingsManager;
    cwd: string;
    agentDir: string;
    writeScope: "global" | "project";
    projectModeAvailable: boolean;
}
export declare function selectConfig(options: ConfigSelectorOptions): Promise<void>;
//# sourceMappingURL=config-selector.d.ts.map