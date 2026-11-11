import { type TUI } from "@cortexagent/tui";
import { SettingsManager } from "../core/settings-manager.ts";
export declare function createStartupTui(settingsManager: SettingsManager): Promise<TUI>;
export declare function startStartupTui(ui: TUI, settingsManager: SettingsManager): void;
export declare function shouldRunFirstTimeSetup(settingsPath?: string): boolean;
export declare function showStartupSelector<T>(settingsManager: SettingsManager, title: string, options: Array<{
    label: string;
    value: T;
}>): Promise<T | undefined>;
export declare function showFirstTimeSetup(settingsManager: SettingsManager): Promise<void>;
export declare function showStartupInput(settingsManager: SettingsManager, title: string, placeholder?: string): Promise<string | undefined>;
//# sourceMappingURL=startup-ui.d.ts.map