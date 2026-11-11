export declare class KillRing {
    private ring;
    push(text: string, opts: {
        prepend: boolean;
        accumulate?: boolean;
    }): void;
    peek(): string | undefined;
    rotate(): void;
    get length(): number;
}
//# sourceMappingURL=kill-ring.d.ts.map