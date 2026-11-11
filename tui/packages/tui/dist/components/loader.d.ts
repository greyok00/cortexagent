import type { TUI } from "../tui.ts";
import { Text } from "./text.ts";
export interface LoaderIndicatorOptions {
    frames?: string[];
    intervalMs?: number;
}
export declare class Loader extends Text {
    private frames;
    private intervalMs;
    private currentFrame;
    private intervalId;
    private ui;
    private renderIndicatorVerbatim;
    private spinnerColorFn;
    private messageColorFn;
    private message;
    constructor(ui: TUI, spinnerColorFn: (str: string) => string, messageColorFn: (str: string) => string, message?: string, indicator?: LoaderIndicatorOptions);
    render(width: number): string[];
    start(): void;
    stop(): void;
    setMessage(message: string): void;
    setIndicator(indicator?: LoaderIndicatorOptions): void;
    private restartAnimation;
    private updateDisplay;
}
//# sourceMappingURL=loader.d.ts.map