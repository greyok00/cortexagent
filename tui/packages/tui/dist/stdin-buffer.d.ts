import { EventEmitter } from "events";
export type StdinBufferOptions = {
    timeout?: number;
    escapeTimeout?: number;
};
export type StdinBufferEventMap = {
    data: [string];
    paste: [string];
};
export declare class StdinBuffer extends EventEmitter<StdinBufferEventMap> {
    private buffer;
    private timeout;
    private readonly timeoutMs;
    private readonly escapeTimeoutMs;
    private pasteMode;
    private pasteBuffer;
    private pendingKittyPrintableCodepoint;
    constructor(options?: StdinBufferOptions);
    process(data: string | Buffer): void;
    private emitDataSequence;
    flush(): string[];
    clear(): void;
    getBuffer(): string;
    destroy(): void;
}
//# sourceMappingURL=stdin-buffer.d.ts.map