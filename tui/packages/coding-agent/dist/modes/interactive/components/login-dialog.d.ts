import type { AuthInfoLink, OAuthDeviceCodeInfo } from "@cortexagent/ai";
import { Container, type Focusable, type TUI } from "@cortexagent/tui";
export declare class LoginDialogComponent extends Container implements Focusable {
    private contentContainer;
    private input;
    private tui;
    private abortController;
    private inputResolver?;
    private inputRejecter?;
    private onComplete;
    private _focused;
    get focused(): boolean;
    set focused(value: boolean);
    constructor(tui: TUI, providerId: string, onComplete: (success: boolean, message?: string) => void, providerNameOverride?: string, titleOverride?: string);
    get signal(): AbortSignal;
    private replaceInputWithSubmittedText;
    private cancel;
    showAuth(url: string, instructions?: string): void;
    showDeviceCode(info: OAuthDeviceCodeInfo): void;
    showManualInput(prompt: string): Promise<string>;
    showPrompt(message: string, placeholder?: string): Promise<string>;
    showDetails(lines: string[]): void;
    showInfo(message: string, links?: readonly AuthInfoLink[], showCloseHint?: boolean): void;
    showWaiting(message: string): void;
    showProgress(message: string): void;
    handleInput(data: string): void;
}
//# sourceMappingURL=login-dialog.d.ts.map