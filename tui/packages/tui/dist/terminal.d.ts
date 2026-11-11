export type KeyboardProtocolNegotiationSequence = {
    type: "kitty-flags";
    flags: number;
} | {
    type: "device-attributes";
};
export declare function parseKeyboardProtocolNegotiationSequence(sequence: string): KeyboardProtocolNegotiationSequence | undefined;
export declare function isAppleTerminalSession(): boolean;
export declare function normalizeNativeShiftEnterInput(data: string, shouldDetectNativeShiftEnter: boolean, isShiftPressed: boolean): string;
export declare function normalizeAppleTerminalInput(data: string, isAppleTerminal: boolean, isShiftPressed: boolean): string;
export interface Terminal {
    start(onInput: (data: string) => void, onResize: () => void): void;
    stop(): void;
    drainInput(maxMs?: number, idleMs?: number): Promise<void>;
    write(data: string): void;
    get columns(): number;
    get rows(): number;
    get kittyProtocolActive(): boolean;
    moveBy(lines: number): void;
    hideCursor(): void;
    showCursor(): void;
    clearLine(): void;
    clearFromCursor(): void;
    clearScreen(): void;
    setTitle(title: string): void;
    setProgress(active: boolean): void;
}
export declare function resolveEscapeTimeoutMs(env?: NodeJS.ProcessEnv): number;
export declare class ProcessTerminal implements Terminal {
    private wasRaw;
    private inputHandler?;
    private resizeHandler?;
    private _kittyProtocolActive;
    private _modifyOtherKeysActive;
    private keyboardProtocolPushed;
    private keyboardProtocolNegotiationBuffer;
    private keyboardProtocolBufferFlushTimer?;
    private stdinBuffer?;
    private stdinDataHandler?;
    private progressInterval?;
    private writeLogPath;
    get kittyProtocolActive(): boolean;
    get modifyOtherKeysActive(): boolean;
    start(onInput: (data: string) => void, onResize: () => void): void;
    private setupStdinBuffer;
    private queryAndEnableKittyProtocol;
    private handleKeyboardProtocolNegotiationSequence;
    private readKeyboardProtocolNegotiationSequence;
    private setKeyboardProtocolNegotiationBuffer;
    private clearKeyboardProtocolNegotiationBuffer;
    private flushKeyboardProtocolNegotiationBufferAsInput;
    private scheduleKeyboardProtocolNegotiationBufferFlush;
    private clearKeyboardProtocolNegotiationBufferFlushTimer;
    private forwardInputSequence;
    private enableModifyOtherKeys;
    private disableModifyOtherKeys;
    private enableWindowsVTInput;
    drainInput(maxMs?: number, idleMs?: number): Promise<void>;
    stop(): void;
    write(data: string): void;
    get columns(): number;
    get rows(): number;
    moveBy(lines: number): void;
    hideCursor(): void;
    showCursor(): void;
    clearLine(): void;
    clearFromCursor(): void;
    clearScreen(): void;
    setTitle(title: string): void;
    setProgress(active: boolean): void;
    private clearProgressInterval;
}
//# sourceMappingURL=terminal.d.ts.map