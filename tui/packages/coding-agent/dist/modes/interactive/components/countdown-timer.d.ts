import type { TUI } from "@cortexagent/tui";
export declare class CountdownTimer {
    private intervalId;
    private remainingSeconds;
    private tui;
    private onTick;
    private onExpire;
    constructor(timeoutMs: number, tui: TUI | undefined, onTick: (seconds: number) => void, onExpire: () => void);
    dispose(): void;
}
//# sourceMappingURL=countdown-timer.d.ts.map