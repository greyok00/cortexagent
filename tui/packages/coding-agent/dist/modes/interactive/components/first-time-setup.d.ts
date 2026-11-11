import { Container } from "@cortexagent/tui";
import { type TerminalTheme } from "../theme/theme.ts";
export interface FirstTimeSetupResult {
    theme: TerminalTheme;
    shareAnalytics: boolean;
}
export interface FirstTimeSetupOptions {
    detectedTheme: TerminalTheme;
    onThemePreview: (themeName: TerminalTheme) => void;
    onSubmit: (result: FirstTimeSetupResult) => void;
    onCancel: () => void;
}
export declare class FirstTimeSetupComponent extends Container {
    private themeIndex;
    private readonly options;
    constructor(options: FirstTimeSetupOptions);
    private update;
    private addOptionList;
    private moveSelection;
    handleInput(keyData: string): void;
}
//# sourceMappingURL=first-time-setup.d.ts.map